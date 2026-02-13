from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QApplication
from PySide6.QtGui import QIcon
import os
import socket
import json
import struct

from auth_window import AuthWindow
from register_window import RegisterWindow
from ui.main_window import MainWindow
from config import load_config, save_config, clear_config
from user_context import UserContext
from settings import get_api_endpoint


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf


def _send_packet(sock: socket.socket, obj: dict) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def _recv_packet(sock: socket.socket, max_bytes: int = 2_000_000) -> dict:
    hdr = _recv_exact(sock, 4)
    if not hdr:
        return {}
    length = struct.unpack("!I", hdr)[0]
    if length <= 0 or length > max_bytes:
        return {}
    body = _recv_exact(sock, length)
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}


class AppWindow(QWidget):
    """
    Single-window контейнер приложения.
    Все экраны внутри одного QStackedWidget.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nodys")
        self.setMinimumSize(1000, 650)

        # Иконка
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.ctx = UserContext()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget(self)
        root.addWidget(self.stack)

        # Создаем страницы один раз
        self.auth_page = AuthWindow()
        self.register_page = RegisterWindow()
        self.main_page = MainWindow(controller=self)  # твой существующий main_window уже умеет controller

        self.stack.addWidget(self.auth_page)      # index 0
        self.stack.addWidget(self.register_page)  # index 1
        self.stack.addWidget(self.main_page)      # index 2

        # Колбэки навигации
        self.auth_page.on_login_success = self.show_main
        self.auth_page.on_open_register = self.show_register

        self.register_page.on_registered = self.show_auth
        self.register_page.on_back = self.show_auth

        # Стартовый экран: стараемся восстановить сессию по токену
        cfg = load_config()
        token = cfg.get("token") or ""

        # При отсутствии токена оставляем пользователя на экране входа
        # (так мы не храним пароль в конфиге).
        if not token:
            if cfg.get("login"):
                try:
                    self.auth_page.login.setText(cfg.get("login", ""))
                except Exception:
                    pass
            self.show_auth()
            return

        resp = self._try_resume_session(token)
        if resp.get("status") == "ok":
            login = resp.get("login", "")
            nickname = resp.get("nickname", "")
            avatar = resp.get("avatar", "")
            expires_at = resp.get("expires_at", cfg.get("token_expires_at", ""))
            self.ctx.set_user(login=login, nickname=nickname, avatar=avatar, session_token=token, token_expires_at=expires_at)
            save_config({
                "login": login,
                "nickname": nickname,
                "avatar": avatar,
                "token": token,
                "token_expires_at": expires_at,
                # при желании можно переопределить endpoints: api_host/api_port/voice_host/voice_port
            })
            self.show_main()
        else:
            # Сессия недействительна — чистим конфиг и показываем вход
            try:
                clear_config()
            except Exception:
                pass
            self.show_auth()

    def _try_resume_session(self, token: str) -> dict:
        """Try to resume session by token.

        This is a small synchronous call used only on app startup.
        """
        host, port = get_api_endpoint()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)
                s.connect((host, int(port)))
                _send_packet(s, {"action": "resume_session", "token": token})
                return _recv_packet(s)
        except Exception:
            return {}

    def show_auth(self):
        self.stack.setCurrentIndex(0)

    def show_register(self):
        self.stack.setCurrentIndex(1)

    def show_main(self):
        # Полный рефреш main-части под текущий UserContext
        self.main_page.reload_from_context(full_reset=True)
        self.stack.setCurrentIndex(2)

    def logout_to_auth(self):
        # Вызывается из MainWindow/ProfilePage
        self.show_auth()

    def closeEvent(self, event):
        # Корректно закрыть внутреннюю main-страницу (остановка таймеров/потоков)
        try:
            self.main_page.prepare_to_close_app()
        except Exception:
            pass
        app = QApplication.instance()
        if app:
            app.quit()
        event.accept()
