import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame,
    QLineEdit, QDialog
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from network import NetworkThread
from user_context import UserContext
from PySide6.QtCore import QTimer


# ==================================================
# =================== FriendItem ===================
# ==================================================

class FriendItem(QFrame):
    def __init__(
        self,
        nickname,
        avatar_path="",
        online=False,
        request_from=None,
        on_accept=None,
        on_decline=None
    ):
        super().__init__()

        self.setFixedHeight(56)
        self.setStyleSheet("""
            QFrame {
                background-color:#2f3136;
                border-radius:8px;
            }
            QFrame:hover {
                background-color:#3a3d42;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        # Avatar
        avatar = QLabel()
        avatar.setFixedSize(40, 40)
        avatar.setStyleSheet("background-color:#202225; border-radius:20px;")
        avatar_loaded = False
        if avatar_path and os.path.exists(avatar_path):
            pix = QPixmap(avatar_path)
            avatar_loaded = True
        else:
            for ext in (".png", ".jpg", ".jpeg"):
                local_path = os.path.join("avatars", f"{nickname}{ext}")
                if os.path.exists(local_path):
                    pix = QPixmap(local_path)
                    avatar_loaded = True
                    break

        if avatar_loaded:
            avatar.setPixmap(
                pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        layout.addWidget(avatar)

        # Online indicator (только для друзей)
        if request_from is None:
            status = QLabel(avatar)
            status.setFixedSize(10, 10)
            status.move(28, 28)
            status.setStyleSheet(
                "border-radius:5px; background-color:{};"
                .format("#43b581" if online else "#747f8d")
            )
            status.setAttribute(Qt.WA_TransparentForMouseEvents)

        # Nickname
        name = QLabel(nickname)
        name.setStyleSheet("color:white; font-weight:500;")
        layout.addWidget(name)

        layout.addStretch()

        # Buttons for requests
        if request_from:
            accept = QPushButton("Принять")
            accept.setStyleSheet("""
                QPushButton {
                    background-color:#43b581;
                    border-radius:6px;
                    padding:4px 10px;
                }
            """)
            accept.clicked.connect(lambda: on_accept(request_from))
            layout.addWidget(accept)

            decline = QPushButton("Отклонить")
            decline.setStyleSheet("""
                QPushButton {
                    background-color:#f04747;
                    border-radius:6px;
                    padding:4px 10px;
                }
            """)
            decline.clicked.connect(lambda: on_decline(request_from))
            layout.addWidget(decline)


# ==================================================
# ================== FriendsPage ===================
# ==================================================

class FriendsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.ctx = UserContext()

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("Друзья")
        title.setStyleSheet("font-size:18px; font-weight:bold;")
        header.addWidget(title)
        header.addStretch()

        add_btn = QPushButton("Добавить друга")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color:#5865F2;
                border-radius:6px;
                padding:6px 10px;
            }
            QPushButton:hover {
                background-color:#4752c4;
            }
        """)
        add_btn.clicked.connect(self.show_add_friend_dialog)
        header.addWidget(add_btn)

        root.addLayout(header)

        # Scroll
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border:none;")

        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll)

        self.setStyleSheet("background-color:#36393f; color:white;")

        self.refresh()

        # авто-обновление онлайна
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load_friends)
        self.timer.start(5000)  # каждые 5 секунд
    
    def clear_friends_only(self):
        for i in reversed(range(self.list_layout.count())):
            item = self.list_layout.itemAt(i)
            if not item or not item.widget():
                continue

            widget = item.widget()
            if isinstance(widget, FriendItem) and widget.property("is_friend"):
                widget.deleteLater()

    def clear_friends_header(self):
        for i in reversed(range(self.list_layout.count())):
            item = self.list_layout.itemAt(i)
            if not item or not item.widget():
                continue
            widget = item.widget()
            if isinstance(widget, QLabel) and widget.text() == "Друзья":
                widget.deleteLater()


    # ==================================================
    # =================== REFRESH =====================
    # ==================================================

    def refresh(self):
        self.clear_list()
        self.load_requests()
        self.load_friends()

    def clear_list(self):
        for i in reversed(range(self.list_layout.count() - 1)):
            item = self.list_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    # ==================================================
    # ================= FRIEND REQUESTS ===============
    # ==================================================

    def load_requests(self):
        data = {
            "action": "get_friend_requests",
            "login": self.ctx.login
        }
        self.req_thread = NetworkThread("127.0.0.1", 5555, data)
        self.req_thread.finished.connect(self.handle_requests)
        self.req_thread.start()

    def handle_requests(self, resp):
        requests = resp.get("requests", [])
        if not requests:
            return

        header = QLabel("Запросы дружбы")
        header.setStyleSheet("color:#b9bbbe; font-weight:bold;")
        self.list_layout.insertWidget(self.list_layout.count() - 1, header)

        for login in requests:
            item = FriendItem(
                nickname=login,
                request_from=login,
                on_accept=self.accept_request,
                on_decline=self.decline_request
            )
            self.list_layout.insertWidget(self.list_layout.count() - 1, item)

    def accept_request(self, from_user):
        data = {
            "action": "accept_friend_request",
            "login": self.ctx.login,
            "from_user": from_user
        }
        self.action_thread = NetworkThread("127.0.0.1", 5555, data)
        self.action_thread.finished.connect(lambda _: self.refresh())
        self.action_thread.start()

    def decline_request(self, from_user):
        data = {
            "action": "decline_friend_request",
            "login": self.ctx.login,
            "from_user": from_user
        }
        self.action_thread = NetworkThread("127.0.0.1", 5555, data)
        self.action_thread.finished.connect(lambda _: self.refresh())
        self.action_thread.start()

    # ==================================================
    # ===================== FRIENDS ===================
    # ==================================================

    def load_friends(self):
        self.clear_friends_only()

        data = {
            "action": "get_friends",
            "login": self.ctx.login
        }
        self.friends_thread = NetworkThread("127.0.0.1", 5555, data)
        self.friends_thread.finished.connect(self.handle_friends)
        self.friends_thread.start()

    def handle_friends(self, resp):
        friends = resp.get("friends", [])
        if not friends:
            return

        header = QLabel("Друзья")
        header.setStyleSheet("color:#b9bbbe; font-weight:bold; margin-top:10px;")
        self.list_layout.insertWidget(self.list_layout.count() - 1, header)

        for friend in friends:
            item = FriendItem(
                nickname=friend["nickname"],
                avatar_path=friend.get("avatar", ""),
                online=friend.get("online", False)
            )
            item.setProperty("is_friend", True)
            self.list_layout.insertWidget(self.list_layout.count() - 1, item)

    def load_friends(self):
        # Убираем старый заголовок, чтобы не дублировался
        self.clear_friends_header()
    
        self.clear_friends_only()  # удаляем старые карточки друзей

        data = {
            "action": "get_friends",
            "login": self.ctx.login
        }
        self.friends_thread = NetworkThread("127.0.0.1", 5555, data)
        self.friends_thread.finished.connect(self.handle_friends)
        self.friends_thread.start()


    # ==================================================
    # ================= ADD FRIEND ====================
    # ==================================================

    def show_add_friend_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Добавить друга")
        dialog.setFixedSize(300, 200)

        layout = QVBoxLayout(dialog)

        login_input = QLineEdit()
        login_input.setPlaceholderText("Введите логин пользователя")
        layout.addWidget(login_input)

        info = QLabel("")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_find = QPushButton("Найти")
        layout.addWidget(btn_find)

        btn_send = QPushButton("Отправить запрос дружбы")
        btn_send.setEnabled(False)
        layout.addWidget(btn_send)

        found_user_login = {"login": None}

        # ---------- поиск пользователя ----------
        def find_user():
            login = login_input.text().strip()
            if not login:
                return

            data = {
                "action": "find_user",
                "login": login
            }

            self.find_thread = NetworkThread("127.0.0.1", 5555, data)

            def handle(resp):
                if resp.get("status") == "ok":
                    found_user_login["login"] = resp["login"]
                    info.setText(f"Найден пользователь: {resp['nickname']}")
                    btn_send.setEnabled(True)
                else:
                    info.setText(resp.get("message", "Пользователь не найден"))
                    btn_send.setEnabled(False)

            self.find_thread.finished.connect(handle)
            self.find_thread.start()

        # ---------- отправка запроса ----------
        def send_request():
            to_user = found_user_login["login"]
            if not to_user:
                return

            data = {
                "action": "send_friend_request",
                "from_user": self.ctx.login,
                "to_user": to_user
            }

            self.send_thread = NetworkThread("127.0.0.1", 5555, data)

            def handle(resp):
                if resp.get("status") == "ok":
                    info.setText("Запрос дружбы отправлен")
                    btn_send.setEnabled(False)
                    btn_find.setEnabled(False)
                else:
                    info.setText(resp.get("message", "Ошибка отправки"))

            self.send_thread.finished.connect(handle)
            self.send_thread.start()

        btn_find.clicked.connect(find_user)
        btn_send.clicked.connect(send_request)

        dialog.exec()

