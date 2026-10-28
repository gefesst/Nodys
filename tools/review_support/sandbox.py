"""Disposable real Nodys TCP/TLS + UDP server. Never opens the user's databases."""

import json, os, socket, subprocess, sys, tempfile, time, secrets
from pathlib import Path


class Sandbox:
    def __init__(self, project):
        self.project = Path(project)
        self.folder = tempfile.TemporaryDirectory(prefix="nodus-ui-lab-")
        self.path = Path(self.folder.name)
        self.children = []
        self.logs = []
        os.environ["NODYS_CONFIG_DIR"] = str(self.path / "config")
        (self.path / "config").mkdir()
        sys.path.insert(0, str(self.project))
        sys.path.insert(0, str(self.project / "client"))
        sys.path.insert(0, str(self.project / "tools"))
        from server import server
        from local_certificate import create_certificate

        server.DB_FILE = str(self.path / "users.db")
        server.CHAT_DB = str(self.path / "chat.db")
        server.init_db()
        server.init_chat_db()
        self.tokens = {}
        self.people = [
            ("proto_alexey", "Алексей Морозов"),
            ("proto_anna", "Анна Смирнова"),
            ("proto_maria", "Мария Ким"),
        ]
        self.me = "proto_andrey"
        for login, name in [(self.me, "Андрей")] + self.people:
            assert server.add_user(login, secrets.token_urlsafe(20), name, "")
            self.tokens[login] = server.create_session(login)[0]
            if login != self.me:
                server.send_friend_request(self.me, login)
                server.accept_friend_request(self.me, login)
        texts = [
            "Привет! Собрал всё в одном месте.\nПосмотри, когда будет минутка.",
            "Сегодня проверим каналы и звонки?",
            "Да, давай. Я уже посмотрел переписку —\nтеперь всё гораздо удобнее.",
            "Отлично. Начнём с нашего канала,\nа потом созвонимся.",
            "Договорились. Буду через десять минут.",
        ]
        for peer, _ in self.people:
            for i, t in enumerate(texts):
                server.save_message(
                    self.me if i in (2, 4) else peer,
                    peer if i in (2, 4) else self.me,
                    t,
                )
        self.channel = server.create_channel(self.me, "Локальный аудиотест")
        server.join_channel_by_code(self.people[0][0], self.channel["code"])
        self.port = self.free_port()
        self.voice_port = self.free_port(socket.SOCK_DGRAM)
        cert = self.path / "cert.pem"
        key = self.path / "key.pem"
        create_certificate(cert, key)
        self.config = dict(
            api_host="localhost",
            api_port=self.port,
            voice_host="127.0.0.1",
            voice_port=self.voice_port,
            api_tls=True,
            api_ca_file=str(cert),
        )
        configfile = self.path / "config/config.json"
        configfile.write_text(json.dumps(self.config))
        configfile.chmod(0o600)
        env = dict(
            os.environ,
            NODYS_DB_FILE=server.DB_FILE,
            NODYS_CHAT_DB=server.CHAT_DB,
            NODYS_HOST="127.0.0.1",
            NODYS_PORT=str(self.port),
            NODYS_VOICE_HOST="127.0.0.1",
            NODYS_VOICE_PORT=str(self.voice_port),
            NODYS_TLS_CERT=str(cert),
            NODYS_TLS_KEY=str(key),
            PYTHONUNBUFFERED="1",
        )
        for file in ("server.py", "voice_server.py"):
            log = open(self.path / (file + ".log"), "w")
            self.logs.append(log)
            self.children.append(
                subprocess.Popen(
                    [sys.executable, str(self.project / "server" / file)],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if any(p.poll() is not None for p in self.children):
                raise RuntimeError("Local test server could not start")
            try:
                r = self.request(self.me, "get_friends")
                if r.get("status") == "ok":
                    break
            except (OSError, ValueError):
                time.sleep(0.05)
        else:
            raise TimeoutError("Local server startup timed out")

    @staticmethod
    def free_port(kind=socket.SOCK_STREAM):
        with socket.socket(socket.AF_INET, kind) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def request(self, login, action, **payload):
        from transport.control import connect_api
        from network import send_json_packet, recv_json_packet

        with connect_api("localhost", self.port, configuration=self.config) as s:
            send_json_packet(
                s, dict(action=action, login=login, token=self.tokens[login], **payload)
            )
            return recv_json_packet(s)

    def close(self):
        for p in self.children:
            if p.poll() is None:
                p.terminate()
        for p in self.children:
            try:
                p.wait(4)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for f in self.logs:
            f.close()
        self.folder.cleanup()
