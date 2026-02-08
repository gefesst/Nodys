import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QLineEdit, QPushButton, QSizePolicy
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QTimer

from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin


class ChatFriendItem(QFrame):
    def __init__(self, login, nickname, avatar_path="", on_click=None, is_active=False, online=False):
        super().__init__()

        border = "border:2px solid #5865F2;" if is_active else "border:1px solid transparent;"
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            QFrame {{
                background-color:#2f3136;
                border-radius:8px;
                {border}
            }}
            QFrame:hover {{
                background-color:#3a3d42;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        avatar = QLabel()
        avatar.setFixedSize(40, 40)
        avatar.setStyleSheet("background-color:#202225; border-radius:20px;")

        pix = None
        if avatar_path and os.path.exists(avatar_path):
            pix = QPixmap(avatar_path)
        else:
            for ext in (".png", ".jpg", ".jpeg"):
                p = os.path.join("avatars", f"{login}{ext}")
                if os.path.exists(p):
                    pix = QPixmap(p)
                    break

        if pix is not None and not pix.isNull():
            avatar.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(avatar)

        status = QLabel(avatar)
        status.setFixedSize(10, 10)
        status.move(28, 28)
        status.setStyleSheet(
            f"border-radius:5px; background-color:{'#43b581' if online else '#747f8d'};"
        )
        status.setAttribute(Qt.WA_TransparentForMouseEvents)

        name = QLabel(nickname)
        name.setStyleSheet("color:white; font-weight:500;")
        layout.addWidget(name)
        layout.addStretch()

        if on_click:
            self.mousePressEvent = lambda event: on_click()


class MessageBubble(QFrame):
    def __init__(self, text, is_outgoing=False):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {"#5865F2" if is_outgoing else "#4f545c"};
                color:white;
                border-radius:8px;
                padding:6px 10px;
            }}
        """)

        if is_outgoing:
            lay.addStretch()
            lay.addWidget(label)
        else:
            lay.addWidget(label)
            lay.addStretch()


class ChatsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = UserContext()

        self._threads = []
        self._alive = True

        self.active_friend = None
        self._loading_friends = False
        self._loading_messages = False
        self._sending = False

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(15)

        # left
        self.friends_container = QWidget()
        self.friends_layout = QVBoxLayout(self.friends_container)
        self.friends_layout.setSpacing(6)
        self.friends_layout.addStretch()

        self.friends_scroll = QScrollArea()
        self.friends_scroll.setWidgetResizable(True)
        self.friends_scroll.setWidget(self.friends_container)
        self.friends_scroll.setStyleSheet("border:none;")
        root.addWidget(self.friends_scroll, 1)

        # right
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(5)

        self.chat_header = QLabel("Выберите друга")
        self.chat_header.setStyleSheet("font-weight:bold; color:white; font-size:16px;")
        self.chat_layout.addWidget(self.chat_header)

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.addStretch()

        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setWidget(self.messages_container)
        self.messages_scroll.setStyleSheet("border:none; background-color:#36393f;")
        self.chat_layout.addWidget(self.messages_scroll)

        input_lay = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Введите сообщение...")
        self.input_edit.setStyleSheet("""
            QLineEdit {
                background-color:#202225;
                color:white;
                border-radius:6px;
                padding:6px;
            }
        """)
        input_lay.addWidget(self.input_edit)

        self.send_btn = QPushButton("Отправить")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color:#5865F2;
                color:white;
                border-radius:6px;
                padding:6px 10px;
            }
            QPushButton:hover {
                background-color:#4752c4;
            }
        """)
        self.send_btn.clicked.connect(self.send_message)
        input_lay.addWidget(self.send_btn)

        self.chat_layout.addLayout(input_lay)
        root.addWidget(self.chat_container, 3)

        self.setStyleSheet("background-color:#36393f; color:white;")

        self.msg_timer = QTimer(self)
        self.msg_timer.setInterval(2000)
        self.msg_timer.timeout.connect(self.load_messages)

        self.friends_timer = QTimer(self)
        self.friends_timer.setInterval(3000)
        self.friends_timer.timeout.connect(self.load_friends)

        self.load_friends()

    def start_auto_update(self):
        if not self.friends_timer.isActive():
            self.friends_timer.start()
        if self.active_friend and not self.msg_timer.isActive():
            self.msg_timer.start()

    def stop_auto_update(self):
        if self.msg_timer.isActive():
            self.msg_timer.stop()
        if self.friends_timer.isActive():
            self.friends_timer.stop()

    def _clear_friends(self):
        for i in reversed(range(self.friends_layout.count() - 1)):
            item = self.friends_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def _clear_messages(self):
        for i in reversed(range(self.messages_layout.count() - 1)):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

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
        if resp.get("status") != "ok":
            return

        friends = resp.get("friends", [])
        current_login = self.active_friend["login"] if self.active_friend else None

        self._clear_friends()

        if current_login:
            for f in friends:
                if f["login"] == current_login:
                    self.active_friend = f
                    self.chat_header.setText(f["nickname"])
                    break

        for friend in friends:
            item = ChatFriendItem(
                login=friend["login"],
                nickname=friend["nickname"],
                avatar_path=friend.get("avatar", ""),
                online=friend.get("online", False),
                is_active=(friend["login"] == current_login),
                on_click=lambda f=friend: self.open_chat(f)
            )
            self.friends_layout.insertWidget(self.friends_layout.count() - 1, item)

    def open_chat(self, friend):
        self.active_friend = friend
        self.chat_header.setText(friend["nickname"])
        self.load_friends()   # чтобы подсветить выбранного
        self.load_messages()
        if not self.msg_timer.isActive():
            self.msg_timer.start()

    def load_messages(self):
        if not self.active_friend or self._loading_messages:
            return
        self._loading_messages = True

        data = {
            "action": "get_messages",
            "from_user": self.ctx.login,
            "to_user": self.active_friend["login"]
        }

        def cb(resp):
            try:
                self.handle_messages(resp)
            finally:
                self._loading_messages = False

        self.start_request(data, cb)

    def handle_messages(self, resp):
        if resp.get("status") != "ok":
            return

        self._clear_messages()
        for msg in resp.get("messages", []):
            text = msg.get("text", msg.get("message", ""))
            is_outgoing = (msg.get("from_user") == self.ctx.login)
            bubble = MessageBubble(text, is_outgoing)
            self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)

        sb = self.messages_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send_message(self):
        if not self.active_friend or self._sending:
            return

        text = self.input_edit.text().strip()
        if not text:
            return

        self._sending = True
        data = {
            "action": "send_message",
            "from_user": self.ctx.login,
            "to_user": self.active_friend["login"],
            "message": text
        }

        def cb(_):
            try:
                self.load_messages()
            finally:
                self._sending = False

        self.start_request(data, cb)
        self.input_edit.clear()

    def closeEvent(self, event):
        self._alive = False
        self.stop_auto_update()
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)
