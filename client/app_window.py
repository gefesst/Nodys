from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QApplication, QLabel, QPushButton
from PySide6.QtCore import Qt, Slot, QTimer
from network import NetworkThread
from PySide6.QtGui import QIcon
import os

from auth_window import AuthWindow
from register_window import RegisterWindow
from ui.main_window import MainWindow
from config import load_config, save_config, clear_config
from user_context import UserContext


class AppWindow(QWidget):
    """
    Single-window контейнер приложения.
    Все экраны внутри одного QStackedWidget.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nodys")
        # Стартовый минимум: шире, но чуть ниже по высоте.
        self.setMinimumSize(1120, 620)

        # Иконка
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        from application.logout_outbox import retry_pending
        retry_pending()
        self._logout_retry_timer = QTimer(self)
        self._logout_retry_timer.setInterval(30000)
        self._logout_retry_timer.timeout.connect(retry_pending)
        self._logout_retry_timer.start()
        self.ctx = UserContext()
        self._resume_token = None
        self._resume_thread = None
        self._closing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget(self)
        root.addWidget(self.stack)

        # Создаем auth/register сразу, а MainWindow — лениво после успешной авторизации.
        # Это убирает фоновую активность (таймеры/запросы) до логина.
        self.auth_page = AuthWindow()
        self.register_page = RegisterWindow()
        self.main_page = None

        self.stack.addWidget(self.auth_page)
        self.stack.addWidget(self.register_page)

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

        self.resume_page = QWidget()
        resume_layout = QVBoxLayout(self.resume_page)
        resume_layout.addWidget(QLabel("Восстанавливаем вход…"))
        cancel = QPushButton("Войти вручную")
        cancel.clicked.connect(self._cancel_resume)
        resume_layout.addWidget(cancel)
        self.stack.addWidget(self.resume_page)
        self.stack.setCurrentWidget(self.resume_page)
        self._resume_token = token
        self._resume_thread = NetworkThread(None, None, {"action":"resume_session", "token":token})
        self._resume_thread.finished.connect(self._handle_resume_response, Qt.QueuedConnection)
        self._resume_thread.start()

    def _cancel_resume(self):
        self._resume_token = None
        if self._resume_thread:
            self._resume_thread.abort()
        self.show_auth()

    @Slot(dict)
    def _handle_resume_response(self, resp):
        token = self._resume_token
        cfg = load_config()
        if self._closing or not token or cfg.get("token") != token:
            return
        self._resume_token = None
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
            # Preserve credentials on transient network failures.
            try:
                if resp.get("code") == "session_invalid":
                    clear_config()
            except Exception:
                pass
            self.show_auth()

    def _ensure_main_page(self):
        if self.main_page is None:
            self.main_page = MainWindow(controller=self)
            self.stack.addWidget(self.main_page)

    def show_auth(self):
        self.stack.setCurrentWidget(self.auth_page)

    def show_register(self):
        self.stack.setCurrentWidget(self.register_page)

    def show_main(self):
        self._resume_token = None
        self._ensure_main_page()
        # Полный рефреш main-части под текущий UserContext
        self.main_page.reload_from_context(full_reset=True)
        self.stack.setCurrentWidget(self.main_page)

    def logout_to_auth(self):
        # Вызывается из MainWindow/ProfilePage
        self.show_auth()

    def closeEvent(self, event):
        self._closing = True
        self._resume_token = None
        if self._resume_thread:
            self._resume_thread.abort()
        for page in (self.auth_page, self.register_page):
            request = getattr(page, "thread", None)
            if request:
                request.abort()
        # Корректно закрыть внутреннюю main-страницу (остановка таймеров/потоков)
        try:
            if self.main_page is not None:
                self.main_page.prepare_to_close_app()
        except Exception:
            pass
        app = QApplication.instance()
        if app:
            app.quit()
        event.accept()
