"""Disposable real Nodys TCP/TLS + UDP server. Never opens the user's databases."""

import json, os, socket, subprocess, sys, tempfile, time, secrets
from pathlib import Path


class Sandbox:
    def __init__(self, project, *, reference_dialogs=False, data_dir=None):
        self.project = Path(project)
        self.folder = tempfile.TemporaryDirectory(prefix="nodus-ui-lab-") if data_dir is None else None
        self.path = Path(data_dir) if data_dir is not None else Path(self.folder.name)
        self.path.mkdir(parents=True, exist_ok=True)
        self.path.chmod(0o700)
        existing = (self.path / "users.db").exists()
        self.children = []
        self.logs = []
        os.environ["NODYS_CONFIG_DIR"] = str(self.path / "config")
        (self.path / "config").mkdir(exist_ok=True)
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
            ("alexey", "Алексей Морозов"),
            ("anna", "Анна Смирнова"),
            ("maria", "Мария Ким"),
            ("sergey", "Сергей Волков"),
        ]
        if reference_dialogs:
            self.people += [("pavel", "Павел Орлов"), ("darya", "Дарья Соколова")]
        self.me = "andrey"
        for login, name in [(self.me, "Андрей")] + self.people:
            if not existing:
                assert server.add_user(login, secrets.token_urlsafe(20), name, "")
            self.tokens[login] = server.create_session(login)[0]
            if login != self.me and not existing:
                server.send_friend_request(self.me, login)
                server.accept_friend_request(self.me, login)
        server.set_session_offline(self.tokens["sergey"])
        if reference_dialogs:
            for peer in ("pavel", "darya"):
                server.set_session_offline(self.tokens[peer])
        if not existing:
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
            if reference_dialogs:
                self.seed_reference_dialogs(server)
            self.channel = server.create_channel(self.me, "Свои люди")
            server.join_channel_by_code(self.people[0][0], self.channel["code"])
        else:
            channels = server.list_user_channels(self.me)
            self.channel = channels[0] if channels else {}
        self.port = self.free_port()
        self.voice_port = self.free_port(socket.SOCK_DGRAM)
        cert = self.path / "cert.pem"
        key = self.path / "key.pem"
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        renew = not (cert.exists() and key.exists())
        if not renew:
            try:
                renew = x509.load_pem_x509_certificate(cert.read_bytes()).not_valid_after_utc < datetime.now(timezone.utc) + timedelta(days=1)
            except ValueError:
                renew = True
        if renew:
            suffix=secrets.token_hex(6)
            new_cert=self.path/f"cert-{suffix}.pem"
            new_key=self.path/f"key-{suffix}.pem"
            create_certificate(new_cert,new_key)
            new_cert.replace(cert);new_key.replace(key)
        self.config = dict(
            api_host="localhost",
            api_port=self.port,
            voice_host="127.0.0.1",
            voice_port=self.voice_port,
            api_tls=True,
            api_ca_file=str(cert),
        )
        configfile = self.path / "config/config.json"
        previous = json.loads(configfile.read_text()) if configfile.exists() else {}
        configfile.write_text(json.dumps(dict(previous, **self.config)))
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

    def seed_reference_dialogs(self, server):
        """Same six conversations as the approved chat; disposable database only."""
        from datetime import datetime, timedelta, timezone
        from server.storage.database import connect
        latest = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0) - timedelta(minutes=10)
        with connect(server.CHAT_DB) as conn:
            rows=conn.execute("SELECT id FROM messages WHERE from_user='alexey' OR to_user='alexey' ORDER BY id").fetchall()
            for index, (message_id,) in enumerate(rows):
                stamp = latest - timedelta(minutes=len(rows)-1-index)
                conn.execute("UPDATE messages SET timestamp=? WHERE id=?", (str(stamp),message_id))
            conn.execute("DELETE FROM messages WHERE from_user<>'alexey' AND to_user<>'alexey'")
            for peer,text,stamp,read in [
                ('anna','Спасибо за помощь.',latest-timedelta(minutes=17),0),
                ('anna','Спасибо, всё получилось',latest-timedelta(minutes=16),0),
                ('sergey','Завтра после семи?',latest-timedelta(minutes=28),1),
                ('maria','Отправила новые идеи',latest-timedelta(minutes=110),1),
                ('pavel','Хорошо, до встречи',latest-timedelta(days=1),1),
                ('darya','На связи',latest-timedelta(days=2),1),
            ]:
                conn.execute("INSERT INTO messages(from_user,to_user,text,timestamp,is_read) VALUES(?,?,?,?,?)",
                             (peer,self.me,text,str(stamp),read))
        server.mark_chat_read('alexey',self.me)

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
        if self.folder is not None:
            self.folder.cleanup()
