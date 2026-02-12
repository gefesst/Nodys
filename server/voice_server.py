
import socket
import threading
import time

HOST = "127.0.0.1"
PORT = 5556

clients = {}  # login -> (ip, port, ts)
active_pairs = set()  # frozenset({a,b})
lock = threading.Lock()


def now():
    return time.time()


def cleanup_loop():
    while True:
        time.sleep(5)
        t = now()
        with lock:
            dead = [u for u, (_, _, ts) in clients.items() if t - ts > 15]
            for u in dead:
                clients.pop(u, None)


def other_user_in_pair(user):
    with lock:
        for pair in active_pairs:
            if user in pair:
                users = list(pair)
                return users[1] if users[0] == user else users[0]
    return None


def set_pair(a, b, active=True):
    p = frozenset((a, b))
    with lock:
        if active:
            active_pairs.add(p)
        else:
            active_pairs.discard(p)


def handle_packet(sock, data, addr):
    if len(data) < 3:
        return
    typ = data[:2]

    if typ == b"J|":
        login = data[2:].decode("utf-8", errors="ignore").strip()
        if login:
            with lock:
                clients[login] = (addr[0], addr[1], now())
        return

    if typ == b"S|":
        try:
            payload = data[2:].decode("utf-8")
            a, b, flag = payload.split("|")
            set_pair(a, b, flag == "1")
        except Exception:
            pass
        return


    if typ == b"P|":
        # ping-pong for latency estimate
        try:
            sock.sendto(b"Q|" + data[2:], addr)
        except Exception:
            pass
        return

    if typ == b"A|":
        try:
            sep = data.find(b"|", 2)
            if sep == -1:
                return
            from_user = data[2:sep].decode("utf-8", errors="ignore")
            pcm = data[sep + 1:]

            with lock:
                clients[from_user] = (addr[0], addr[1], now())

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
    print(f"[VOICE SERVER] UDP {HOST}:{PORT}")
    threading.Thread(target=cleanup_loop, daemon=True).start()
    while True:
        data, addr = sock.recvfrom(8192)
        handle_packet(sock, data, addr)


if __name__ == "__main__":
    main()
