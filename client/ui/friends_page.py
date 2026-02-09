from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QLineEdit
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
                border-radius:10px;
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

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        name = QLabel(nickname)
        name.setStyleSheet("color:white; font-size:14px; font-weight:600;")
        text_col.addWidget(name)

        sub = QLabel(login if request_from is None else f"Запрос от: {login}")
        sub.setStyleSheet("color:#b9bbbe; font-size:11px;")
        text_col.addWidget(sub)

        layout.addLayout(text_col)
        layout.addStretch()

        if request_from is not None:
            btn_accept = QPushButton("Принять")
            btn_accept.setStyleSheet("""
                QPushButton { background:#43b581; border-radius:6px; padding:5px 10px; color:white; }
                QPushButton:hover { background:#3ca374; }
            """)
            btn_accept.clicked.connect(lambda: on_accept(request_from))
            layout.addWidget(btn_accept)

            btn_decline = QPushButton("Отклонить")
            btn_decline.setStyleSheet("""
                QPushButton { background:#f04747; border-radius:6px; padding:5px 10px; color:white; }
                QPushButton:hover { background:#d83c3c; }
            """)
            btn_decline.clicked.connect(lambda: on_decline(request_from))
            layout.addWidget(btn_decline)


class FriendsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = UserContext()

        # Для ThreadSafeMixin
        self._threads = []
        self._alive = True

        self._loading_friends = False
        self._loading_requests = False
        self._finding_user = False
        self._sending_request = False
        self._found_user = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # ---------- Header ----------
        head = QHBoxLayout()
        title = QLabel("Друзья")
        title.setStyleSheet("font-size:18px; font-weight:700; color:white;")
        head.addWidget(title)
        head.addStretch()

        self.add_btn = QPushButton("Добавить друга")
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color:#5865F2;
                color:white;
                border-radius:8px;
                padding:8px 12px;
                font-weight:600;
            }
            QPushButton:hover {
                background-color:#4752c4;
            }
        """)
        self.add_btn.clicked.connect(self.toggle_add_friend_panel)
        head.addWidget(self.add_btn)

        root.addLayout(head)

        # ---------- Inline add panel ----------
        self.add_panel = QFrame()
        self.add_panel.setVisible(False)
        self.add_panel.setStyleSheet("""
            QFrame {
                background-color:#2f3136;
                border-radius:10px;
            }
            QLineEdit {
                background-color:#202225;
                border:1px solid #40444b;
                border-radius:8px;
                padding:8px;
                color:white;
            }
            QLabel {
                color:#b9bbbe;
            }
        """)
        panel_lay = QVBoxLayout(self.add_panel)
        panel_lay.setContentsMargins(12, 12, 12, 12)
        panel_lay.setSpacing(8)

        panel_title = QLabel("Добавить друга по логину")
        panel_title.setStyleSheet("color:white; font-weight:600; font-size:13px;")
        panel_lay.addWidget(panel_title)

        row = QHBoxLayout()
        self.login_input = QLineEdit()
        self.login_input.setPlaceholderText("Введите логин пользователя")
        row.addWidget(self.login_input)

        self.find_btn = QPushButton("Найти")
        self.find_btn.setStyleSheet("""
            QPushButton {
                background-color:#3c3f45;
                color:white;
                border-radius:8px;
                padding:8px 12px;
            }
            QPushButton:hover { background-color:#4a4e57; }
        """)
        self.find_btn.clicked.connect(self.find_user_inline)
        row.addWidget(self.find_btn)
        panel_lay.addLayout(row)

        self.find_result = QLabel("")
        self.find_result.setWordWrap(True)
        panel_lay.addWidget(self.find_result)

        panel_actions = QHBoxLayout()
        panel_actions.addStretch()

        self.send_request_btn = QPushButton("Отправить запрос")
        self.send_request_btn.setEnabled(False)
        self.send_request_btn.setStyleSheet("""
            QPushButton {
                background-color:#5865F2;
                color:white;
                border-radius:8px;
                padding:8px 12px;
                font-weight:600;
            }
            QPushButton:hover { background-color:#4752c4; }
            QPushButton:disabled {
                background-color:#3a3d42;
                color:#8e9297;
            }
        """)
        self.send_request_btn.clicked.connect(self.send_request_inline)
        panel_actions.addWidget(self.send_request_btn)

        self.close_add_panel_btn = QPushButton("Скрыть")
        self.close_add_panel_btn.setStyleSheet("""
            QPushButton {
                background-color:#3c3f45;
                color:white;
                border-radius:8px;
                padding:8px 12px;
            }
            QPushButton:hover { background-color:#4a4e57; }
        """)
        self.close_add_panel_btn.clicked.connect(self.hide_add_friend_panel)
        panel_actions.addWidget(self.close_add_panel_btn)

        panel_lay.addLayout(panel_actions)

        root.addWidget(self.add_panel)

        # ---------- List ----------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border:none; background:transparent;")

        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

        self.setStyleSheet("background-color:#36393f; color:white;")

        # Auto refresh
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)

        self.refresh()

    # ==================================================
    # ================= Lifecycle ======================
    # ==================================================

    def reset_for_user(self):
        """
        Полный reset при перелогине/смене пользователя.
        """
        self._loading_friends = False
        self._loading_requests = False
        self._finding_user = False
        self._sending_request = False
        self._found_user = None

        self.clear_list()
        self.hide_add_friend_panel()

    def closeEvent(self, event):
        self._alive = False
        if self.timer.isActive():
            self.timer.stop()
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)

    # ==================================================
    # ================= UI helpers =====================
    # ==================================================

    def toggle_add_friend_panel(self):
        visible = not self.add_panel.isVisible()
        self.add_panel.setVisible(visible)
        self.add_btn.setText("Скрыть добавление" if visible else "Добавить друга")

        if not visible:
            self._reset_add_panel_state()

    def hide_add_friend_panel(self):
        self.add_panel.setVisible(False)
        self.add_btn.setText("Добавить друга")
        self._reset_add_panel_state()

    def _reset_add_panel_state(self):
        self.login_input.clear()
        self.find_result.setText("")
        self.send_request_btn.setEnabled(False)
        self._found_user = None

    def clear_list(self):
        # удаляем всё кроме stretch
        for i in reversed(range(self.list_layout.count() - 1)):
            item = self.list_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def _add_section_header(self, text: str):
        header = QLabel(text)
        header.setStyleSheet("""
            QLabel {
                color:#b9bbbe;
                font-size:11px;
                font-weight:700;
                text-transform: uppercase;
                padding:4px 2px;
            }
        """)
        self.list_layout.insertWidget(self.list_layout.count() - 1, header)

    # ==================================================
    # ================= Refresh ========================
    # ==================================================

    def refresh(self):
        if not self._alive or not self.ctx.login:
            return
        self.clear_list()
        self.load_requests()
        self.load_friends()

    # ==================================================
    # ================ Friend requests =================
    # ==================================================

    def load_requests(self):
        if not self._alive or self._loading_requests or not self.ctx.login:
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

        self._add_section_header(f"Запросы дружбы — {len(requests)}")

        for req_login in requests:
            item = FriendItem(
                login=req_login,
                nickname=req_login,  # Можно заменить, если сервер будет возвращать nickname по заявке
                request_from=req_login,
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
        self.start_request(data, lambda _resp: self.refresh())

    def decline_request(self, from_user):
        data = {
            "action": "decline_friend_request",
            "login": self.ctx.login,
            "from_user": from_user
        }
        self.start_request(data, lambda _resp: self.refresh())

    # ==================================================
    # =================== Friends ======================
    # ==================================================

    def load_friends(self):
        if not self._alive or self._loading_friends or not self.ctx.login:
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
            empty = QLabel("У тебя пока нет друзей")
            empty.setStyleSheet("color:#8e9297; padding:8px;")
            self.list_layout.insertWidget(self.list_layout.count() - 1, empty)
            return

        friends_sorted = sorted(
            friends,
            key=lambda f: (0 if f.get("online", False) else 1, f.get("nickname", "").lower())
        )

        online_friends = [f for f in friends_sorted if f.get("online", False)]
        offline_friends = [f for f in friends_sorted if not f.get("online", False)]

        if online_friends:
            self._add_section_header(f"В сети — {len(online_friends)}")
            for friend in online_friends:
                item = FriendItem(
                    login=friend["login"],
                    nickname=friend["nickname"],
                    avatar_path=friend.get("avatar", ""),
                    online=True
                )
                self.list_layout.insertWidget(self.list_layout.count() - 1, item)

        if offline_friends:
            self._add_section_header(f"Не в сети — {len(offline_friends)}")
            for friend in offline_friends:
                item = FriendItem(
                    login=friend["login"],
                    nickname=friend["nickname"],
                    avatar_path=friend.get("avatar", ""),
                    online=False
                )
                self.list_layout.insertWidget(self.list_layout.count() - 1, item)

    # ==================================================
    # ============== Inline add friend =================
    # ==================================================

    def find_user_inline(self):
        if self._finding_user or not self._alive:
            return

        login = self.login_input.text().strip()
        if not login:
            self.find_result.setText("Введи логин для поиска.")
            self.send_request_btn.setEnabled(False)
            self._found_user = None
            return

        if login == self.ctx.login:
            self.find_result.setText("Нельзя добавить самого себя.")
            self.send_request_btn.setEnabled(False)
            self._found_user = None
            return

        self._finding_user = True
        self.find_result.setText("Ищу пользователя...")
        self.send_request_btn.setEnabled(False)
        self._found_user = None

        data = {"action": "find_user", "login": login}

        def cb(resp):
            try:
                if resp.get("status") == "ok":
                    self._found_user = {
                        "login": resp.get("login", ""),
                        "nickname": resp.get("nickname", resp.get("login", "")),
                        "avatar": resp.get("avatar", "")
                    }
                    self.find_result.setText(
                        f"Найден: {self._found_user['nickname']} ({self._found_user['login']})"
                    )
                    self.send_request_btn.setEnabled(True)
                else:
                    self._found_user = None
                    self.find_result.setText(resp.get("message", "Пользователь не найден"))
                    self.send_request_btn.setEnabled(False)
            finally:
                self._finding_user = False

        self.start_request(data, cb)

    def send_request_inline(self):
        if self._sending_request or not self._alive:
            return

        if not self._found_user:
            self.find_result.setText("Сначала найди пользователя.")
            return

        to_user = self._found_user["login"]
        self._sending_request = True
        self.send_request_btn.setEnabled(False)
        self.find_result.setText("Отправляю запрос...")

        data = {
            "action": "send_friend_request",
            "from_user": self.ctx.login,
            "to_user": to_user
        }

        def cb(resp):
            try:
                if resp.get("status") == "ok":
                    self.find_result.setText("✅ Запрос дружбы отправлен")
                    self.refresh()
                else:
                    self.find_result.setText(resp.get("message", "Ошибка отправки запроса"))
                    self.send_request_btn.setEnabled(True)
            finally:
                self._sending_request = False

        self.start_request(data, cb)
