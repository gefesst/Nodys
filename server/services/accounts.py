"""AccountService: explicit dependencies, independent of socket dispatch."""
import datetime as dt
import sqlite3
from typing import Any, Dict, Optional, Tuple
try:
    from ..storage.database import connect as database_connection
except ImportError:
    from storage.database import connect as database_connection
import secrets
import threading
from collections import OrderedDict
try:
    from ..domain.authorization import session_valid
    from ..domain.passwords import hash_password, verify_password, maybe_upgrade_legacy_password
except ImportError:
    from domain.authorization import session_valid
    from domain.passwords import hash_password, verify_password, maybe_upgrade_legacy_password

class AccountService:
    def __init__(self, database, now, iso, ttl=2592000, online_seconds=45, touch_interval=3):
        self.database, self.now, self.iso = database, now, iso
        self.ttl, self.online_seconds, self.touch_interval = ttl, online_seconds, touch_interval
        self.touch_cache = OrderedDict()
        self.touch_lock = threading.Lock()

    def cleanup_expired_sessions(self) -> None:
        now = self.now()
        with database_connection(self.database) as conn:
            conn.execute("DELETE FROM voice_tickets WHERE expires<=? OR token IN (SELECT token FROM sessions WHERE expires_at<?)", (now.timestamp(), self.iso(now)))
            conn.execute("DELETE FROM voice_presence_versions WHERE token IN (SELECT token FROM sessions WHERE expires_at<?)", (self.iso(now),))
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (self.iso(now),))
            conn.commit()

    def create_session(self, login: str) -> Tuple[str, str]:
        token = secrets.token_urlsafe(32)
        now = self.now()
        expires = now + dt.timedelta(seconds=self.ttl)
        with database_connection(self.database) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions(token, login, created_at, last_seen, expires_at) VALUES(?,?,?,?,?)",
                (token, login, self.iso(now), self.iso(now), self.iso(expires)),
            )
            conn.commit()
        return token, self.iso(expires)

    def get_session_by_token(self, token: str) -> Optional[Dict[str, str]]:
        if not token:
            return None
        self.cleanup_expired_sessions()
        with database_connection(self.database) as conn:
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

    def touch_session(self, token: str) -> None:
        if not token:
            return

        now_dt = self.now()
        now_ts = now_dt.timestamp()

        # Throttle writes per token to reduce lock contention.
        with self.touch_lock:
            prev = self.touch_cache.get(token, 0.0)
            if (now_ts - prev) < self.touch_interval:
                return
            self.touch_cache[token] = now_ts
            self.touch_cache.move_to_end(token)
            while len(self.touch_cache) > 8192:
                self.touch_cache.popitem(last=False)

        now_iso = self.iso(now_dt)
        try:
            with database_connection(self.database, timeout=10) as conn:
                conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (now_iso, token))
                conn.commit()
        except Exception:
            # Allow retry sooner if write failed
            with self.touch_lock:
                self.touch_cache.pop(token, None)

    def delete_session(self, token: str) -> None:
        if not token:
            return
        try:
            with database_connection(self.database, timeout=10) as conn:
                conn.execute("DELETE FROM voice_presence_versions WHERE token=?", (token,))
                conn.execute("DELETE FROM voice_tickets WHERE token=?", (token,))
                conn.execute("DELETE FROM sessions WHERE token=?", (token,))
                conn.commit()
        finally:
            with self.touch_lock:
                self.touch_cache.pop(token, None)

    def set_session_offline(self, token: str) -> None:
        """Mark session as offline without deleting token.

        Useful on app close when we want fast presence convergence but still keep
        token for auto-login on next app start.
        """
        if not token:
            return
        # move last_seen outside online window
        old_seen = self.iso(self.now() - dt.timedelta(seconds=self.online_seconds + 5))
        try:
            with database_connection(self.database, timeout=10) as conn:
                conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (old_seen, token))
                conn.commit()
        finally:
            # allow immediate future touch updates after app relaunch/login resume
            with self.touch_lock:
                self.touch_cache.pop(token, None)

    def is_online(self, login: str) -> bool:
        if not login:
            return False
        self.cleanup_expired_sessions()
        window_start = self.now() - dt.timedelta(seconds=self.online_seconds)
        with database_connection(self.database) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM sessions
                WHERE login=?
                  AND expires_at >= ?
                  AND last_seen >= ?
                LIMIT 1
                """,
                (login, self.iso(self.now()), self.iso(window_start)),
            ).fetchone()
            return bool(row)

    def require_auth(self, data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        token = data.get("token") or data.get("session_token") or ""
        if not token:
            return None, None, {"status": "error", "code": "session_required", "message": "Требуется авторизация"}
        sess = self.get_session_by_token(token)
        if not sess:
            return None, None, {"status": "error", "code": "session_invalid", "message": "Сессия недействительна. Войдите заново."}
        self.touch_session(token)
        return sess.get("login"), token, None

    def user_exists(self, login: str) -> bool:
        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM users WHERE login=?", (login,))
            return cur.fetchone() is not None

    def add_user(self, login: str, password: str, nickname: str, avatar: str) -> bool:
        if self.user_exists(login):
            return False
        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO users(login, password, nickname, avatar) VALUES (?,?,?,?)",
                (login, hash_password(password), nickname, avatar or ""),
            )
            conn.commit()
            return cur.rowcount == 1

    def authenticate(self, login: str, password: str) -> bool:
        with database_connection(self.database) as conn:
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

    def get_user_info(self, login: str) -> Optional[Dict[str, str]]:
        with database_connection(self.database) as conn:
            cur = conn.cursor()
            cur.execute("SELECT login, nickname, avatar FROM users WHERE login=?", (login,))
            row = cur.fetchone()
            if not row:
                return None
            return {"login": row[0], "nickname": row[1], "avatar": row[2] or ""}

    def update_user_profile(self, login: str, nickname: str, password: Optional[str], avatar: Optional[str], keep_token: str = "") -> bool:
        with database_connection(self.database) as conn:
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
