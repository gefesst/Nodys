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
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional, Tuple

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
ONLINE_WINDOW_SEC = 120              # considered online if seen within this window
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

        # Helpful indexes
        # indexes (compatible with existing DB)
        c.execute("CREATE INDEX IF NOT EXISTS idx_friends_user ON friends(user_login)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_friends_friend ON friends(friend_login)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_fr_to ON friend_requests(to_user)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_login ON sessions(login)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen)")
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

        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_pair_time ON messages(from_user, to_user, timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_to_read ON messages(to_user, is_read)")
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
    with sqlite3.connect(CHAT_DB) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """SELECT id, from_user, to_user, text, timestamp AS created_at, is_read
               FROM messages
               WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
               ORDER BY timestamp ASC
               LIMIT ?""",
            (user_a, user_b, user_b, user_a, int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]


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


# -------------------- Calls --------------------

def start_call(from_user: str, to_user: str) -> Tuple[bool, str]:
    prune_stale_calls()

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

    if action == "find_user":
        login = (data.get("login") or "").strip()
        info = get_user_info(login)
        if not info:
            return {"status": "error", "message": "Пользователь не найден"}
        info["online"] = is_online(login)
        return {"status": "ok", **info}

    # Everything below requires auth
    current_user, token, err = require_auth(data)
    if err:
        return err

    # Common touch already done

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
