from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QApplication
from PySide6.QtGui import QIcon
import os

from auth_window import AuthWindow
from register_window import RegisterWindow
from ui.main_window import MainWindow
from config import load_config
from user_context import UserContext


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

        # Стартовый экран
        cfg = load_config()
        if cfg.get("login"):
            self.ctx.set_user(
                login=cfg.get("login", ""),
                nickname=cfg.get("nickname", ""),
                avatar=cfg.get("avatar", "")
            )
            self.show_main()
        else:
            self.show_auth()

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
