import os
import socket
import struct
import sqlite3
import threading
import time
from typing import Dict, Tuple, Optional

# Bind address
HOST = os.environ.get("VOICECHAT_VOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("VOICECHAT_VOICE_PORT", "5556"))

# If 0 -> require token on join. If 1 -> allow legacy join without token.
ALLOW_INSECURE_JOIN = os.environ.get("VOICECHAT_ALLOW_INSECURE", "1") == "1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def resolve_db_path(filename: str) -> str:
    cwd_path = os.path.abspath(filename)
    base_path = os.path.join(BASE_DIR, filename)
    if os.path.exists(cwd_path) and not os.path.exists(base_path):
        return cwd_path
    return base_path

DB_FILE = resolve_db_path("users.db")

clients: Dict[str, Tuple[str, int, float]] = {}  # login -> (ip, port, ts)
addr_to_login: Dict[Tuple[str, int], str] = {}   # (ip,port) -> login
active_pairs = set()  # frozenset({a,b})
lock = threading.Lock()


def now() -> float:
    return time.time()


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
        # expires_at is ISO string
        try:
            # allow timezone suffix
            import datetime as dt
            exp = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=dt.timezone.utc)
            return exp.timestamp() > time.time()
        except Exception:
            return True
    except Exception:
        return False


def cleanup_loop():
    while True:
        time.sleep(5)
        t = now()
        with lock:
            dead = [u for u, (_, _, ts) in clients.items() if t - ts > 20]
            for u in dead:
                clients.pop(u, None)
            # clean addr map
            for addr, u in list(addr_to_login.items()):
                if u not in clients:
                    addr_to_login.pop(addr, None)


def other_user_in_pair(user: str) -> Optional[str]:
    with lock:
        for pair in active_pairs:
            if user in pair:
                users = list(pair)
                return users[1] if users[0] == user else users[0]
    return None


def set_pair(a: str, b: str, active: bool = True):
    p = frozenset((a, b))
    with lock:
        if active:
            active_pairs.add(p)
        else:
            active_pairs.discard(p)


def _mark_seen(login: str, addr):
    with lock:
        clients[login] = (addr[0], addr[1], now())
        addr_to_login[(addr[0], addr[1])] = login


def handle_packet(sock: socket.socket, data: bytes, addr):
    if len(data) < 3:
        return
    typ = data[:2]

    if typ == b"J|":
        payload = data[2:].decode("utf-8", errors="ignore").strip()
        if not payload:
            return
        parts = payload.split("|")
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

    if typ == b"S|":
        # Pairing: accept only if sender is one of the pair participants
        try:
            payload = data[2:].decode("utf-8", errors="ignore")
            a, b, flag = payload.split("|", 2)
            sender = addr_to_login.get((addr[0], addr[1]))
            if sender not in (a, b):
                return
            set_pair(a, b, flag == "1")
        except Exception:
            pass
        return

    if typ == b"P|":
        # ping-pong
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
                # ignore spoofed frames
                return

            _mark_seen(from_user, addr)

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

    # Windows: suppress WSAECONNRESET (WinError 10054) on UDP recvfrom.
    # This error can happen when sending UDP to a recently closed endpoint.
    try:
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            sock.ioctl(socket.SIO_UDP_CONNRESET, struct.pack("I", 0))
    except Exception:
        pass

    sock.bind((HOST, PORT))
    sock.settimeout(1.0)
    print(f"[VOICE SERVER] UDP {HOST}:{PORT} (insecure_join={'ON' if ALLOW_INSECURE_JOIN else 'OFF'})")
    threading.Thread(target=cleanup_loop, daemon=True).start()
    while True:
        try:
            data, addr = sock.recvfrom(8192)
        except socket.timeout:
            continue
        except ConnectionResetError:
            # Typical on Windows when peer port is closed; server must keep running.
            continue
        except OSError as e:
            # Also ignore Windows-specific UDP reset numeric code defensively.
            if getattr(e, "winerror", None) == 10054:
                continue
            raise

        try:
            handle_packet(sock, data, addr)
        except Exception:
            # Ignore malformed packets to keep voice server alive.
            continue


if __name__ == "__main__":
    main()
