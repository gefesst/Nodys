from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QSizePolicy, QStackedWidget, QLabel
)

from PySide6.QtGui import QIcon
from ui.channels_page import ChannelsPage
from ui.profile_page import ProfilePage
from ui.friends_page import FriendsPage
from ui.chats_page import ChatsPage
from user_context import UserContext
from auth_window import AuthWindow
import os


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.ctx = UserContext()
        self.is_logging_out = False
        self.setWindowTitle("Nodys")
        self.setMinimumSize(900, 600)
        self.setStyleSheet("background-color:#2f3136; color:white;")

        # Получаем путь к иконке относительно этого файла
        current_dir = os.path.dirname(os.path.abspath(__file__))  # client/ui
        parent_dir = os.path.dirname(current_dir)                  # client
        icon_path = os.path.join(parent_dir, "icons", "app_icon.png")

        self.setWindowIcon(QIcon(icon_path))

        # ---------------- Stack ----------------
        self.stack = QStackedWidget(self)

        # Вкладки
        self.friends_page = FriendsPage(self)
        self.chats_page = ChatsPage(self)
        self.channels_page = ChannelsPage(self)   
        self.profile_page = ProfilePage(self.ctx.login, self.ctx.nickname, self)

        self.stack.addWidget(self.friends_page)   # index 0
        self.stack.addWidget(self.chats_page)     # index 1
        self.stack.addWidget(self.channels_page)  # index 2
        self.stack.addWidget(self.profile_page)   # index 3

        # ---------------- Sidebar ----------------
        sidebar = QWidget()
        sidebar.setStyleSheet("background-color:#202225;")
        menu_layout = QVBoxLayout(sidebar)
        menu_layout.setContentsMargins(10, 10, 10, 10)
        menu_layout.setSpacing(10)

        self.buttons = {}

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

        # Добавляем кнопки
        menu_layout.addWidget(make_button("Друзья", lambda: self.stack.setCurrentIndex(0)))
        menu_layout.addWidget(make_button("Чаты", lambda: self.stack.setCurrentIndex(1)))
        menu_layout.addWidget(make_button("Каналы", lambda: self.stack.setCurrentIndex(2)))
        menu_layout.addWidget(make_button("Мой профиль", self.show_profile))
        menu_layout.addStretch()

        # ---------------- Root layout ----------------
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(sidebar, 1)
        root.addWidget(self.stack, 4)

    # ---------------- show profile ----------------
    def show_profile(self):
        self.stack.setCurrentIndex(3)
        # Обновляем онлайн статус профиля
        data = {"action": "status", "login": self.ctx.login}
        from network import NetworkThread
        self.status_thread = NetworkThread("127.0.0.1", 5555, data)
        self.status_thread.finished.connect(
            lambda resp: self.profile_page.update_status(resp.get("online", False))
        )
        self.status_thread.start()

    # ---------------- show login ----------------
    def show_login(self):
        self.is_logging_out = True
        self.ctx.clear()
        self.auth_window = AuthWindow()
        self.auth_window.show()
        self.hide()

    # ---------------- close event ----------------
    def closeEvent(self, event):
        from network import NetworkThread
        if not self.is_logging_out and self.ctx.login:
            close_thread = NetworkThread(
                "127.0.0.1",
                5555,
                {"action": "logout", "login": self.ctx.login}
            )
            close_thread.start()
        event.accept()
