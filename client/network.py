import socket
import json
import threading
import struct
import time
import random
from dataclasses import dataclass
from typing import Optional, Dict, Any

from PySide6.QtCore import QObject, Signal

from user_context import UserContext
from settings import get_api_endpoint


# Actions that require a valid session token.
AUTH_ACTIONS = {
    "logout",
    "update_profile",
    "status",
    "send_friend_request",
    "get_friend_requests",
    "accept_friend_request",
    "decline_friend_request",
    "get_friends",
    "remove_friend",
    "send_message",
    "get_messages",
    "mark_chat_read",
    "get_unread_counts",
    "call_user",
    "poll_events",
    "accept_call",
    "decline_call",
    "end_call",
    "release_call_state",
    "presence_offline",
    "heartbeat",
    "find_user",
    "resume_session",  # token-only
    "create_channel",
    "join_channel",
    "get_my_channels",
    "send_channel_invite",
    "get_my_channel_invites",
    "respond_channel_invite",
    "get_channel_messages",
    "send_channel_message",
    "get_channel_details",
    "update_channel_settings",
    "regenerate_channel_code",
    "set_channel_member_role",
    "remove_channel_member",
    "leave_channel",
    "delete_channel",
    "set_channel_voice_presence",
    "leave_channel_voice",
    "get_channel_voice_participants",
}

# Действия без автоповтора при сетевых ошибках.
# Для мутаций это предотвращает дубль side-effect на сервере.
NO_RETRY_ACTIONS = {
    "register",
    "login",
    "logout",
    "update_profile",
    "send_friend_request",
    "accept_friend_request",
    "decline_friend_request",
    "remove_friend",
    "send_message",
    "create_channel",
    "join_channel",
    "send_channel_invite",
    "respond_channel_invite",
    "send_channel_message",
    "update_channel_settings",
    "regenerate_channel_code",
    "set_channel_member_role",
    "remove_channel_member",
    "leave_channel",
    "delete_channel",
    "call_user",
    "accept_call",
    "decline_call",
    "end_call",
}

# Идемпотентные state-update действия: можно повторять аккуратно.
STATEFUL_RETRY_ACTIONS = {
    "heartbeat",
    "status",
    "check_online",
    "resume_session",
    "release_call_state",
    "presence_offline",
    "set_channel_voice_presence",
    "leave_channel_voice",
    "mark_chat_read",
}

# Чистые poll/read действия: ретраи допустимы и полезны.
POLL_RETRY_ACTIONS = {
    "find_user",
    "get_friend_requests",
    "get_friends",
    "get_messages",
    "get_unread_counts",
    "get_my_channels",
    "get_my_channel_invites",
    "get_channel_messages",
    "get_channel_details",
    "get_channel_voice_participants",
    "poll_events",
}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay: float
    max_delay: float
    jitter: float


NO_RETRY_POLICY = RetryPolicy(max_attempts=1, base_delay=0.0, max_delay=0.0, jitter=0.0)
STATEFUL_RETRY_POLICY = RetryPolicy(max_attempts=2, base_delay=0.14, max_delay=0.45, jitter=0.03)
POLL_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay=0.10, max_delay=0.70, jitter=0.04)


def retry_policy_for_action(action: str) -> RetryPolicy:
    a = (action or "").strip()
    if a in NO_RETRY_ACTIONS:
        return NO_RETRY_POLICY
    if a in STATEFUL_RETRY_ACTIONS:
        return STATEFUL_RETRY_POLICY
    if a in POLL_RETRY_ACTIONS:
        return POLL_RETRY_POLICY
    # По умолчанию не повторяем неизвестные мутации.
    return NO_RETRY_POLICY


def _is_retryable_error(payload: dict) -> bool:
    msg = str((payload or {}).get("message", "")).lower()
    return (
        "таймаут" in msg
        or "сервер не запущен" in msg
        or "ошибка сокета" in msg
        or "пустой" in msg
        or "некорректный ответ" in msg
    )


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf


def send_json_packet(sock: socket.socket, obj: Dict[str, Any]) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def recv_json_packet(sock: socket.socket, max_bytes: int = 10_000_000) -> Optional[Dict[str, Any]]:
    """Read one response.

    Supports both the new length-prefixed protocol and legacy raw-JSON replies.
    """
    header = _recv_exact(sock, 4)
    if not header:
        return None

    # Legacy detection: JSON usually starts with '{' or '['.
    if header[:1] in (b"{", b"["):
        data = header
        # Read until socket closes or we get a valid JSON.
        sock.settimeout(0.4)
        while len(data) < max_bytes:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
        try:
            return json.loads(data.decode("utf-8"))
        except Exception:
            return None

    length = struct.unpack("!I", header)[0]
    if length <= 0 or length > max_bytes:
        return None
    payload = _recv_exact(sock, length)
    if not payload:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return None


class NetworkThread(QObject):
    """Threaded one-shot network request.

    Drop-in replacement for older QThread-based logic.
    """

    finished = Signal(dict)

    def __init__(self, host: Optional[str], port: Optional[int], data: Dict[str, Any]):
        super().__init__()
        self.host = host
        self.port = port
        self.data = data

        self._abort_event = threading.Event()
        self._thread = None

    # ---------------- compatibility API ----------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def isRunning(self):
        return self._thread is not None and self._thread.is_alive()

    def wait(self, ms=0):
        if not self._thread:
            return True
        timeout = None if ms is None or ms <= 0 else ms / 1000.0
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

    def abort(self):
        self._abort_event.set()

    def requestInterruption(self):
        self.abort()

    def quit(self):
        self.abort()

    # ---------------- internal ----------------
    def _emit_if_alive(self, payload: dict):
        if not self._abort_event.is_set():
            self.finished.emit(payload)

    def _prepare_payload(self) -> Dict[str, Any]:
        obj = dict(self.data or {})
        action = obj.get("action")
        ctx = UserContext()

        if action in AUTH_ACTIONS:
            token = getattr(ctx, "session_token", "")
            if token and "token" not in obj:
                obj["token"] = token

            # ВАЖНО:
            # Не перезаписываем явные login/from_user из payload.
            # Для accept/decline (дружба/звонок) поле from_user означает
            # ИСТОЧНИКА запроса/звонка, и подмена ломает логику.
            # Добавляем только отсутствующие поля для совместимости.
            if "login" not in obj and getattr(ctx, "login", ""):
                obj["login"] = ctx.login

            if action in {"send_friend_request", "send_message", "call_user", "get_messages"}:
                if "from_user" not in obj and getattr(ctx, "login", ""):
                    obj["from_user"] = ctx.login

        return obj

    def _sleep_abortable(self, sec: float):
        left = max(0.0, float(sec))
        while left > 0 and not self._abort_event.is_set():
            chunk = min(0.05, left)
            time.sleep(chunk)
            left -= chunk

    def _run(self):
        if self._abort_event.is_set():
            return

        try:
            host = self.host
            port = self.port
            if not host or not port:
                host, port = get_api_endpoint()

            payload_obj = self._prepare_payload()
            action = str(payload_obj.get("action") or "").strip()
            policy = retry_policy_for_action(action)
            max_attempts = max(1, int(policy.max_attempts))

            last_err = None
            for attempt in range(1, max_attempts + 1):
                if self._abort_event.is_set():
                    return
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(3.0)
                        s.connect((host, int(port)))
                        if self._abort_event.is_set():
                            return

                        send_json_packet(s, payload_obj)
                        if self._abort_event.is_set():
                            return

                        obj = recv_json_packet(s)
                        if self._abort_event.is_set():
                            return

                    if not obj:
                        last_err = {"status": "error", "message": "Пустой или некорректный ответ от сервера"}
                        if attempt < max_attempts and _is_retryable_error(last_err):
                            delay = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
                            if policy.jitter > 0:
                                delay += random.uniform(0.0, policy.jitter)
                            self._sleep_abortable(delay)
                            continue
                        self._emit_if_alive(last_err)
                        return

                    self._emit_if_alive(obj)
                    return

                except socket.timeout:
                    last_err = {"status": "error", "message": "Таймаут сети"}
                    if attempt < max_attempts and _is_retryable_error(last_err):
                        delay = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
                        if policy.jitter > 0:
                            delay += random.uniform(0.0, policy.jitter)
                        self._sleep_abortable(delay)
                        continue
                    self._emit_if_alive(last_err)
                    return
                except ConnectionRefusedError:
                    last_err = {"status": "error", "message": "Сервер не запущен"}
                    if attempt < max_attempts and _is_retryable_error(last_err):
                        delay = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
                        if policy.jitter > 0:
                            delay += random.uniform(0.0, policy.jitter)
                        self._sleep_abortable(delay)
                        continue
                    self._emit_if_alive(last_err)
                    return
                except OSError as e:
                    last_err = {"status": "error", "message": f"Ошибка сокета: {e}"}
                    if attempt < max_attempts and _is_retryable_error(last_err):
                        delay = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
                        if policy.jitter > 0:
                            delay += random.uniform(0.0, policy.jitter)
                        self._sleep_abortable(delay)
                        continue
                    self._emit_if_alive(last_err)
                    return

            if last_err is not None:
                self._emit_if_alive(last_err)

        except socket.timeout:
            self._emit_if_alive({"status": "error", "message": "Таймаут сети"})
        except ConnectionRefusedError:
            self._emit_if_alive({"status": "error", "message": "Сервер не запущен"})
        except OSError as e:
            self._emit_if_alive({"status": "error", "message": f"Ошибка сокета: {e}"})
        except Exception as e:
            self._emit_if_alive({"status": "error", "message": f"Ошибка сети: {e}"})
