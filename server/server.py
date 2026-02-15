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


DB_FILE = resolve_db_path("users.db")
CHAT_DB = resolve_db_path("voice_chat.db")

# -------------------- Presence / Sessions --------------------
SESSION_TTL_SEC = 60 * 60 * 24 * 30  # 30 days
ONLINE_WINDOW_SEC = 45               # considered online if seen within this window
SESSION_TOUCH_MIN_INTERVAL_SEC = 3     # reduce DB write contention on frequent polling

# -------------------- Events / Calls --------------------
EVENT_MAX_PER_USER = 200
EVENT_TTL_SEC = 180
CALL_STALE_SEC = 25  # if one side stops sending heartbeats/polls, auto-release call

active_calls: Dict[str, str] = {}  # user -> peer
call_activity: Dict[str, float] = {}  # user -> monotonic ts of last call-related activity
call_lock = threading.Lock()

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
    return hmac.compare_digest(password, stored)


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


def recv_request(conn: socket.socket, max_bytes: int = 10_000_000) -> Optional[Dict[str, Any]]:
    """Receive one JSON request.

    Supports new length-prefixed frames and legacy raw JSON.
    """
    header = _recv_exact(conn, 4)
    if not header:
        return None

    # Legacy: JSON starts with '{' or '['
    if header[:1] in (b"{", b"["):
        data = header
        conn.settimeout(0.4)
        while len(data) < max_bytes:
            try:
                chunk = conn.recv(65536)
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
    payload = _recv_exact(conn, length)
    if not payload:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return None


def send_response(conn: socket.socket, obj: Dict[str, Any]) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    conn.sendall(struct.pack("!I", len(payload)) + payload)


# -------------------- DB init --------------------

def init_db() -> None:
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        c = conn.cursor()
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                login TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                nickname TEXT NOT NULL,
                avatar TEXT
            )"""
        )
        # Keep backward‑compatible column names (project already uses user_login/friend_login)
        c.execute(
            """CREATE TABLE IF NOT EXISTS friends (
                user_login TEXT,
                friend_login TEXT,
                PRIMARY KEY (user_login, friend_login)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS friend_requests (
                from_user TEXT,
                to_user TEXT,
                PRIMARY KEY (from_user, to_user)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                login TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )"""
        )

        c.execute(
            """CREATE TABLE IF NOT EXISTS active_call_pairs (
                user_a TEXT NOT NULL,
                user_b TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ringing',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_a, user_b)
            )"""
        )

        c.execute(
            """CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                avatar TEXT DEFAULT '',
                owner_login TEXT NOT NULL,
                text_min_role TEXT NOT NULL DEFAULT 'member',
                voice_min_role TEXT NOT NULL DEFAULT 'member',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS channel_members (
                channel_id INTEGER NOT NULL,
                login TEXT NOT NULL,
                joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                role TEXT NOT NULL DEFAULT 'member',
                PRIMARY KEY (channel_id, login)
            )"""
        )
        # migration for older DBs
        try:
            cm_cols = [r[1] for r in c.execute("PRAGMA table_info(channel_members)").fetchall()]
            if "role" not in cm_cols:
                c.execute("ALTER TABLE channel_members ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
        except Exception:
            pass

        # migration for channels access policy
        try:
            ch_cols = [r[1] for r in c.execute("PRAGMA table_info(channels)").fetchall()]
            if "text_min_role" not in ch_cols:
                c.execute("ALTER TABLE channels ADD COLUMN text_min_role TEXT NOT NULL DEFAULT 'member'")
            if "voice_min_role" not in ch_cols:
                c.execute("ALTER TABLE channels ADD COLUMN voice_min_role TEXT NOT NULL DEFAULT 'member'")
        except Exception:
            pass

        c.execute(
            """CREATE TABLE IF NOT EXISTS channel_voice_presence (
                channel_id INTEGER NOT NULL,
                login TEXT NOT NULL,
                speaking INTEGER NOT NULL DEFAULT 0,
                last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (channel_id, login)
            )"""
        )

        c.execute(
            """CREATE TABLE IF NOT EXISTS channel_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                from_user TEXT NOT NULL,
                to_user TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        # Helpful indexes
        # indexes (compatible with existing DB)
        c.execute("CREATE INDEX IF NOT EXISTS idx_friends_user ON friends(user_login)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_friends_friend ON friends(friend_login)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_fr_to ON friend_requests(to_user)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_login ON sessions(login)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels(owner_login)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_channel_members_login ON channel_members(login)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_channel_members_channel ON channel_members(channel_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ch_voice_presence_channel ON channel_voice_presence(channel_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ch_voice_presence_seen ON channel_voice_presence(last_seen)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ch_inv_to_status ON channel_invites(to_user, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ch_inv_channel_status ON channel_invites(channel_id, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_active_call_pairs_updated ON active_call_pairs(updated_at)")

        # На старте процесса очищаем transient-таблицу активных звонков
        # (в памяти active_calls всё равно пустой после рестарта).
        try:
            c.execute("DELETE FROM active_call_pairs")
        except Exception:
            pass

        conn.commit()


def init_chat_db() -> None:
    os.makedirs(os.path.dirname(CHAT_DB), exist_ok=True)
    with sqlite3.connect(CHAT_DB, timeout=10) as conn:
        c = conn.cursor()
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        c.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user TEXT NOT NULL,
                to_user TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_read INTEGER DEFAULT 0
            )"""
        )
        # Ensure column exists in older DBs
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(messages)").fetchall()]
            if "is_read" not in cols:
                c.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0")
        except Exception:
            pass

        c.execute(
            """CREATE TABLE IF NOT EXISTS channel_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                from_user TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_pair_time ON messages(from_user, to_user, timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_to_read ON messages(to_user, is_read)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ch_msg_channel_time ON channel_messages(channel_id, timestamp)")
        conn.commit()


# -------------------- Sessions / Presence helpers --------------------

def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime) -> str:
    return ts.isoformat()


def cleanup_expired_sessions() -> None:
    now = _now_utc()
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))
        conn.commit()


def create_session(login: str) -> Tuple[str, str]:
    token = secrets.token_urlsafe(32)
    now = _now_utc()
    expires = now + dt.timedelta(seconds=SESSION_TTL_SEC)
    with sqlite3.connect(DB_FILE) as conn:
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
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT token, login, created_at, last_seen, expires_at FROM sessions WHERE token=?",
            (token,),
        ).fetchone()
        if not row:
            return None
        # check expiry
        try:
            expires = dt.datetime.fromisoformat(row["expires_at"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=dt.timezone.utc)
            if expires < _now_utc():
                return None
        except Exception:
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
        with sqlite3.connect(DB_FILE, timeout=10) as conn:
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
        with sqlite3.connect(DB_FILE, timeout=10) as conn:
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
        with sqlite3.connect(DB_FILE, timeout=10) as conn:
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
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM sessions
            WHERE login=?
              AND expires_at >= ?
              AND (last_seen >= ? OR created_at >= ?)
            LIMIT 1
            """,
            (login, _iso(_now_utc()), _iso(window_start), _iso(window_start)),
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
    with events_lock:
        pending_events[login].append(ev)


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
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE login=?", (login,))
        return cur.fetchone() is not None


def add_user(login: str, password: str, nickname: str, avatar: str) -> bool:
    if user_exists(login):
        return False
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users(login, password, nickname, avatar) VALUES (?,?,?,?)",
            (login, hash_password(password), nickname, avatar or ""),
        )
        conn.commit()
    return True


def authenticate(login: str, password: str) -> bool:
    with sqlite3.connect(DB_FILE) as conn:
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
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT login, nickname, avatar FROM users WHERE login=?", (login,))
        row = cur.fetchone()
        if not row:
            return None
        return {"login": row[0], "nickname": row[1], "avatar": row[2] or ""}


def update_user_profile(login: str, nickname: str, password: Optional[str], avatar: Optional[str]) -> bool:
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        if password:
            cur.execute(
                "UPDATE users SET nickname=?, password=?, avatar=? WHERE login=?",
                (nickname, hash_password(password), avatar or "", login),
            )
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

    with sqlite3.connect(DB_FILE) as conn:
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
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT from_user FROM friend_requests WHERE to_user=?", (to_user,))
        return [r[0] for r in cur.fetchall()]


def accept_friend_request(from_user: str, to_user: str) -> bool:
    if (not from_user) or (not to_user) or (from_user == to_user):
        return False

    with sqlite3.connect(DB_FILE) as conn:
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

    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute("DELETE FROM friend_requests WHERE from_user=? AND to_user=?", (from_user, to_user))
        conn.commit()
    return cur.rowcount > 0


def get_friends(login: str) -> list:
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT friend_login FROM friends WHERE user_login=? AND friend_login<>?", (login, login))
        return [r[0] for r in cur.fetchall()]


def are_friends(user_a: str, user_b: str) -> bool:
    if not user_a or not user_b or user_a == user_b:
        return False
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
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

    with sqlite3.connect(DB_FILE) as conn:
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
    with sqlite3.connect(CHAT_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages(from_user, to_user, text, is_read) VALUES(?,?,?,0)",
            (from_user, to_user, text),
        )
        conn.commit()
    return True


def get_messages(user_a: str, user_b: str, limit: int = 50) -> list:
    lim = max(1, min(500, int(limit or 50)))
    with sqlite3.connect(CHAT_DB) as conn:
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
    with sqlite3.connect(CHAT_DB) as conn:
        conn.execute(
            "UPDATE messages SET is_read=1 WHERE from_user=? AND to_user=? AND is_read=0",
            (friend, current_user),
        )
        conn.commit()


def get_unread_counts(current_user: str) -> Dict[str, int]:
    with sqlite3.connect(CHAT_DB) as conn:
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

def _generate_channel_code(conn: sqlite3.Connection, length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = ''.join(random.choice(alphabet) for _ in range(length))
        row = conn.execute("SELECT 1 FROM channels WHERE code=?", (code,)).fetchone()
        if not row:
            return code
    # ultra-rare fallback
    return ''.join(random.choice(alphabet) for _ in range(length + 2))


def create_channel(owner_login: str, name: str, avatar: str = "") -> Dict[str, Any]:
    channel_name = (name or "").strip()
    if not channel_name:
        raise ValueError("Название канала не может быть пустым")

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        code = _generate_channel_code(conn)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO channels(code, name, avatar, owner_login, text_min_role, voice_min_role, created_at) VALUES(?,?,?,?,?,?,?)",
            (code, channel_name[:64], avatar or "", owner_login, "member", "member", _iso(_now_utc())),
        )
        channel_id = int(cur.lastrowid)
        cur.execute(
            "INSERT OR IGNORE INTO channel_members(channel_id, login, joined_at, role) VALUES(?,?,?,?)",
            (channel_id, owner_login, _iso(_now_utc()), "admin"),
        )
        conn.commit()

        row = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
            (channel_id,),
        ).fetchone()
        return dict(row) if row else {
            "id": channel_id,
            "code": code,
            "name": channel_name[:64],
            "avatar": avatar or "",
            "owner_login": owner_login,
        }


def list_user_channels(login: str) -> list:
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        _cleanup_channel_voice_presence(conn)
        rows = conn.execute(
            """
            SELECT c.id, c.code, c.name, c.avatar, c.owner_login, c.text_min_role, c.voice_min_role, c.created_at,
                   CASE
                       WHEN c.owner_login = m.login THEN 'owner'
                       ELSE COALESCE(NULLIF(m.role,''), 'member')
                   END AS my_role,
                   (SELECT COUNT(*) FROM channel_members cm WHERE cm.channel_id = c.id) AS participants_count,
                   (SELECT COUNT(*) FROM channel_voice_presence vp WHERE vp.channel_id = c.id) AS voice_online_count
            FROM channels c
            JOIN channel_members m ON m.channel_id = c.id
            WHERE m.login=?
            ORDER BY LOWER(c.name) ASC, c.id ASC
            """,
            (login,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_channel_by_id(channel_id: int) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
            (int(channel_id),),
        ).fetchone()
        return dict(row) if row else None


def is_channel_member(channel_id: int, login: str) -> bool:
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        row = conn.execute(
            "SELECT 1 FROM channel_members WHERE channel_id=? AND login=? LIMIT 1",
            (int(channel_id), login),
        ).fetchone()
        return bool(row)


def join_channel_by_code(login: str, code: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    code_norm = (code or "").strip().upper()
    if not code_norm:
        return False, "Укажите код канала", None

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE UPPER(code)=?",
            (code_norm,),
        ).fetchone()
        if not row:
            return False, "Канал не найден", None

        channel_id = int(row["id"])
        conn.execute(
            "INSERT OR IGNORE INTO channel_members(channel_id, login, joined_at, role) VALUES(?,?,?,?)",
            (channel_id, login, _iso(_now_utc()), "member"),
        )
        conn.commit()
        return True, "ok", dict(row)


def send_channel_invite(actor_login: str, channel_id: int, target_login: str) -> Tuple[bool, str]:
    cid = int(channel_id or 0)
    to_login = (target_login or "").strip()
    if cid <= 0 or not to_login:
        return False, "Некорректные данные"
    if actor_login == to_login:
        return False, "Нельзя пригласить самого себя"

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row

        target_user = conn.execute("SELECT 1 FROM users WHERE login=?", (to_login,)).fetchone()
        if not target_user:
            return False, "Пользователь не найден"

        ch, my_role = _get_channel_and_my_role(conn, cid, actor_login)
        if not ch or not my_role:
            return False, "Нет доступа к каналу"

        perms = _role_permissions(my_role, ch.get("text_min_role", "member"), ch.get("voice_min_role", "member"))
        if not bool(perms.get("can_invite", False)):
            return False, "Недостаточно прав"

        already_member = conn.execute(
            "SELECT 1 FROM channel_members WHERE channel_id=? AND login=?",
            (cid, to_login),
        ).fetchone()
        if already_member:
            return False, "Пользователь уже состоит в канале"

        existing = conn.execute(
            "SELECT id FROM channel_invites WHERE channel_id=? AND to_user=? AND status='pending' LIMIT 1",
            (cid, to_login),
        ).fetchone()
        if existing:
            return False, "У этого пользователя уже есть активное приглашение"

        now = _iso(_now_utc())
        conn.execute(
            """
            INSERT INTO channel_invites(channel_id, from_user, to_user, status, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            """,
            (cid, actor_login, to_login, "pending", now, now),
        )
        conn.commit()
    return True, "ok"


def get_incoming_channel_invites(login: str) -> List[Dict[str, Any]]:
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT i.id AS invite_id,
                   i.channel_id,
                   i.from_user,
                   i.to_user,
                   i.created_at,
                   c.name AS channel_name,
                   c.avatar AS channel_avatar,
                   c.code AS channel_code,
                   COALESCE(u.nickname, i.from_user) AS from_nickname,
                   COALESCE(u.avatar, '') AS from_avatar
            FROM channel_invites i
            JOIN channels c ON c.id = i.channel_id
            LEFT JOIN users u ON u.login = i.from_user
            WHERE i.to_user=? AND i.status='pending'
            ORDER BY i.id DESC
            """,
            (login,),
        ).fetchall()
        return [dict(r) for r in rows]


def respond_channel_invite(login: str, invite_id: int, accept: bool) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    iid = int(invite_id or 0)
    if iid <= 0:
        return False, "Некорректное приглашение", None

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        inv = conn.execute(
            "SELECT id, channel_id, to_user, status FROM channel_invites WHERE id=?",
            (iid,),
        ).fetchone()
        if not inv:
            return False, "Приглашение не найдено", None

        if inv["to_user"] != login:
            return False, "Это приглашение адресовано другому пользователю", None

        if (inv["status"] or "").lower() != "pending":
            return False, "Приглашение уже обработано", None

        cid = int(inv["channel_id"])
        ch = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
            (cid,),
        ).fetchone()
        if not ch:
            now = _iso(_now_utc())
            conn.execute(
                "UPDATE channel_invites SET status='declined', updated_at=? WHERE id=?",
                (now, iid),
            )
            conn.commit()
            return False, "Канал уже не существует", None

        now = _iso(_now_utc())
        if accept:
            conn.execute(
                "INSERT OR IGNORE INTO channel_members(channel_id, login, joined_at, role) VALUES(?,?,?,?)",
                (cid, login, now, "member"),
            )
            conn.execute(
                "UPDATE channel_invites SET status='accepted', updated_at=? WHERE channel_id=? AND to_user=? AND status='pending'",
                (now, cid, login),
            )
            conn.commit()
            return True, "ok", dict(ch)

        conn.execute(
            "UPDATE channel_invites SET status='declined', updated_at=? WHERE id=?",
            (now, iid),
        )
        conn.commit()
        return True, "ok", None


def get_channel_messages(channel_id: int, limit: int = 200) -> list:
    lim = max(1, min(500, int(limit or 200)))
    with sqlite3.connect(CHAT_DB, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, channel_id, from_user, text, timestamp AS created_at
            FROM channel_messages
            WHERE channel_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(channel_id), lim),
        ).fetchall()
        # Возвращаем в хронологическом порядке для UI.
        return [dict(r) for r in reversed(rows)]


def save_channel_message(channel_id: int, from_user: str, text: str) -> bool:
    msg = (text or "").strip()
    if not msg:
        return False
    with sqlite3.connect(CHAT_DB, timeout=10) as conn:
        conn.execute(
            "INSERT INTO channel_messages(channel_id, from_user, text) VALUES(?,?,?)",
            (int(channel_id), from_user, msg),
        )
        conn.commit()
    return True


_VALID_CHANNEL_ROLES = {"member", "moderator", "admin"}
_VALID_MIN_ACCESS_ROLES = {"member", "moderator", "admin"}
_ROLE_RANK = {"member": 1, "moderator": 2, "admin": 3, "owner": 4}
VOICE_PRESENCE_TTL_SEC = 8


def _normalize_member_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r not in _VALID_CHANNEL_ROLES:
        return "member"
    return r


def _normalize_min_access_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r not in _VALID_MIN_ACCESS_ROLES:
        return "member"
    return r


def _has_min_role(user_role: str, min_role: str) -> bool:
    ur = (user_role or "member").strip().lower()
    mr = _normalize_min_access_role(min_role)
    return _ROLE_RANK.get(ur, 0) >= _ROLE_RANK.get(mr, 1)


def _channel_member_role(conn: sqlite3.Connection, channel_id: int, login: str) -> Optional[str]:
    row = conn.execute(
        "SELECT c.owner_login, m.role FROM channels c LEFT JOIN channel_members m ON m.channel_id=c.id AND m.login=? WHERE c.id=?",
        (login, int(channel_id)),
    ).fetchone()
    if not row:
        return None
    owner = row[0]
    if owner == login:
        return "owner"
    role = row[1] if len(row) > 1 else "member"
    return _normalize_member_role(role)


def _role_permissions(role: str, text_min_role: str = "member", voice_min_role: str = "member") -> Dict[str, bool]:
    rr = (role or "member").strip().lower()
    text_req = _normalize_min_access_role(text_min_role)
    voice_req = _normalize_min_access_role(voice_min_role)

    can_send_text = _has_min_role(rr, text_req)
    can_join_voice = _has_min_role(rr, voice_req)

    if rr == "owner":
        return {
            "can_send_text": True,
            "can_join_voice": True,
            "can_invite": True,
            "manage_members": True,
            "manage_channel": True,
            "assign_roles": True,
            "delete_channel": True,
            "text_min_role": text_req,
            "voice_min_role": voice_req,
            "my_role": rr,
        }
    if rr == "admin":
        return {
            "can_send_text": can_send_text,
            "can_join_voice": can_join_voice,
            "can_invite": True,
            "manage_members": True,
            "manage_channel": False,
            "assign_roles": True,
            "delete_channel": False,
            "text_min_role": text_req,
            "voice_min_role": voice_req,
            "my_role": rr,
        }
    if rr == "moderator":
        return {
            "can_send_text": can_send_text,
            "can_join_voice": can_join_voice,
            "can_invite": True,
            "manage_members": True,
            "manage_channel": False,
            "assign_roles": False,
            "delete_channel": False,
            "text_min_role": text_req,
            "voice_min_role": voice_req,
            "my_role": rr,
        }
    return {
        "can_send_text": can_send_text,
        "can_join_voice": can_join_voice,
        "can_invite": True,
        "manage_members": False,
        "manage_channel": False,
        "assign_roles": False,
        "delete_channel": False,
        "text_min_role": text_req,
        "voice_min_role": voice_req,
        "my_role": rr,
    }



def _channel_online_map(conn: sqlite3.Connection) -> Dict[str, bool]:
    now = _now_utc()
    threshold = now - dt.timedelta(seconds=ONLINE_WINDOW_SEC)
    rows = conn.execute(
        "SELECT DISTINCT login FROM sessions WHERE last_seen >= ? AND expires_at > ?",
        (_iso(threshold), _iso(now)),
    ).fetchall()
    out = {}
    for r in rows:
        try:
            out[r[0]] = True
        except Exception:
            pass
    return out


def _channel_members_details(conn: sqlite3.Connection, channel_id: int, owner_login: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT m.login, COALESCE(NULLIF(m.role,''), 'member') AS role,
               COALESCE(u.nickname, m.login) AS nickname, COALESCE(u.avatar, '') AS avatar
        FROM channel_members m
        LEFT JOIN users u ON u.login = m.login
        WHERE m.channel_id = ?
        ORDER BY CASE WHEN m.login = ? THEN 0 ELSE 1 END, LOWER(COALESCE(u.nickname, m.login)) ASC, LOWER(m.login) ASC
        """,
        (int(channel_id), owner_login),
    ).fetchall()

    online_map = _channel_online_map(conn)
    members = []
    for r in rows:
        login = r[0]
        role = "owner" if login == owner_login else _normalize_member_role(r[1])
        members.append({
            "login": login,
            "nickname": r[2] or login,
            "avatar": r[3] or "",
            "role": role,
            "online": bool(online_map.get(login)),
        })
    return members



def _get_channel_and_my_role(conn: sqlite3.Connection, channel_id: int, login: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
        (int(channel_id),),
    ).fetchone()
    if not row:
        return None, None
    ch = dict(row)
    member = conn.execute(
        "SELECT role FROM channel_members WHERE channel_id=? AND login=?",
        (int(channel_id), login),
    ).fetchone()
    if not member:
        return ch, None
    my_role = "owner" if ch.get("owner_login") == login else _normalize_member_role(member[0] if member else "member")
    return ch, my_role


def _can_send_text(conn: sqlite3.Connection, channel_id: int, login: str) -> bool:
    ch, my_role = _get_channel_and_my_role(conn, channel_id, login)
    if not ch or not my_role:
        return False
    need = ch.get("text_min_role", "member")
    return _has_min_role(my_role, need)


def _can_join_voice(conn: sqlite3.Connection, channel_id: int, login: str) -> bool:
    ch, my_role = _get_channel_and_my_role(conn, channel_id, login)
    if not ch or not my_role:
        return False
    need = ch.get("voice_min_role", "member")
    return _has_min_role(my_role, need)


def _cleanup_channel_voice_presence(conn: sqlite3.Connection, channel_id: Optional[int] = None) -> None:
    threshold = _iso(_now_utc() - dt.timedelta(seconds=VOICE_PRESENCE_TTL_SEC))
    if channel_id is None:
        conn.execute("DELETE FROM channel_voice_presence WHERE last_seen < ?", (threshold,))
    else:
        conn.execute(
            "DELETE FROM channel_voice_presence WHERE channel_id=? AND last_seen < ?",
            (int(channel_id), threshold),
        )


def set_channel_voice_presence(login: str, channel_id: int, speaking: bool = False, joined: bool = True) -> Tuple[bool, str]:
    cid = int(channel_id or 0)
    if cid <= 0:
        return False, "Не указан канал"

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        if not is_channel_member(cid, login):
            return False, "Нет доступа к каналу"
        if joined and not _can_join_voice(conn, cid, login):
            return False, "У вас нет прав для входа в голосовой канал"

        _cleanup_channel_voice_presence(conn, cid)
        if not joined:
            conn.execute(
                "DELETE FROM channel_voice_presence WHERE channel_id=? AND login=?",
                (cid, login),
            )
            conn.commit()
            return True, "ok"

        conn.execute(
            """
            INSERT INTO channel_voice_presence(channel_id, login, speaking, last_seen)
            VALUES(?,?,?,?)
            ON CONFLICT(channel_id, login) DO UPDATE SET
                speaking=excluded.speaking,
                last_seen=excluded.last_seen
            """,
            (cid, login, 1 if bool(speaking) else 0, _iso(_now_utc())),
        )
        conn.commit()
    return True, "ok"


def leave_channel_voice(login: str, channel_id: int) -> Tuple[bool, str]:
    cid = int(channel_id or 0)
    if cid <= 0:
        return False, "Не указан канал"
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.execute(
            "DELETE FROM channel_voice_presence WHERE channel_id=? AND login=?",
            (cid, login),
        )
        conn.commit()
    return True, "ok"


def get_channel_voice_participants(channel_id: int, login: str) -> Tuple[bool, str, List[Dict[str, Any]]]:
    cid = int(channel_id or 0)
    if cid <= 0:
        return False, "Не указан канал", []

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        if not is_channel_member(cid, login):
            return False, "Нет доступа к каналу", []
        # visibility is available to all channel members
        _cleanup_channel_voice_presence(conn, cid)

        ch = conn.execute(
            "SELECT owner_login FROM channels WHERE id=?",
            (cid,),
        ).fetchone()
        if not ch:
            return False, "Канал не найден", []

        owner_login = ch["owner_login"]
        rows = conn.execute(
            """
            SELECT p.login,
                   p.speaking,
                   p.last_seen,
                   COALESCE(u.nickname, p.login) AS nickname,
                   COALESCE(u.avatar, '') AS avatar,
                   COALESCE(NULLIF(m.role,''), 'member') AS role
            FROM channel_voice_presence p
            LEFT JOIN users u ON u.login = p.login
            LEFT JOIN channel_members m ON m.channel_id = p.channel_id AND m.login = p.login
            WHERE p.channel_id=?
            ORDER BY p.speaking DESC, LOWER(COALESCE(u.nickname, p.login)) ASC, LOWER(p.login) ASC
            """,
            (cid,),
        ).fetchall()

        online_map = _channel_online_map(conn)

        out: List[Dict[str, Any]] = []
        for r in rows:
            lg = r["login"]
            role = "owner" if lg == owner_login else _normalize_member_role(r["role"])
            out.append({
                "login": lg,
                "nickname": r["nickname"] or lg,
                "avatar": r["avatar"] or "",
                "role": role,
                "speaking": bool(int(r["speaking"] or 0)),
                "online": bool(online_map.get(lg)),
            })

        return True, "ok", out


def get_channel_details_for_user(channel_id: int, login: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    cid = int(channel_id or 0)
    if cid <= 0:
        return False, "Не указан канал", None

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
            (cid,),
        ).fetchone()
        if not row:
            return False, "Канал не найден", None

        member = conn.execute(
            "SELECT role FROM channel_members WHERE channel_id=? AND login=?",
            (cid, login),
        ).fetchone()
        if not member:
            return False, "Нет доступа к каналу", None

        ch = dict(row)
        my_role = "owner" if ch.get("owner_login") == login else _normalize_member_role(member[0] if member else "member")
        perms = _role_permissions(my_role, ch.get("text_min_role", "member"), ch.get("voice_min_role", "member"))
        members = _channel_members_details(conn, cid, ch.get("owner_login") or "")

        result = {
            "channel": ch,
            "my_role": my_role,
            "permissions": perms,
            "members": members,
        }
        return True, "ok", result


def update_channel_settings(actor_login: str, channel_id: int, name: str, avatar: str, text_min_role: str = "member", voice_min_role: str = "member") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    cid = int(channel_id or 0)
    if cid <= 0:
        return False, "Не указан канал", None

    new_name = (name or "").strip()
    if not new_name:
        return False, "Введите название канала", None

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        ch = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
            (cid,),
        ).fetchone()
        if not ch:
            return False, "Канал не найден", None

        if ch["owner_login"] != actor_login:
            return False, "Недостаточно прав", None

        text_policy = _normalize_min_access_role(text_min_role)
        voice_policy = _normalize_min_access_role(voice_min_role)
        conn.execute(
            "UPDATE channels SET name=?, avatar=?, text_min_role=?, voice_min_role=? WHERE id=?",
            (new_name[:64], avatar or "", text_policy, voice_policy, cid),
        )
        conn.commit()

        out = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
            (cid,),
        ).fetchone()
        return True, "ok", dict(out) if out else None


def regenerate_channel_code(actor_login: str, channel_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    cid = int(channel_id or 0)
    if cid <= 0:
        return False, "Не указан канал", None

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        ch = conn.execute(
            "SELECT id, owner_login FROM channels WHERE id=?",
            (cid,),
        ).fetchone()
        if not ch:
            return False, "Канал не найден", None
        if ch["owner_login"] != actor_login:
            return False, "Недостаточно прав", None

        code = _generate_channel_code(conn)
        conn.execute("UPDATE channels SET code=? WHERE id=?", (code, cid))
        conn.commit()

        out = conn.execute(
            "SELECT id, code, name, avatar, owner_login, text_min_role, voice_min_role, created_at FROM channels WHERE id=?",
            (cid,),
        ).fetchone()
        return True, "ok", dict(out) if out else None


def set_channel_member_role(actor_login: str, channel_id: int, target_login: str, role: str) -> Tuple[bool, str]:
    cid = int(channel_id or 0)
    tgt = (target_login or "").strip()
    new_role = _normalize_member_role(role)

    if cid <= 0 or not tgt:
        return False, "Некорректные данные"

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        ch = conn.execute("SELECT owner_login FROM channels WHERE id=?", (cid,)).fetchone()
        if not ch:
            return False, "Канал не найден"

        owner = ch["owner_login"]
        actor_role = _channel_member_role(conn, cid, actor_login)
        if actor_role not in {"owner", "admin"}:
            return False, "Недостаточно прав"

        tgt_member = conn.execute(
            "SELECT login, COALESCE(NULLIF(role,''), 'member') FROM channel_members WHERE channel_id=? AND login=?",
            (cid, tgt),
        ).fetchone()
        if not tgt_member:
            return False, "Участник не найден"

        if tgt == owner:
            return False, "Нельзя изменить роль владельца"

        if new_role == "owner":
            return False, "Нельзя назначить владельца через эту операцию"

        tgt_role = "owner" if tgt == owner else _normalize_member_role(tgt_member[1])
        if actor_role == "admin":
            if tgt_role in {"owner", "admin"}:
                return False, "Админ не может изменить роль этого участника"
            if new_role == "admin":
                return False, "Админ не может назначать администраторов"

        conn.execute(
            "UPDATE channel_members SET role=? WHERE channel_id=? AND login=?",
            (new_role, cid, tgt),
        )
        conn.commit()
        return True, "ok"


def remove_channel_member(actor_login: str, channel_id: int, target_login: str) -> Tuple[bool, str]:
    cid = int(channel_id or 0)
    tgt = (target_login or "").strip()
    if cid <= 0 or not tgt:
        return False, "Некорректные данные"

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        ch = conn.execute("SELECT owner_login FROM channels WHERE id=?", (cid,)).fetchone()
        if not ch:
            return False, "Канал не найден"

        owner = ch["owner_login"]
        actor_role = _channel_member_role(conn, cid, actor_login)
        if actor_role not in {"owner", "admin", "moderator"}:
            return False, "Недостаточно прав"

        tgt_member = conn.execute(
            "SELECT login, COALESCE(NULLIF(role,''), 'member') FROM channel_members WHERE channel_id=? AND login=?",
            (cid, tgt),
        ).fetchone()
        if not tgt_member:
            return False, "Участник не найден"

        if tgt == owner:
            return False, "Нельзя удалить владельца"

        tgt_role = _normalize_member_role(tgt_member[1])
        if actor_role == "admin" and tgt_role == "admin":
            return False, "Админ не может удалить другого админа"
        if actor_role == "moderator" and tgt_role != "member":
            return False, "Модератор может удалять только обычных участников"

        conn.execute("DELETE FROM channel_members WHERE channel_id=? AND login=?", (cid, tgt))
        conn.execute("DELETE FROM channel_voice_presence WHERE channel_id=? AND login=?", (cid, tgt))
        conn.execute(
            "DELETE FROM channel_invites WHERE channel_id=? AND (from_user=? OR to_user=?)",
            (cid, tgt, tgt),
        )
        conn.commit()
        return True, "ok"


def leave_channel(login: str, channel_id: int) -> Tuple[bool, str]:
    cid = int(channel_id or 0)
    if cid <= 0:
        return False, "Не указан канал"

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        ch = conn.execute("SELECT owner_login FROM channels WHERE id=?", (cid,)).fetchone()
        if not ch:
            return False, "Канал не найден"

        if ch["owner_login"] == login:
            return False, "Владелец не может выйти из канала. Передайте владельца или удалите канал"

        row = conn.execute("SELECT 1 FROM channel_members WHERE channel_id=? AND login=?", (cid, login)).fetchone()
        if not row:
            return False, "Вы не участник канала"

        conn.execute("DELETE FROM channel_members WHERE channel_id=? AND login=?", (cid, login))
        conn.execute("DELETE FROM channel_voice_presence WHERE channel_id=? AND login=?", (cid, login))
        conn.execute(
            "DELETE FROM channel_invites WHERE channel_id=? AND (from_user=? OR to_user=?)",
            (cid, login, login),
        )
        conn.commit()
        return True, "ok"


def delete_channel(actor_login: str, channel_id: int) -> Tuple[bool, str]:
    cid = int(channel_id or 0)
    if cid <= 0:
        return False, "Не указан канал"

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        ch = conn.execute("SELECT owner_login FROM channels WHERE id=?", (cid,)).fetchone()
        if not ch:
            return False, "Канал не найден"

        if ch["owner_login"] != actor_login:
            return False, "Только владелец может удалить канал"

        conn.execute("DELETE FROM channel_members WHERE channel_id=?", (cid,))
        conn.execute("DELETE FROM channel_voice_presence WHERE channel_id=?", (cid,))
        conn.execute("DELETE FROM channel_invites WHERE channel_id=?", (cid,))
        conn.execute("DELETE FROM channels WHERE id=?", (cid,))
        conn.commit()

    # delete channel chat history in separate DB
    try:
        with sqlite3.connect(CHAT_DB, timeout=10) as chat_conn:
            chat_conn.execute("DELETE FROM channel_messages WHERE channel_id=?", (cid,))
            chat_conn.commit()
    except Exception:
        pass

    return True, "ok"


# -------------------- Calls --------------------

def _canon_call_pair(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _db_set_call_pair(a: str, b: str, status: str) -> None:
    ua, ub = _canon_call_pair(a, b)
    now_iso = _iso(_now_utc())
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.execute(
            """
            INSERT INTO active_call_pairs(user_a, user_b, status, created_at, updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(user_a, user_b) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at
            """,
            (ua, ub, status, now_iso, now_iso),
        )
        conn.commit()


def _db_remove_call_pair(a: str, b: str) -> None:
    ua, ub = _canon_call_pair(a, b)
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.execute(
            "DELETE FROM active_call_pairs WHERE user_a=? AND user_b=?",
            (ua, ub),
        )
        conn.commit()


def start_call(from_user: str, to_user: str) -> Tuple[bool, str]:
    prune_stale_calls()

    if not user_exists(to_user):
        return False, "Пользователь не найден"

    if not are_friends(from_user, to_user):
        return False, "Можно звонить только друзьям"

    if not is_online(to_user):
        return False, "Пользователь не в сети"

    with call_lock:
        if from_user in active_calls or to_user in active_calls:
            return False, "Пользователь занят"
        active_calls[from_user] = to_user
        active_calls[to_user] = from_user
        ts = time.time()
        call_activity[from_user] = ts
        call_activity[to_user] = ts

    try:
        _db_set_call_pair(from_user, to_user, "ringing")
    except Exception:
        pass

    push_event(to_user, {"type": "incoming_call", "from_user": from_user})
    return True, "ok"


def mark_call_activity(user: str) -> None:
    if not user:
        return
    with call_lock:
        if user in active_calls:
            call_activity[user] = time.time()


def prune_stale_calls() -> None:
    """Drop calls where any participant is silent for too long.

    Helps release 'busy' state when the app is force-closed and no explicit
    end_call/logout request reaches the server.
    """
    now_ts = time.time()
    stale_pairs = []

    with call_lock:
        seen = set()
        for a, b in list(active_calls.items()):
            if (a, b) in seen or (b, a) in seen:
                continue
            seen.add((a, b))
            ta = float(call_activity.get(a, 0.0) or 0.0)
            tb = float(call_activity.get(b, 0.0) or 0.0)
            # If either side stopped heartbeats/polls for CALL_STALE_SEC, release pair.
            if (now_ts - ta) > CALL_STALE_SEC or (now_ts - tb) > CALL_STALE_SEC:
                stale_pairs.append((a, b))

        for a, b in stale_pairs:
            active_calls.pop(a, None)
            active_calls.pop(b, None)
            call_activity.pop(a, None)
            call_activity.pop(b, None)

    for a, b in stale_pairs:
        try:
            _db_remove_call_pair(a, b)
        except Exception:
            pass
        # notify both sides (best effort)
        push_event(a, {"type": "call_ended", "with_user": b, "by_user": "system"})
        push_event(b, {"type": "call_ended", "with_user": a, "by_user": "system"})


def accept_call(current_user: str, from_user: str) -> bool:
    prune_stale_calls()

    with call_lock:
        peer = active_calls.get(current_user)
        if peer != from_user:
            return False
        ts = time.time()
        call_activity[current_user] = ts
        call_activity[from_user] = ts

    try:
        _db_set_call_pair(current_user, from_user, "active")
    except Exception:
        pass

    # Звонящий получает подтверждение.
    push_event(from_user, {
        "type": "call_accepted",
        "by_user": current_user,
        "with_user": current_user,
    })

    # Принявший звонок тоже должен получить событие старта,
    # иначе окно разговора/аудио у него не запускаются.
    push_event(current_user, {
        "type": "call_started",
        "with_user": from_user,
    })
    return True


def decline_call(current_user: str, from_user: str) -> bool:
    prune_stale_calls()

    with call_lock:
        peer = active_calls.get(current_user)
        if peer != from_user:
            return False
        # clear mapping
        active_calls.pop(current_user, None)
        active_calls.pop(from_user, None)
        call_activity.pop(current_user, None)
        call_activity.pop(from_user, None)
    try:
        _db_remove_call_pair(current_user, from_user)
    except Exception:
        pass
    push_event(from_user, {"type": "call_declined", "by_user": current_user})
    return True


def end_call(current_user: str, with_user: str) -> bool:
    prune_stale_calls()

    with call_lock:
        if active_calls.get(current_user) != with_user:
            return False
        active_calls.pop(current_user, None)
        active_calls.pop(with_user, None)
        call_activity.pop(current_user, None)
        call_activity.pop(with_user, None)
    try:
        _db_remove_call_pair(current_user, with_user)
    except Exception:
        pass
    push_event(with_user, {"type": "call_ended", "with_user": current_user, "by_user": current_user})
    return True


def cleanup_calls_for_user(user: str) -> None:
    with call_lock:
        peer = active_calls.get(user)
        if peer:
            active_calls.pop(user, None)
            active_calls.pop(peer, None)
            call_activity.pop(user, None)
            call_activity.pop(peer, None)
            try:
                _db_remove_call_pair(user, peer)
            except Exception:
                pass
            push_event(peer, {"type": "call_ended", "with_user": user, "by_user": user})


# -------------------- Request dispatcher --------------------

def handle_request(data: Dict[str, Any]) -> Dict[str, Any]:
    prune_stale_calls()

    action = data.get("action")
    if not action:
        return {"status": "error", "message": "Нет действия"}

    # public actions
    if action == "register":
        login = (data.get("login") or "").strip()
        password = data.get("password") or ""
        nickname = (data.get("nickname") or "").strip()
        avatar = data.get("avatar") or ""
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
        cleanup_calls_for_user(current_user)
        delete_session(token)
        return {"status": "ok"}

    if action == "release_call_state":
        # Used by client on app close to avoid stale "busy" state,
        # but keeps session token valid for auto-login.
        cleanup_calls_for_user(current_user)
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
        password = (data.get("password") or "").strip() or None
        avatar = data.get("avatar") or ""
        update_user_profile(current_user, nickname, password, avatar)
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
        avatar = data.get("avatar") or ""
        try:
            ch = create_channel(current_user, name=name, avatar=avatar)
            return {"status": "ok", "channel": ch}
        except ValueError as ve:
            return {"status": "error", "message": str(ve)}
        except Exception as e:
            return {"status": "error", "message": f"Не удалось создать канал: {e}"}

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
        with sqlite3.connect(DB_FILE, timeout=10) as conn:
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
        avatar = data.get("avatar") or ""
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
        ok, msg = set_channel_voice_presence(current_user, channel_id, speaking=speaking, joined=joined)
        return {"status": "ok"} if ok else {"status": "error", "message": msg}

    if action == "leave_channel_voice":
        channel_id = int(data.get("channel_id") or 0)
        ok, msg = leave_channel_voice(current_user, channel_id)
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

def handle_client(conn: socket.socket, addr):
    try:
        data = recv_request(conn)
        if not data:
            send_response(conn, {"status": "error", "message": "Пустой запрос"})
            return
        resp = handle_request(data)
        send_response(conn, resp)
    except Exception as e:
        try:
            send_response(conn, {"status": "error", "message": f"Ошибка сервера: {e}"})
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_server(host: str = "0.0.0.0", port: int = 5555):
    init_db()
    init_chat_db()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(20)
    print(f"[SERVER] TCP listening on {host}:{port}")

    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    start_server()
