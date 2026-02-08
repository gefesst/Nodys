import os

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QSizePolicy, QStackedWidget, QApplication
)
from PySide6.QtGui import QIcon

from ui.channels_page import ChannelsPage
from ui.profile_page import ProfilePage
from ui.friends_page import FriendsPage
from ui.chats_page import ChatsPage

from user_context import UserContext
from network import NetworkThread


class MainWindow(QWidget):
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.ctx = UserContext()

        self.is_logging_out = False
        self.close_thread = None
        self._is_closing = False

        self.setWindowTitle("Nodys")
        self.setMinimumSize(900, 600)
        self.setStyleSheet("background-color:#2f3136; color:white;")

        # Иконка приложения (если есть)
        current_dir = os.path.dirname(os.path.abspath(__file__))   # client/ui
        client_dir = os.path.dirname(current_dir)                  # client
        icon_path = os.path.join(client_dir, "icons", "app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # ---------------- Stack ----------------
        self.stack = QStackedWidget(self)

        self.friends_page = FriendsPage(self)      # index 0
        self.chats_page = ChatsPage(self)          # index 1
        self.channels_page = ChannelsPage(self)    # index 2
        self.profile_page = ProfilePage(self.ctx.login, self.ctx.nickname, self)  # index 3

        self.stack.addWidget(self.friends_page)
        self.stack.addWidget(self.chats_page)
        self.stack.addWidget(self.channels_page)
        self.stack.addWidget(self.profile_page)

        # ---------------- Sidebar ----------------
        sidebar = QWidget()
        sidebar.setStyleSheet("background-color:#202225;")
        menu_layout = QVBoxLayout(sidebar)
        menu_layout.setContentsMargins(10, 10, 10, 10)
        menu_layout.setSpacing(10)

        def make_button(text, callback):
            btn = QPushButton(text)
            btn.setFixedHeight(50)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setStyleSheet("""
                QPushButton {
                    background-color:#2f3136;
                    border-radius:10px;
                    color:white;
                }
                QPushButton:hover {
                    background-color:#5865F2;
                }
            """)
            btn.clicked.connect(callback)
            return btn

        menu_layout.addWidget(make_button("Друзья", self.show_friends))
        menu_layout.addWidget(make_button("Чаты", self.show_chats))
        menu_layout.addWidget(make_button("Каналы", self.show_channels))
        menu_layout.addWidget(make_button("Мой профиль", self.show_profile))
        menu_layout.addStretch()

        # ---------------- Root layout ----------------
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(sidebar, 1)
        root.addWidget(self.stack, 4)

        # Стартовая вкладка
        self.show_friends()

    # ==================================================
    # ================== Навигация ======================
    # ==================================================

    def show_friends(self):
        self.chats_page.stop_auto_update()
        self.stack.setCurrentIndex(0)
        if hasattr(self.friends_page, "refresh"):
            self.friends_page.refresh()

    def show_chats(self):
        self.stack.setCurrentIndex(1)
        if hasattr(self.chats_page, "load_friends"):
            self.chats_page.load_friends()
        self.chats_page.start_auto_update()

    def show_channels(self):
        self.chats_page.stop_auto_update()
        self.stack.setCurrentIndex(2)

    def show_profile(self):
        self.chats_page.stop_auto_update()
        self.stack.setCurrentIndex(3)

        # Обновляем онлайн-статус профиля
        data = {"action": "status", "login": self.ctx.login}
        self.status_thread = NetworkThread("127.0.0.1", 5555, data)

        def on_status(resp):
            self.profile_page.update_status(resp.get("online", False))

        self.status_thread.finished.connect(on_status)
        self.status_thread.start()

    # ==================================================
    # ============== Переход к авторизации =============
    # ==================================================

    def show_login(self):
        """
        Вызывается из ProfilePage после logout.
        Это НЕ закрытие приложения, а смена сессии.
        """
        self.is_logging_out = True

        # Остановить автообновления
        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass
        try:
            if hasattr(self.friends_page, "timer"):
                self.friends_page.timer.stop()
        except Exception:
            pass

        # Корректно остановить запросы страниц
        for page in (self.friends_page, self.chats_page, self.profile_page):
            try:
                page._alive = False
                if hasattr(page, "shutdown_requests"):
                    page.shutdown_requests(wait_ms=1000)
            except Exception:
                pass

        self.ctx.clear()

        if self.controller is not None:
            self.controller.logout_to_auth()

    # ==================================================
    # ================== Закрытие окна =================
    # ==================================================

    def closeEvent(self, event):
        # Защита от повторного входа в closeEvent
        if self._is_closing:
            event.accept()
            return
        self._is_closing = True

        # Если это logout-переход (show_login), не выходим из приложения
        if self.is_logging_out:
            event.accept()
            return

        # Это именно закрытие приложения на крестик
        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass

        try:
            if hasattr(self.friends_page, "timer"):
                self.friends_page.timer.stop()
        except Exception:
            pass

        # Остановить фоновые запросы страниц
        for page in (self.friends_page, self.chats_page, self.profile_page):
            try:
                page._alive = False
                if hasattr(page, "shutdown_requests"):
                    page.shutdown_requests(wait_ms=1000)
            except Exception:
                pass

        # Снять online-статус на сервере (коротко, без долгой блокировки)
        try:
            if self.ctx.login:
                t = NetworkThread("127.0.0.1", 5555, {"action": "logout", "login": self.ctx.login})
                t.start()
                t.wait(500)
        except Exception:
            pass

        # Полное завершение процесса приложения
        app = QApplication.instance()
        if app is not None:
            app.quit()

        event.accept()
