import socket
import threading
import sqlite3
import time
import os
from collections import deque
from typing import Dict, Tuple, Optional

# Shared DB with TCP server for token validation / channel ACL
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")

HOST = "0.0.0.0"
PORT = 5556

# Security mode:
#   0 (default): strictly require token for join/control.
#   1: allow legacy insecure join without token (for debugging only).
ALLOW_INSECURE_JOIN = os.environ.get("VOICECHAT_ALLOW_INSECURE", "0") == "1"

# login -> (ip, port, last_seen)
clients: Dict[str, Tuple[str, int, float]] = {}
# (ip,port) -> login
addr_to_login: Dict[Tuple[str, int], str] = {}
# frozenset({a,b}) -> True
pairs: Dict[frozenset, bool] = {}

# channel voice rooms
# room_id(str) -> set(logins)
room_members: Dict[str, set] = {}
# login -> room_id(str)
login_room: Dict[str, str] = {}

lock = threading.Lock()

_ROLE_RANK = {"member": 1, "moderator": 2, "admin": 3, "owner": 4}
_CONTROL_RATE_WINDOW_SEC = 1.0
_CONTROL_RATE_LIMIT = {b"J|": 30, b"C|": 30, b"L|": 30, b"S|": 40}
_rate_lock = threading.Lock()
_rate_log: Dict[Tuple[str, int, bytes], deque] = {}

_has_active_pair_table_cache: Optional[bool] = None
_has_active_pair_table_ts: float = 0.0


# -------------------- Helpers --------------------

def validate_token(login: str, token: str) -> bool:
    if not login or not token:
        return False
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute(
            "SELECT expires_at FROM sessions WHERE token=? AND login=?",
            (token, login),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return False

        expires_at = row[0]
        try:
            import datetime as dt
            exp = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=dt.timezone.utc)
            return exp.timestamp() > time.time()
        except Exception:
            # If timestamp format changed, trust existing DB session row as valid.
            return True
    except Exception:
        return False


def _norm_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r not in {"member", "moderator", "admin", "owner"}:
        return "member"
    return r


def _control_rate_limited(addr: Tuple[str, int], typ: bytes) -> bool:
    limit = _CONTROL_RATE_LIMIT.get(typ)
    if not limit:
        return False

    key = (addr[0], int(addr[1]), typ)
    now_ts = time.time()
    with _rate_lock:
        q = _rate_log.get(key)
        if q is None:
            q = deque()
            _rate_log[key] = q
        while q and (now_ts - q[0]) > _CONTROL_RATE_WINDOW_SEC:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now_ts)

        # occasional cleanup
        if len(_rate_log) > 5000:
            for k in list(_rate_log.keys())[:1500]:
                qq = _rate_log.get(k)
                if not qq or (now_ts - qq[-1]) > 3.0:
                    _rate_log.pop(k, None)
    return False


def _is_friends(user_a: str, user_b: str) -> bool:
    if not user_a or not user_b or user_a == user_b:
        return False
    try:
        conn = sqlite3.connect(DB_FILE, timeout=5)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM friends
            WHERE (user_login=? AND friend_login=?)
               OR (user_login=? AND friend_login=?)
            LIMIT 1
            """,
            (user_a, user_b, user_b, user_a),
        )
        row = cur.fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def _active_pair_table_exists() -> bool:
    global _has_active_pair_table_cache, _has_active_pair_table_ts
    now_ts = time.time()
    if _has_active_pair_table_cache is not None and (now_ts - _has_active_pair_table_ts) < 5.0:
        return bool(_has_active_pair_table_cache)

    try:
        conn = sqlite3.connect(DB_FILE, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='active_call_pairs'")
        row = cur.fetchone()
        conn.close()
        _has_active_pair_table_cache = bool(row)
    except Exception:
        _has_active_pair_table_cache = False

    _has_active_pair_table_ts = now_ts
    return bool(_has_active_pair_table_cache)


def _is_active_call_pair(user_a: str, user_b: str) -> bool:
    # Compatibility fallback for older DB schema.
    if not _active_pair_table_exists():
        return True

    ua, ub = (user_a, user_b) if user_a <= user_b else (user_b, user_a)
    try:
        conn = sqlite3.connect(DB_FILE, timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM active_call_pairs WHERE user_a=? AND user_b=? LIMIT 1",
            (ua, ub),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return False
        return str(row[0]).strip().lower() == "active"
    except Exception:
        return False


def _can_join_channel_voice(login: str, room_id: str) -> bool:
    # room_id can arrive either as plain numeric id ("12")
    # or namespaced format from client ("channel:12").
    raw = (room_id or "").strip()
    if not raw:
        return False

    cid: Optional[int] = None
    if raw.isdigit():
        cid = int(raw)
    else:
        low = raw.lower()
        if low.startswith("channel:"):
            tail = low.split(":", 1)[1].strip()
            if tail.isdigit():
                cid = int(tail)

    if cid is None or cid <= 0:
        return False

    try:
        conn = sqlite3.connect(DB_FILE, timeout=5)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.owner_login,
                   c.voice_min_role,
                   m.role
            FROM channels c
            LEFT JOIN channel_members m ON m.channel_id=c.id AND m.login=?
            WHERE c.id=?
            LIMIT 1
            """,
            (login, cid),
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            return False

        owner_login, min_role, member_role = row[0], row[1], row[2]
        need = _norm_role(min_role or "member")

        if owner_login == login:
            have = "owner"
        else:
            if member_role is None:
                return False
            have = _norm_role(member_role)

        return _ROLE_RANK.get(have, 0) >= _ROLE_RANK.get(need, 1)
    except Exception:
        return False


def _mark_seen(login: str, addr):
    now_ts = time.time()
    with lock:
        clients[login] = (addr[0], addr[1], now_ts)
        addr_to_login[(addr[0], addr[1])] = login


def _join_room(login: str, room_id: str):
    old = login_room.get(login)
    if old and old in room_members:
        room_members[old].discard(login)
        if not room_members[old]:
            room_members.pop(old, None)

    room_members.setdefault(room_id, set()).add(login)
    login_room[login] = room_id


def _remove_from_room(login: str):
    old = login_room.pop(login, None)
    if old and old in room_members:
        room_members[old].discard(login)
        if not room_members[old]:
            room_members.pop(old, None)


def set_pair(a: str, b: str, active: bool):
    key = frozenset((a, b))
    with lock:
        if active:
            pairs[key] = True
        else:
            pairs.pop(key, None)


def other_user_in_pair(me: str) -> Optional[str]:
    with lock:
        for key in pairs.keys():
            if me in key:
                for u in key:
                    if u != me:
                        return u
    return None


# -------------------- Cleanup --------------------

def cleanup_loop(timeout_sec: int = 20):
    while True:
        now_ts = time.time()
        dead = []
        with lock:
            for login, (_, _, last_seen) in list(clients.items()):
                if now_ts - last_seen > timeout_sec:
                    dead.append(login)

            for login in dead:
                clients.pop(login, None)
                # remove reverse addr mapping
                for k, v in list(addr_to_login.items()):
                    if v == login:
                        addr_to_login.pop(k, None)
                # remove from channel room if present
                _remove_from_room(login)
                # remove any pairs containing this login
                for key in list(pairs.keys()):
                    if login in key:
                        pairs.pop(key, None)

        time.sleep(2)


# -------------------- Packet handling --------------------

def handle_packet(sock: socket.socket, data: bytes, addr):
    if len(data) < 3:
        return
    typ = data[:2]

    if _control_rate_limited(addr, typ):
        return

    if typ == b"J|":
        payload = data[2:].decode("utf-8", errors="ignore").strip()
        if not payload:
            return

        parts = payload.split("|", 1)
        login = parts[0].strip()
        token = parts[1].strip() if len(parts) > 1 else ""

        if token:
            if not validate_token(login, token):
                return
        else:
            if not ALLOW_INSECURE_JOIN:
                return

        _mark_seen(login, addr)
        return

    if typ == b"C|":
        # Join channel voice room: C|login|token|room_id
        payload = data[2:].decode("utf-8", errors="ignore").strip()
        parts = payload.split("|", 3)
        if len(parts) < 3:
            return

        login = parts[0].strip()
        token = parts[1].strip()
        room_id = parts[2].strip()
        if not login or not room_id:
            return

        if token:
            if not validate_token(login, token):
                return
        else:
            if not ALLOW_INSECURE_JOIN:
                return

        if not _can_join_channel_voice(login, room_id):
            return

        _mark_seen(login, addr)
        with lock:
            _join_room(login, room_id)
        return

    if typ == b"L|":
        # Leave channel room: L|login|room_id
        payload = data[2:].decode("utf-8", errors="ignore").strip()
        parts = payload.split("|", 2)
        if len(parts) < 1:
            return

        login = parts[0].strip()
        if not login:
            return

        sender = addr_to_login.get((addr[0], addr[1]))
        if sender != login:
            return

        with lock:
            _remove_from_room(login)
        return

    if typ == b"S|":
        # Pairing commands:
        #   secure format: S|sender_login|token|a|b|flag
        #   legacy format: S|a|b|flag
        try:
            payload = data[2:].decode("utf-8", errors="ignore").strip()
            parts = payload.split("|")

            sender_mapped = addr_to_login.get((addr[0], addr[1]))
            if not sender_mapped:
                return

            sender_login = ""
            token = ""
            a = b = flag = ""

            if len(parts) >= 5:
                sender_login, token, a, b, flag = parts[0], parts[1], parts[2], parts[3], parts[4]
                sender_login = sender_login.strip()
                token = token.strip()
            elif len(parts) >= 3:
                a, b, flag = parts[0], parts[1], parts[2]
                sender_login = sender_mapped
            else:
                return

            a = (a or "").strip()
            b = (b or "").strip()
            flag = (flag or "").strip()

            if sender_login and sender_login != sender_mapped:
                return

            sender = sender_mapped
            if sender not in (a, b):
                return

            if token:
                if not validate_token(sender, token):
                    return
            else:
                if not ALLOW_INSECURE_JOIN:
                    return

            if flag == "1":
                # Private pair can be established only for friends and active calls.
                if not _is_friends(a, b):
                    return
                if not _is_active_call_pair(a, b):
                    return

            set_pair(a, b, flag == "1")
        except Exception:
            pass
        return

    if typ == b"P|":
        # Ping -> pong
        try:
            sock.sendto(b"Q|" + data[2:], addr)
        except Exception:
            pass
        return

    if typ == b"A|":
        # Audio frame: A|from_user|<pcm>
        try:
            sep = data.find(b"|", 2)
            if sep == -1:
                return

            from_user = data[2:sep].decode("utf-8", errors="ignore").strip()
            pcm = data[sep + 1 :]

            sender = addr_to_login.get((addr[0], addr[1]))
            if sender != from_user:
                return

            _mark_seen(from_user, addr)

            # 1) channel room broadcast
            with lock:
                room_id = login_room.get(from_user)
                if room_id:
                    recips = [u for u in room_members.get(room_id, set()) if u != from_user]
                    targets = [clients.get(u) for u in recips]
                else:
                    targets = None

            if targets is not None:
                for tgt in targets:
                    if not tgt:
                        continue
                    ip, port, _ = tgt
                    try:
                        sock.sendto(b"R|" + from_user.encode("utf-8") + b"|" + pcm, (ip, port))
                    except Exception:
                        pass
                return

            # 2) private pair
            to_user = other_user_in_pair(from_user)
            if not to_user:
                return

            with lock:
                target = clients.get(to_user)
            if not target:
                return

            ip, port, _ = target
            sock.sendto(b"R|" + from_user.encode("utf-8") + b"|" + pcm, (ip, port))
        except Exception:
            pass


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    print(f"[VOICE] UDP listening on {HOST}:{PORT}")
    if ALLOW_INSECURE_JOIN:
        print("[VOICE] WARNING: insecure join mode enabled (VOICECHAT_ALLOW_INSECURE=1)")

    threading.Thread(target=cleanup_loop, daemon=True).start()

    while True:
        try:
            data, addr = sock.recvfrom(8192)
            handle_packet(sock, data, addr)
        except Exception:
            pass


if __name__ == "__main__":
    main()
