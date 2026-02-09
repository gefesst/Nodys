from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QLineEdit, QDialog
)
from PySide6.QtCore import Qt, QTimer

from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel


class FriendItem(QFrame):
    def __init__(
        self,
        login,
        nickname,
        avatar_path="",
        online=False,
        request_from=None,
        on_accept=None,
        on_decline=None
    ):
        super().__init__()
        self.setFixedHeight(64)
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
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        avatar = AvatarLabel(size=44)
        avatar.set_avatar(path=avatar_path, login=login, nickname=nickname)
        avatar.set_online(online if request_from is None else None, ring_color="#2f3136")
        layout.addWidget(avatar)

        name = QLabel(nickname)
        name.setStyleSheet("color:white; font-weight:500;")
        layout.addWidget(name)
        layout.addStretch()

        if request_from is not None:
            btn_accept = QPushButton("Принять")
            btn_accept.setStyleSheet("QPushButton { background:#43b581; border-radius:6px; padding:4px 10px; }")
            btn_accept.clicked.connect(lambda: on_accept(request_from))
            layout.addWidget(btn_accept)

            btn_decline = QPushButton("Отклонить")
            btn_decline.setStyleSheet("QPushButton { background:#f04747; border-radius:6px; padding:4px 10px; }")
            btn_decline.clicked.connect(lambda: on_decline(request_from))
            layout.addWidget(btn_decline)


class FriendsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = UserContext()

        self._threads = []
        self._alive = True
        self._loading_friends = False
        self._loading_requests = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Друзья")
        title.setStyleSheet("font-size:18px; font-weight:bold;")
        head.addWidget(title)
        head.addStretch()

        add_btn = QPushButton("Добавить друга")
        add_btn.setStyleSheet("""
            QPushButton { background-color:#5865F2; border-radius:6px; padding:6px 10px; }
            QPushButton:hover { background-color:#4752c4; }
        """)
        add_btn.clicked.connect(self.show_add_friend_dialog)
        head.addWidget(add_btn)
        root.addLayout(head)

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

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)

    def clear_list(self):
        for i in reversed(range(self.list_layout.count() - 1)):
            item = self.list_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def refresh(self):
        self.clear_list()
        self.load_requests()
        self.load_friends()

    # ---------- requests ----------
    def load_requests(self):
        if self._loading_requests:
            return
        self._loading_requests = True

        data = {"action": "get_friend_requests", "login": self.ctx.login}

        def cb(resp):
            try:
                self.handle_requests(resp)
            finally:
                self._loading_requests = False

        self.start_request(data, cb)

    def handle_requests(self, resp):
        requests = resp.get("requests", [])
        if not requests:
            return

        header = QLabel("Запросы дружбы")
        header.setStyleSheet("color:#b9bbbe; font-weight:bold;")
        self.list_layout.insertWidget(self.list_layout.count() - 1, header)

        for login in requests:
            item = FriendItem(
                login=login,
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
        self.start_request(data, lambda _: self.refresh())

    def decline_request(self, from_user):
        data = {
            "action": "decline_friend_request",
            "login": self.ctx.login,
            "from_user": from_user
        }
        self.start_request(data, lambda _: self.refresh())

    # ---------- friends ----------
    def load_friends(self):
        if self._loading_friends:
            return
        self._loading_friends = True

        data = {"action": "get_friends", "login": self.ctx.login}

        def cb(resp):
            try:
                self.handle_friends(resp)
            finally:
                self._loading_friends = False

        self.start_request(data, cb)

    def handle_friends(self, resp):
        friends = resp.get("friends", [])
        if not friends:
            return

        header = QLabel("Друзья")
        header.setStyleSheet("color:#b9bbbe; font-weight:bold; margin-top:10px;")
        self.list_layout.insertWidget(self.list_layout.count() - 1, header)

        for friend in friends:
            item = FriendItem(
                login=friend["login"],
                nickname=friend["nickname"],
                avatar_path=friend.get("avatar", ""),
                online=friend.get("online", False)
            )
            self.list_layout.insertWidget(self.list_layout.count() - 1, item)

    # ---------- add friend ----------
    def show_add_friend_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Добавить друга")
        dialog.setFixedSize(320, 220)

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

        found = {"login": None}

        def find_user():
            login = login_input.text().strip()
            if not login:
                return

            data = {"action": "find_user", "login": login}

            def on_found(resp):
                if resp.get("status") == "ok":
                    found["login"] = resp["login"]
                    info.setText(f"Найден: {resp.get('nickname', resp['login'])} ({resp['login']})")
                    btn_send.setEnabled(True)
                else:
                    found["login"] = None
                    info.setText(resp.get("message", "Пользователь не найден"))
                    btn_send.setEnabled(False)

            self.start_request(data, on_found)

        def send_req():
            to_user = found["login"]
            if not to_user:
                return

            data = {
                "action": "send_friend_request",
                "from_user": self.ctx.login,
                "to_user": to_user
            }

            def on_sent(resp):
                if resp.get("status") == "ok":
                    info.setText("Запрос отправлен")
                    btn_send.setEnabled(False)
                else:
                    info.setText(resp.get("message", "Ошибка отправки"))

            self.start_request(data, on_sent)

        btn_find.clicked.connect(find_user)
        btn_send.clicked.connect(send_req)
        dialog.exec()

    def closeEvent(self, event):
        self._alive = False
        self.timer.stop()
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)
