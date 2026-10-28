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
    from .storage import events as event_store
    from .storage import voice_tickets
    from .storage.migrations import migrate as migrate_database
    from .services.calls import CallService
    from .services.channels import ChannelService
    from .services import mutations, channel_cleanup
except ImportError:
    from storage import events as event_store
    from storage import voice_tickets
    from storage.migrations import migrate as migrate_database
    from services.calls import CallService
    from services.channels import ChannelService
    from services import mutations, channel_cleanup

try:
    from .domain.avatars import normalize_avatar
except ImportError:
    from domain.avatars import normalize_avatar

try:
    from .domain.presence_order import accept_update
except ImportError:
    from domain.presence_order import accept_update

try:
    from .storage.database import connect as database_connection
except ImportError:
    from storage.database import connect as database_connection

try:
    from .domain.authorization import session_valid, channel_voice_allowed
except ImportError:
    from domain.authorization import session_valid, channel_voice_allowed

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import socket
import sqlite3
import struct
import random
import string
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional, Tuple, List

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

# per user event queue
pending_events: Dict[str, deque] = defaultdict(lambda: deque(maxlen=EVENT_MAX_PER_USER))
events_lock = threading.Lock()

# session touch throttling to avoid sqlite write storms with multiple windows
_session_touch_cache: Dict[str, float] = {}
_session_touch_lock = threading.Lock()


# -------------------- Password hashing --------------------
PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERS = 200_000


def hash_password(password: str, iterations: int = PBKDF2_ITERS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return (
        f"{PBKDF2_PREFIX}${iterations}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(dk).decode('ascii')}"
    )


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith(PBKDF2_PREFIX + "$"):
        try:
            _, it_s, salt_b64, dk_b64 = stored.split("$", 3)
            iterations = int(it_s)
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(dk_b64.encode("ascii"))
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
            return hmac.compare_digest(dk, expected)
        except Exception:
            return False
    # legacy plaintext
    return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))


def maybe_upgrade_legacy_password(conn: sqlite3.Connection, login: str, stored: str, password: str) -> None:
    """If password was stored in plaintext, upgrade to PBKDF2 on successful login."""
    if stored and not stored.startswith(PBKDF2_PREFIX + "$") and hmac.compare_digest(stored, password):
        try:
            conn.execute("UPDATE users SET password=? WHERE login=?", (hash_password(password), login))
            conn.commit()
        except Exception:
            pass


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


def cleanup_expired_sessions() -> None:
    now = _now_utc()
    with database_connection(DB_FILE) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))
        conn.commit()


def create_session(login: str) -> Tuple[str, str]:
    token = secrets.token_urlsafe(32)
    now = _now_utc()
    expires = now + dt.timedelta(seconds=SESSION_TTL_SEC)
    with database_connection(DB_FILE) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions(token, login, created_at, last_seen, expires_at) VALUES(?,?,?,?,?)",
            (token, login, _iso(now), _iso(now), _iso(expires)),
        )
        conn.commit()
    return token, _iso(expires)


def get_session_by_token(token: str) -> Optional[Dict[str, str]]:
    if not token:
        return None
    cleanup_expired_sessions()
    with database_connection(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT token, login, created_at, last_seen, expires_at FROM sessions WHERE token=?",
            (token,),
        ).fetchone()
        if not row:
            return None
        if not session_valid(conn, row["login"], token):
            return None
        return dict(row)


def touch_session(token: str) -> None:
    if not token:
        return

    now_dt = _now_utc()
    now_ts = now_dt.timestamp()

    # Throttle writes per token to reduce lock contention.
    with _session_touch_lock:
        prev = _session_touch_cache.get(token, 0.0)
        if (now_ts - prev) < SESSION_TOUCH_MIN_INTERVAL_SEC:
            return
        _session_touch_cache[token] = now_ts

    now_iso = _iso(now_dt)
    try:
        with database_connection(DB_FILE, timeout=10) as conn:
            conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (now_iso, token))
            conn.commit()
    except Exception:
        # Allow retry sooner if write failed
        with _session_touch_lock:
            _session_touch_cache.pop(token, None)

def delete_session(token: str) -> None:
    if not token:
        return
    try:
        with database_connection(DB_FILE, timeout=10) as conn:
            conn.execute("DELETE FROM voice_presence_versions WHERE token=?", (token,))
            conn.execute("DELETE FROM voice_tickets WHERE token=?", (token,))
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            conn.commit()
    except Exception:
        pass
    finally:
        with _session_touch_lock:
            _session_touch_cache.pop(token, None)


def set_session_offline(token: str) -> None:
    """Mark session as offline without deleting token.

    Useful on app close when we want fast presence convergence but still keep
    token for auto-login on next app start.
    """
    if not token:
        return
    # move last_seen outside online window
    old_seen = _iso(_now_utc() - dt.timedelta(seconds=ONLINE_WINDOW_SEC + 5))
    try:
        with database_connection(DB_FILE, timeout=10) as conn:
            conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (old_seen, token))
            conn.commit()
    except Exception:
        pass
    finally:
        # allow immediate future touch updates after app relaunch/login resume
        with _session_touch_lock:
            _session_touch_cache.pop(token, None)


def is_online(login: str) -> bool:
    if not login:
        return False
    cleanup_expired_sessions()
    window_start = _now_utc() - dt.timedelta(seconds=ONLINE_WINDOW_SEC)
    with database_connection(DB_FILE) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM sessions
            WHERE login=?
              AND expires_at >= ?
              AND last_seen >= ?
            LIMIT 1
            """,
            (login, _iso(_now_utc()), _iso(window_start)),
        ).fetchone()
        return bool(row)


def require_auth(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    token = data.get("token") or data.get("session_token") or ""
    if not token:
        return None, None, {"status": "error", "code": "session_required", "message": "Требуется авторизация"}
    sess = get_session_by_token(token)
    if not sess:
        return None, None, {"status": "error", "code": "session_invalid", "message": "Сессия недействительна. Войдите заново."}
    touch_session(token)
    return sess.get("login"), token, None


# -------------------- Events helpers --------------------

def push_event(login: str, event: Dict[str, Any]) -> None:
    if not login:
        return
    ev = dict(event)
    ev.setdefault("ts", _iso(_now_utc()))
    with database_connection(DB_FILE, timeout=10) as connection:
        event_store.append(connection, login, ev)
    _publish_legacy_event(login, ev)


def _publish_legacy_event(login, event):
    with events_lock:
        pending_events[login].append(event)


def pop_events(login: str) -> list:
    if not login:
        return []
    now = _now_utc()
    out = []
    with events_lock:
        q = pending_events.get(login)
        if not q:
            return []
        # prune by TTL
        keep = deque(maxlen=EVENT_MAX_PER_USER)
        for ev in q:
            try:
                ts = dt.datetime.fromisoformat(ev.get("ts", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=dt.timezone.utc)
                if (now - ts).total_seconds() <= EVENT_TTL_SEC:
                    out.append(ev)
            except Exception:
                out.append(ev)
        # clear queue (one-shot delivery)
        pending_events[login].clear()
    return out


# -------------------- User operations --------------------

def user_exists(login: str) -> bool:
    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE login=?", (login,))
        return cur.fetchone() is not None


def add_user(login: str, password: str, nickname: str, avatar: str) -> bool:
    if user_exists(login):
        return False
    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO users(login, password, nickname, avatar) VALUES (?,?,?,?)",
            (login, hash_password(password), nickname, avatar or ""),
        )
        conn.commit()
        return cur.rowcount == 1


def authenticate(login: str, password: str) -> bool:
    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT password FROM users WHERE login=?", (login,))
        row = cur.fetchone()
        if not row:
            return False
        stored = row[0]
        ok = verify_password(password, stored)
        if ok:
            maybe_upgrade_legacy_password(conn, login, stored, password)
        return ok


def get_user_info(login: str) -> Optional[Dict[str, str]]:
    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT login, nickname, avatar FROM users WHERE login=?", (login,))
        row = cur.fetchone()
        if not row:
            return None
        return {"login": row[0], "nickname": row[1], "avatar": row[2] or ""}


def update_user_profile(login: str, nickname: str, password: Optional[str], avatar: Optional[str], keep_token: str = "") -> bool:
    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        if password:
            cur.execute(
                "UPDATE users SET nickname=?, password=?, avatar=? WHERE login=?",
                (nickname, hash_password(password), avatar or "", login),
            )
            cur.execute("DELETE FROM voice_tickets WHERE login=? AND token<>?", (login, keep_token))
            cur.execute("DELETE FROM voice_presence_versions WHERE token IN (SELECT token FROM sessions WHERE login=? AND token<>?)", (login, keep_token))
            cur.execute("DELETE FROM sessions WHERE login=? AND token<>?", (login, keep_token))
        else:
            cur.execute(
                "UPDATE users SET nickname=?, avatar=? WHERE login=?",
                (nickname, avatar or "", login),
            )
        conn.commit()
    return True


# -------------------- Friends / Requests --------------------

def send_friend_request(from_user: str, to_user: str) -> bool:
    if from_user == to_user:
        return False
    if not user_exists(to_user):
        return False

    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        # already friends?
        cur.execute(
            "SELECT 1 FROM friends WHERE (user_login=? AND friend_login=?) OR (user_login=? AND friend_login=?)",
            (from_user, to_user, to_user, from_user),
        )
        if cur.fetchone():
            return False

        # pending already?
        cur.execute("SELECT 1 FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, to_user))
        if cur.fetchone():
            return False

        cur.execute("INSERT INTO friend_requests(from_user, to_user) VALUES(?,?)", (from_user, to_user))
        conn.commit()
        return True


def get_friend_requests(to_user: str) -> list:
    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT from_user FROM friend_requests WHERE to_user=?", (to_user,))
        return [r[0] for r in cur.fetchall()]


def accept_friend_request(from_user: str, to_user: str) -> bool:
    if (not from_user) or (not to_user) or (from_user == to_user):
        return False

    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, to_user))
        # Принять можно только существующую заявку.
        if cur.rowcount <= 0:
            conn.commit()
            return False

        cur.execute("INSERT OR IGNORE INTO friends(user_login, friend_login) VALUES(?,?)", (from_user, to_user))
        cur.execute("INSERT OR IGNORE INTO friends(user_login, friend_login) VALUES(?,?)", (to_user, from_user))
        conn.commit()
    return True


def decline_friend_request(from_user: str, to_user: str) -> bool:
    if (not from_user) or (not to_user) or (from_user == to_user):
        return False

    with database_connection(DB_FILE) as conn:
        cur = conn.execute("DELETE FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, to_user))
        conn.commit()
    return cur.rowcount > 0


def get_friends(login: str) -> list:
    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT friend_login FROM friends WHERE user_login=? AND friend_login<>?", (login, login))
        return [r[0] for r in cur.fetchall()]


def are_friends(user_a: str, user_b: str) -> bool:
    if not user_a or not user_b or user_a == user_b:
        return False
    with database_connection(DB_FILE, timeout=10) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM friends
            WHERE (user_login=? AND friend_login=?)
               OR (user_login=? AND friend_login=?)
            LIMIT 1
            """,
            (user_a, user_b, user_b, user_a),
        ).fetchone()
        return bool(row)


def remove_friend(current_user: str, friend_login: str) -> bool:
    """Remove friendship in both directions and clear pending requests between users."""
    if (not current_user) or (not friend_login) or (current_user == friend_login):
        return False

    with database_connection(DB_FILE) as conn:
        cur = conn.cursor()

        # remove accepted friendship in both directions
        cur.execute(
            "DELETE FROM friends WHERE (user_login=? AND friend_login=?) OR (user_login=? AND friend_login=?)",
            (current_user, friend_login, friend_login, current_user),
        )
        deleted_friends = cur.rowcount

        # also clear pending requests in both directions (if any)
        cur.execute(
            "DELETE FROM friend_requests WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)",
            (current_user, friend_login, friend_login, current_user),
        )
        deleted_requests = cur.rowcount

        conn.commit()

    return (deleted_friends > 0) or (deleted_requests > 0)


# -------------------- Chat (messages) --------------------

def save_message(from_user: str, to_user: str, text: str) -> bool:
    with database_connection(CHAT_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages(from_user, to_user, text, is_read) VALUES(?,?,?,0)",
            (from_user, to_user, text),
        )
        conn.commit()
    return True


def get_messages(user_a: str, user_b: str, limit: int = 50) -> list:
    lim = max(1, min(500, int(limit or 50)))
    with database_connection(CHAT_DB) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """SELECT id, from_user, to_user, text, timestamp AS created_at, is_read
               FROM messages
               WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
               ORDER BY timestamp DESC, id DESC
               LIMIT ?""",
            (user_a, user_b, user_b, user_a, lim),
        )
        # Клиенту по-прежнему отдаём в хронологическом порядке (старые -> новые).
        rows = cur.fetchall()
        return [dict(r) for r in reversed(rows)]


def mark_chat_read(current_user: str, friend: str) -> None:
    with database_connection(CHAT_DB) as conn:
        conn.execute(
            "UPDATE messages SET is_read=1 WHERE from_user=? AND to_user=? AND is_read=0",
            (friend, current_user),
        )
        conn.commit()


def get_unread_counts(current_user: str) -> Dict[str, int]:
    with database_connection(CHAT_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT from_user, COUNT(*)
               FROM messages
               WHERE to_user=? AND is_read=0
               GROUP BY from_user""",
            (current_user,),
        )
        return {row[0]: int(row[1]) for row in cur.fetchall()}


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
    try:
        validate_request(data)
    except ValueError as error:
        return {"status":"error", "code":"invalid_request", "message":str(error)}

    action = data.get("action")
    if not action:
        return {"status": "error", "message": "Нет действия"}

    # public actions
    if action == "register":
        login = (data.get("login") or "").strip()
        password = data.get("password") or ""
        nickname = (data.get("nickname") or "").strip()
        try:
            avatar = normalize_avatar(data.get("avatar") or "")
        except ValueError as error:
            return {"status": "error", "message": str(error)}
        if not login or not password or not nickname:
            return {"status": "error", "message": "Заполните все поля"}
        ok = add_user(login, password, nickname, avatar)
        return {"status": "ok"} if ok else {"status": "error", "message": "Логин уже существует"}

    if action == "login":
        login = (data.get("login") or "").strip()
        password = data.get("password") or ""
        if not authenticate(login, password):
            return {"status": "error", "message": "Неверный логин или пароль"}
        info = get_user_info(login) or {"login": login, "nickname": login, "avatar": ""}
        token, expires_at = create_session(login)
        return {
            "status": "ok",
            "login": info["login"],
            "nickname": info["nickname"],
            "avatar": info["avatar"],
            "token": token,
            "expires_at": expires_at,
        }

    if action == "resume_session":
        token = data.get("token") or ""
        sess = get_session_by_token(token)
        if not sess:
            return {"status": "error", "code": "session_invalid", "message": "Сессия недействительна"}
        touch_session(token)
        login = sess["login"]
        info = get_user_info(login) or {"login": login, "nickname": login, "avatar": ""}
        return {
            "status": "ok",
            "login": info["login"],
            "nickname": info["nickname"],
            "avatar": info["avatar"],
            "token": token,
            "expires_at": sess.get("expires_at", ""),
        }

    # Everything below requires auth
    current_user, token, err = require_auth(data)
    if err:
        return err

    if action == "voice_ticket":
        try:
            with database_connection(DB_FILE, timeout=5) as connection:
                connection.execute("BEGIN IMMEDIATE")
                ticket = voice_tickets.issue(connection, current_user, token,
                                             data.get("room"), data.get("peer"))
            return {"status": "ok", **ticket}
        except (ValueError, TypeError, OverflowError) as error:
            return {"status": "error", "message": str(error)}

    # Common touch already done

    if action == "find_user":
        target_login = (data.get("target_login") or data.get("login") or "").strip()
        if not target_login:
            return {"status": "error", "message": "Не указан логин пользователя"}
        info = get_user_info(target_login)
        if not info:
            return {"status": "error", "message": "Пользователь не найден"}
        info["online"] = is_online(target_login)
        return {"status": "ok", **info}

    if action == "heartbeat":
        mark_call_activity(current_user)
        return {"status": "ok"}

    if action == "logout":
        # End active call (if any)
        delete_session(token)
        with database_connection(DB_FILE) as connection:
            remaining = connection.execute('SELECT 1 FROM sessions WHERE login=? AND expires_at>? LIMIT 1',
                                           (current_user, _iso(_now_utc()))).fetchone()
        if not remaining:
            cleanup_calls_for_user(current_user)
        return {"status": "ok"}

    if action == "release_call_state":
        # Used by client on app close to avoid stale "busy" state,
        # but keeps session token valid for auto-login.
        if data.get("call_id"):
            _call_service().finish(current_user, expected_id=data["call_id"])
        return {"status": "ok"}

    if action == "presence_offline":
        # Fast presence convergence on app close while keeping session token.
        set_session_offline(token)
        return {"status": "ok"}

    if action == "status":
        # status for the current user only
        return {"status": "ok", "login": current_user, "online": is_online(current_user)}

    if action == "update_profile":
        nickname = (data.get("nickname") or "").strip()
        if not nickname:
            return {"status": "error", "message": "Никнейм не может быть пустым"}
        password = data.get("password") or None
        if password and not authenticate(current_user, data.get("current_password") or ""):
            return {"status":"error", "message":"Укажите верный текущий пароль"}
        try:
            avatar = normalize_avatar(data.get("avatar") or "")
        except ValueError as error:
            return {"status": "error", "message": str(error)}
        update_user_profile(current_user, nickname, password, avatar, keep_token=token)
        return {"status": "ok"}

    # Friends
    if action == "send_friend_request":
        to_user = (data.get("to_user") or "").strip()
        ok = send_friend_request(current_user, to_user)
        return {"status": "ok"} if ok else {"status": "error", "message": "Не удалось отправить запрос"}

    if action == "get_friend_requests":
        reqs = get_friend_requests(current_user)
        return {"status": "ok", "requests": reqs}

    if action == "accept_friend_request":
        from_user = (data.get("from_user") or "").strip()
        ok = accept_friend_request(from_user, current_user)
        return {"status": "ok"} if ok else {"status": "error", "message": "Заявка не найдена или уже обработана"}

    if action == "decline_friend_request":
        from_user = (data.get("from_user") or "").strip()
        ok = decline_friend_request(from_user, current_user)
        return {"status": "ok"} if ok else {"status": "error", "message": "Заявка не найдена или уже обработана"}

    if action == "get_friends":
        friends = get_friends(current_user)
        friends_info = []
        for f in friends:
            info = get_user_info(f) or {"login": f, "nickname": f, "avatar": ""}
            friends_info.append({
                "login": info["login"],
                "nickname": info["nickname"],
                "avatar": info.get("avatar") or "",
                "online": is_online(f),
            })
        return {"status": "ok", "friends": friends_info}

    if action == "remove_friend":
        friend_login = (data.get("friend_login") or "").strip()
        if not friend_login:
            return {"status": "error", "message": "Не указан пользователь"}
        ok = remove_friend(current_user, friend_login)
        return {"status": "ok"} if ok else {"status": "error", "message": "Друг не найден или уже удалён"}

    # Chat
    if action == "send_message":
        to_user = (data.get("to_user") or "").strip()
        text = (data.get("text") or data.get("message") or "").strip()
        if not to_user or not text:
            return {"status": "error", "message": "Пустое сообщение"}
        if not are_friends(current_user, to_user):
            return {"status":"error", "message":"Отправлять сообщения можно только друзьям"}
        save_message(current_user, to_user, text)
        return {"status": "ok"}

    if action == "get_messages":
        # Client usually sends from_user/to_user. We trust session login.
        other = (data.get("to_user") or "").strip()
        if not other or other == current_user:
            other = (data.get("from_user") or "").strip()
        if not other or other == current_user:
            return {"status": "error", "message": "Не указан собеседник"}
        msgs = get_messages(current_user, other, limit=int(data.get("limit", 50) or 50))
        return {"status": "ok", "messages": msgs}

    if action == "mark_chat_read":
        friend = (data.get("friend_login") or "").strip()
        if not friend:
            return {"status": "error", "message": "Не указан собеседник"}
        mark_chat_read(current_user, friend)
        return {"status": "ok"}

    if action == "get_unread_counts":
        counts = get_unread_counts(current_user)
        total = sum(counts.values())
        return {"status": "ok", "counts": counts, "total": total}

    # Channels
    if action == "create_channel":
        name = (data.get("name") or "").strip()
        try:
            avatar = normalize_avatar(data.get("avatar") or "")
        except ValueError as error:
            return {"status": "error", "message": str(error)}
        try:
            ch = create_channel(current_user, name=name, avatar=avatar)
            return {"status": "ok", "channel": ch}
        except ValueError as ve:
            return {"status": "error", "message": str(ve)}
        except Exception as e:
            return {"status": "error", "message": "Не удалось создать канал"}

    if action == "join_channel":
        code = (data.get("code") or "").strip()
        ok, msg, ch = join_channel_by_code(current_user, code)
        if ok:
            return {"status": "ok", "channel": ch}
        return {"status": "error", "message": msg}

    if action == "get_my_channels":
        channels = list_user_channels(current_user)
        return {"status": "ok", "channels": channels}

    if action == "send_channel_invite":
        channel_id = int(data.get("channel_id") or 0)
        to_user = (data.get("to_user") or "").strip()
        ok, msg = send_channel_invite(current_user, channel_id, to_user)
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "get_my_channel_invites":
        invites = get_incoming_channel_invites(current_user)
        return {"status": "ok", "invites": invites}

    if action == "respond_channel_invite":
        invite_id = int(data.get("invite_id") or 0)
        decision = (data.get("decision") or "").strip().lower()
        if decision not in {"accept", "decline"}:
            return {"status": "error", "message": "Некорректное решение"}
        ok, msg, ch = respond_channel_invite(current_user, invite_id, accept=(decision == "accept"))
        if not ok:
            return {"status": "error", "message": msg}
        return {"status": "ok", "channel": ch} if ch else {"status": "ok"}

    if action == "get_channel_messages":
        channel_id = int(data.get("channel_id") or 0)
        if channel_id <= 0:
            return {"status": "error", "message": "Не указан канал"}
        if not is_channel_member(channel_id, current_user):
            return {"status": "error", "message": "Нет доступа к каналу"}
        msgs = get_channel_messages(channel_id, limit=int(data.get("limit", 200) or 200))
        return {"status": "ok", "messages": msgs}

    if action == "send_channel_message":
        channel_id = int(data.get("channel_id") or 0)
        text_msg = (data.get("text") or data.get("message") or "").strip()
        if channel_id <= 0:
            return {"status": "error", "message": "Не указан канал"}
        if not text_msg:
            return {"status": "error", "message": "Пустое сообщение"}
        with database_connection(DB_FILE, timeout=10) as conn:
            if not is_channel_member(channel_id, current_user):
                return {"status": "error", "message": "Нет доступа к каналу"}
            if not _can_send_text(conn, channel_id, current_user):
                return {"status": "error", "message": "У вас нет прав писать в этот канал"}
        ok = save_channel_message(channel_id, current_user, text_msg)
        return {"status": "ok"} if ok else {"status": "error", "message": "Не удалось отправить сообщение"}

    if action == "get_channel_details":
        channel_id = int(data.get("channel_id") or 0)
        ok, msg, details = get_channel_details_for_user(channel_id, current_user)
        if not ok:
            return {"status": "error", "message": msg}
        return {"status": "ok", **(details or {})}

    if action == "update_channel_settings":
        channel_id = int(data.get("channel_id") or 0)
        name = (data.get("name") or "").strip()
        try:
            avatar = normalize_avatar(data.get("avatar") or "")
        except ValueError as error:
            return {"status": "error", "message": str(error)}
        text_min_role = (data.get("text_min_role") or "member").strip().lower()
        voice_min_role = (data.get("voice_min_role") or "member").strip().lower()
        ok, msg, channel = update_channel_settings(
            current_user,
            channel_id,
            name,
            avatar,
            text_min_role=text_min_role,
            voice_min_role=voice_min_role,
        )
        if not ok:
            return {"status": "error", "message": msg}
        return {"status": "ok", "channel": channel}

    if action == "regenerate_channel_code":
        channel_id = int(data.get("channel_id") or 0)
        ok, msg, channel = regenerate_channel_code(current_user, channel_id)
        if not ok:
            return {"status": "error", "message": msg}
        return {"status": "ok", "channel": channel}

    if action == "set_channel_member_role":
        channel_id = int(data.get("channel_id") or 0)
        target_login = (data.get("target_login") or "").strip()
        role = (data.get("role") or "").strip().lower()
        ok, msg = set_channel_member_role(current_user, channel_id, target_login, role)
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "remove_channel_member":
        channel_id = int(data.get("channel_id") or 0)
        target_login = (data.get("target_login") or "").strip()
        ok, msg = remove_channel_member(current_user, channel_id, target_login)
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "leave_channel":
        channel_id = int(data.get("channel_id") or 0)
        ok, msg = leave_channel(current_user, channel_id)
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "delete_channel":
        channel_id = int(data.get("channel_id") or 0)
        ok, msg = delete_channel(current_user, channel_id)
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "set_channel_voice_presence":
        channel_id = int(data.get("channel_id") or 0)
        speaking = bool(data.get("speaking", False))
        joined = bool(data.get("joined", True))
        ok, msg = set_channel_voice_presence(current_user, channel_id, speaking=speaking, joined=joined, token=token, sequence=data.get("sequence"))
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "leave_channel_voice":
        channel_id = int(data.get("channel_id") or 0)
        ok, msg = leave_channel_voice(current_user, channel_id, token=token, sequence=data.get("sequence"))
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "get_channel_voice_participants":
        channel_id = int(data.get("channel_id") or 0)
        ok, msg, participants = get_channel_voice_participants(channel_id, current_user)
        if not ok:
            return {"status": "error", "message": msg}
        return {"status": "ok", "participants": participants}

    # Calls
    if action == "call_user":
        to_user = (data.get("to_user") or "").strip()
        if not to_user:
            return {"status": "error", "message": "Не указан пользователь"}
        if to_user == current_user:
            return {"status": "error", "message": "Нельзя позвонить самому себе"}
        ok, msg = start_call(current_user, to_user)
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "poll_events":
        mark_call_activity(current_user)
        if "after_event_id" in data:
            with database_connection(DB_FILE, timeout=10) as connection:
                connection.execute("BEGIN")
                try:
                    events = event_store.read(connection, current_user, data["after_event_id"])
                except ValueError as error:
                    return {"status": "error", "message": str(error)}
                pair = connection.execute("""SELECT user_a,user_b,status,caller_login,created_at
                    FROM active_call_pairs WHERE user_a=? OR user_b=? LIMIT 1""",
                    (current_user,current_user)).fetchone()
            state = None if not pair else {
                "peer": pair[1] if pair[0] == current_user else pair[0],
                "status": pair[2], "incoming": pair[3] != current_user, "call_id": pair[4],
            }
            return {"status": "ok", "events": events, "call_state": state}
        events = pop_events(current_user)
        return {"status": "ok", "events": events}

    if action == "accept_call":
        from_user = (data.get("from_user") or "").strip()
        ok = accept_call(current_user, from_user)
        return {"status": "ok"} if ok else {"status": "error", "message": "Нет активного вызова"}

    if action == "decline_call":
        from_user = (data.get("from_user") or "").strip()
        ok = decline_call(current_user, from_user)
        return {"status": "ok"} if ok else {"status": "error", "message": "Нет активного вызова"}

    if action == "end_call":
        with_user = (data.get("with_user") or "").strip()
        ok = end_call(current_user, with_user)
        return {"status": "ok"} if ok else {"status": "error", "message": "Нет активного вызова"}

    return {"status": "error", "message": "Неизвестное действие"}


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
