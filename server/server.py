# Preserve direct script entry points while sharing the wire protocol package.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from .server_transport.tls import server_context
    from .server_transport.framing import receive as recv_request
    from .server_transport.admission import Admission
    from .protocol.requests import validate as validate_request
except ImportError:
    from server_transport.tls import server_context
    from server_transport.framing import receive as recv_request
    from server_transport.admission import Admission
    from protocol.requests import validate as validate_request

try:
    from .storage.migrations import migrate as migrate_database
    from .services.calls import CallService
    from .services.channels import ChannelService
    from .services.accounts import AccountService
    from .services.events import EventService
    from .protocol.router import RequestRouter
    from .services.friends import FriendshipService
    from .storage.messages import MessageRepository
    from .domain.passwords import hash_password, verify_password, maybe_upgrade_legacy_password
    from .services import mutations, channel_cleanup
except ImportError:
    from storage.migrations import migrate as migrate_database
    from services.calls import CallService
    from services.channels import ChannelService
    from services.accounts import AccountService
    from services.events import EventService
    from protocol.router import RequestRouter
    from services.friends import FriendshipService
    from storage.messages import MessageRepository
    from domain.passwords import hash_password, verify_password, maybe_upgrade_legacy_password
    from services import mutations, channel_cleanup

try:
    from .storage.database import connect as database_connection
except ImportError:
    from storage.database import connect as database_connection

import datetime as dt
import json
import os
import socket
import sqlite3
import struct
import threading
import time
from typing import Any, Dict, Optional

# -------------------- Paths / DB --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def resolve_db_path(filename: str) -> str:
    """Resolve DB path.

    Backward compatible: if a file exists in the current working directory but
    not in BASE_DIR, we keep using it to avoid losing data.
    """
    cwd_path = os.path.abspath(filename)
    base_path = os.path.join(BASE_DIR, filename)
    if os.path.exists(cwd_path) and not os.path.exists(base_path):
        return cwd_path
    return base_path


DB_FILE = os.environ.get("NODYS_DB_FILE") or resolve_db_path("users.db")
CHAT_DB = os.environ.get("NODYS_CHAT_DB") or resolve_db_path("voice_chat.db")

# -------------------- Presence / Sessions --------------------
SESSION_TTL_SEC = 60 * 60 * 24 * 30  # 30 days
ONLINE_WINDOW_SEC = 45               # considered online if seen within this window
SESSION_TOUCH_MIN_INTERVAL_SEC = 3     # reduce DB write contention on frequent polling

# -------------------- Events / Calls --------------------
EVENT_MAX_PER_USER = 200
EVENT_TTL_SEC = 180
CALL_STALE_SEC = 25  # if one side stops sending heartbeats/polls, auto-release call

from functools import lru_cache

@lru_cache(maxsize=8)
def _accounts_for_path(path):
    return AccountService(path, _now_utc, _iso, SESSION_TTL_SEC, ONLINE_WINDOW_SEC, SESSION_TOUCH_MIN_INTERVAL_SEC)


@lru_cache(maxsize=8)
def _events_for_path(path):
    return EventService(path, _now_utc, _iso, EVENT_MAX_PER_USER, EVENT_TTL_SEC)


def _events_service():
    return _events_for_path(DB_FILE)


def _accounts_service():
    return _accounts_for_path(DB_FILE)


def _friends_service():
    return FriendshipService(DB_FILE, _accounts_service(), _call_service())


def _messages_service():
    return MessageRepository(CHAT_DB)

# -------------------- Protocol (length‑prefix) --------------------

def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf


def send_response(conn: socket.socket, obj: Dict[str, Any]) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    conn.sendall(struct.pack("!I", len(payload)) + payload)


# -------------------- DB init --------------------

def init_db() -> None:
    migrate_database(DB_FILE, "users")


def init_chat_db() -> None:
    migrate_database(CHAT_DB, "chat")
    channel_cleanup.drain(DB_FILE, CHAT_DB)


# -------------------- Sessions / Presence helpers --------------------

def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime) -> str:
    return ts.isoformat()


def cleanup_expired_sessions():
    return _accounts_service().cleanup_expired_sessions()


def create_session(login: str):
    return _accounts_service().create_session(login)


def get_session_by_token(token: str):
    return _accounts_service().get_session_by_token(token)


def touch_session(token: str):
    return _accounts_service().touch_session(token)

def delete_session(token: str):
    return _accounts_service().delete_session(token)


def set_session_offline(token: str):
    return _accounts_service().set_session_offline(token)


def is_online(login: str):
    return _accounts_service().is_online(login)


def require_auth(data: Dict[str, Any]):
    return _accounts_service().require_auth(data)


# -------------------- Events helpers --------------------

def push_event(login: str, event: Dict[str, Any]):
    return _events_service().push_event(login, event)


def _publish_legacy_event(login, event):
    return _events_service()._publish_legacy_event(login, event)


def pop_events(login: str):
    return _events_service().pop_events(login)


# -------------------- User operations --------------------

def user_exists(login: str):
    return _accounts_service().user_exists(login)


def add_user(login: str, password: str, nickname: str, avatar: str):
    return _accounts_service().add_user(login, password, nickname, avatar)


def authenticate(login: str, password: str):
    return _accounts_service().authenticate(login, password)


def get_user_info(login: str):
    return _accounts_service().get_user_info(login)


def update_user_profile(login: str, nickname: str, password: Optional[str], avatar: Optional[str], keep_token: str=''):
    return _accounts_service().update_user_profile(login, nickname, password, avatar, keep_token)


# -------------------- Friends / Requests --------------------

def send_friend_request(from_user: str, to_user: str):
    return _friends_service().send_friend_request(from_user, to_user)


def get_friend_requests(to_user: str):
    return _friends_service().get_friend_requests(to_user)


def accept_friend_request(from_user: str, to_user: str):
    return _friends_service().accept_friend_request(from_user, to_user)


def decline_friend_request(from_user: str, to_user: str):
    return _friends_service().decline_friend_request(from_user, to_user)


def get_friends(login: str):
    return _friends_service().get_friends(login)


def are_friends(user_a: str, user_b: str):
    return _friends_service().are_friends(user_a, user_b)


def remove_friend(current_user: str, friend_login: str):
    return _friends_service().remove_friend(current_user, friend_login)


# -------------------- Chat (messages) --------------------

def save_message(from_user: str, to_user: str, text: str):
    return _messages_service().save_message(from_user, to_user, text)


def get_messages(user_a: str, user_b: str, limit: int=50):
    return _messages_service().get_messages(user_a, user_b, limit)


def mark_chat_read(current_user: str, friend: str):
    return _messages_service().mark_chat_read(current_user, friend)


def get_unread_counts(current_user: str):
    return _messages_service().get_unread_counts(current_user)


# -------------------- Channels --------------------

def _channel_service():
    return ChannelService(DB_FILE, CHAT_DB, _now_utc, _iso, ONLINE_WINDOW_SEC)


def _generate_channel_code(conn: sqlite3.Connection, length: int=8):
    return _channel_service()._generate_channel_code(conn, length)


def create_channel(owner_login: str, name: str, avatar: str=''):
    return _channel_service().create_channel(owner_login, name, avatar)


def list_user_channels(login: str):
    return _channel_service().list_user_channels(login)


def get_channel_by_id(channel_id: int):
    return _channel_service().get_channel_by_id(channel_id)


def is_channel_member(channel_id: int, login: str):
    return _channel_service().is_channel_member(channel_id, login)


def join_channel_by_code(login: str, code: str):
    return _channel_service().join_channel_by_code(login, code)


def send_channel_invite(actor_login: str, channel_id: int, target_login: str):
    return _channel_service().send_channel_invite(actor_login, channel_id, target_login)


def get_incoming_channel_invites(login: str):
    return _channel_service().get_incoming_channel_invites(login)


def respond_channel_invite(login: str, invite_id: int, accept: bool):
    return _channel_service().respond_channel_invite(login, invite_id, accept)


def get_channel_messages(channel_id: int, limit: int=200):
    return _channel_service().get_channel_messages(channel_id, limit)


def save_channel_message(channel_id: int, from_user: str, text: str):
    return _channel_service().save_channel_message(channel_id, from_user, text)


def _normalize_member_role(role: str):
    return _channel_service()._normalize_member_role(role)


def _normalize_min_access_role(role: str):
    return _channel_service()._normalize_min_access_role(role)


def _has_min_role(user_role: str, min_role: str):
    return _channel_service()._has_min_role(user_role, min_role)


def _channel_member_role(conn: sqlite3.Connection, channel_id: int, login: str):
    return _channel_service()._channel_member_role(conn, channel_id, login)


def _role_permissions(role: str, text_min_role: str='member', voice_min_role: str='member'):
    return _channel_service()._role_permissions(role, text_min_role, voice_min_role)


def _channel_online_map(conn: sqlite3.Connection):
    return _channel_service()._channel_online_map(conn)


def _channel_members_details(conn: sqlite3.Connection, channel_id: int, owner_login: str):
    return _channel_service()._channel_members_details(conn, channel_id, owner_login)


def _get_channel_and_my_role(conn: sqlite3.Connection, channel_id: int, login: str):
    return _channel_service()._get_channel_and_my_role(conn, channel_id, login)


def _can_send_text(conn: sqlite3.Connection, channel_id: int, login: str):
    return _channel_service()._can_send_text(conn, channel_id, login)


def _can_join_voice(conn: sqlite3.Connection, channel_id: int, login: str):
    return _channel_service()._can_join_voice(conn, channel_id, login)


def _cleanup_channel_voice_presence(conn: sqlite3.Connection, channel_id: Optional[int]=None):
    return _channel_service()._cleanup_channel_voice_presence(conn, channel_id)


def set_channel_voice_presence(login: str, channel_id: int, speaking: bool=False, joined: bool=True, token: str='', sequence=None):
    return _channel_service().set_channel_voice_presence(login, channel_id, speaking, joined, token, sequence)


def leave_channel_voice(login: str, channel_id: int, token: str='', sequence=None):
    return _channel_service().leave_channel_voice(login, channel_id, token, sequence)


def get_channel_voice_participants(channel_id: int, login: str):
    return _channel_service().get_channel_voice_participants(channel_id, login)


def get_channel_details_for_user(channel_id: int, login: str):
    return _channel_service().get_channel_details_for_user(channel_id, login)


def update_channel_settings(actor_login: str, channel_id: int, name: str, avatar: str, text_min_role: str='member', voice_min_role: str='member'):
    return _channel_service().update_channel_settings(actor_login, channel_id, name, avatar, text_min_role, voice_min_role)


def regenerate_channel_code(actor_login: str, channel_id: int):
    return _channel_service().regenerate_channel_code(actor_login, channel_id)


def set_channel_member_role(actor_login: str, channel_id: int, target_login: str, role: str):
    return _channel_service().set_channel_member_role(actor_login, channel_id, target_login, role)


def remove_channel_member(actor_login: str, channel_id: int, target_login: str):
    return _channel_service().remove_channel_member(actor_login, channel_id, target_login)


def leave_channel(login: str, channel_id: int):
    return _channel_service().leave_channel(login, channel_id)


def delete_channel(actor_login: str, channel_id: int):
    return _channel_service().delete_channel(actor_login, channel_id)


# -------------------- Calls --------------------

def _call_service():
    return CallService(DB_FILE, _publish_legacy_event, CALL_STALE_SEC, ONLINE_WINDOW_SEC)


def start_call(from_user, to_user):
    prune_stale_calls()
    return _call_service().start(from_user, to_user)


def mark_call_activity(user):
    if user:
        _call_service().touch(user)


def prune_stale_calls():
    _call_service().prune()


def accept_call(current_user, from_user):
    prune_stale_calls()
    return _call_service().accept(current_user, from_user)


def decline_call(current_user, from_user):
    prune_stale_calls()
    return _call_service().finish(current_user, from_user, decline=True)


def end_call(current_user, with_user):
    return _call_service().finish(current_user, with_user)


def cleanup_calls_for_user(user):
    _call_service().finish(user)


# -------------------- Request dispatcher --------------------

def handle_request(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        validate_request(data)
    except ValueError as error:
        return {"status":"error", "code":"invalid_request", "message":str(error)}
    prune_stale_calls()
    if data['action'] in mutations.ACTIONS:
        # Validate before returning a receipt, then revalidate inside the write lock.
        _, _, error = require_auth(data)
        if error:
            return error
        result = mutations.execute(DB_FILE, CHAT_DB, data, lambda: _dispatch_request(data))
        if data["action"] == "delete_channel" and result.get("status") == "ok":
            channel_cleanup.drain(DB_FILE, CHAT_DB)
        return result
    return _dispatch_request(data)


def _dispatch_request(data: Dict[str, Any]) -> Dict[str, Any]:
    return RequestRouter(DB_FILE, _accounts_service(), _friends_service(), _messages_service(),
                         _channel_service(), _call_service(), _events_service()).dispatch(data)


# -------------------- Server loop --------------------

_admission = Admission()


def handle_client(conn: socket.socket, addr, tls_context=None):
    try:
        conn.settimeout(5.0)
        if tls_context is not None:
            conn = tls_context.wrap_socket(conn, server_side=True)
        data = recv_request(conn)
        if not data:
            send_response(conn, {"status": "error", "message": "Пустой запрос"})
            return
        validate_request(data)
        if data['action'] in ('login','register') and not _admission.allow_auth(addr[0],data.get('login','')):
            send_response(conn, {"status":"error", "code":"rate_limited",
                                 "message":"Слишком много попыток. Повторите через минуту.", "retry_after":60})
            return
        resp = handle_request(data)
        send_response(conn, resp)
    except (ValueError, TimeoutError) as error:
        try:
            send_response(conn, {"status":"error", "code":"invalid_request", "message":"Некорректный или незавершённый запрос"})
        except Exception:
            pass
    except Exception:
        try:
            send_response(conn, {"status": "error", "code":"internal_error", "message": "Внутренняя ошибка сервера"})
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_server(host: str = None, port: int = None):
    host = host or os.environ.get("NODYS_HOST", "127.0.0.1")
    port = int(port if port is not None else os.environ.get("NODYS_PORT", "5555"))
    tls_context = server_context(host)
    init_db()
    init_chat_db()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(20)
    server.settimeout(1)
    next_cleanup = time.monotonic() + 30
    print(f"[SERVER] TCP listening on {host}:{port}")

    slots = threading.BoundedSemaphore(64)
    def serve(conn, addr):
        try:
            handle_client(conn, addr, tls_context)
        finally:
            slots.release()
    while True:
        if time.monotonic() >= next_cleanup:
            channel_cleanup.drain(DB_FILE, CHAT_DB)
            next_cleanup = time.monotonic() + 30
        try:
            conn, addr = server.accept()
        except socket.timeout:
            continue
        if not _admission.connections.allow(addr[0]) or not slots.acquire(blocking=False):
            conn.close()
            continue
        try:
            threading.Thread(target=serve, args=(conn, addr), daemon=True).start()
        except Exception:
            conn.close()
            slots.release()
            raise


if __name__ == "__main__":
    start_server()
