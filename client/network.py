import socket
import json
import threading
import struct
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
    "heartbeat",
    "resume_session",  # token-only
}


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

    def _run(self):
        if self._abort_event.is_set():
            return

        try:
            host = self.host
            port = self.port
            if not host or not port:
                host, port = get_api_endpoint()

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)
                s.connect((host, int(port)))
                if self._abort_event.is_set():
                    return

                payload_obj = self._prepare_payload()
                send_json_packet(s, payload_obj)
                if self._abort_event.is_set():
                    return

                obj = recv_json_packet(s)
                if self._abort_event.is_set():
                    return

                if not obj:
                    self._emit_if_alive({"status": "error", "message": "Пустой или некорректный ответ от сервера"})
                    return

                self._emit_if_alive(obj)

        except socket.timeout:
            self._emit_if_alive({"status": "error", "message": "Таймаут сети"})
        except ConnectionRefusedError:
            self._emit_if_alive({"status": "error", "message": "Сервер не запущен"})
        except OSError as e:
            self._emit_if_alive({"status": "error", "message": f"Ошибка сокета: {e}"})
        except Exception as e:
            self._emit_if_alive({"status": "error", "message": f"Ошибка сети: {e}"})
