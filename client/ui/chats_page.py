from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QLineEdit, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer

from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel


class ChatFriendItem(QFrame):
    def __init__(
        self,
        login,
        nickname,
        avatar_path="",
        on_click=None,
        is_active=False,
        online=False,
        unread_count=0
    ):
        super().__init__()

        self.setFixedHeight(64)
        self.setObjectName("ChatFriendItem")
        self.setProperty("active", is_active)

        self.setStyleSheet("""
            QFrame#ChatFriendItem {
                background-color:#2f3136;
                border:none;
                border-radius:10px;
            }
            QFrame#ChatFriendItem[active="true"] {
                background-color:#3a3d42;
            }
            QFrame#ChatFriendItem:hover {
                background-color:#3a3d42;
            }
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Левая полоска выбранного элемента
        self.active_bar = QFrame()
        self.active_bar.setFixedWidth(4)
        self.active_bar.setStyleSheet(
            "background-color:#5865F2; border-top-left-radius:10px; border-bottom-left-radius:10px;"
            if is_active else
            "background-color:transparent; border:none;"
        )
        root.addWidget(self.active_bar)

        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)

        # Круглый аватар + online dot
        avatar = AvatarLabel(size=44)
        avatar.set_avatar(path=avatar_path, login=login, nickname=nickname)
        avatar.set_online(online, ring_color="#2f3136")
        row.addWidget(avatar)

        # Текст
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        name = QLabel(nickname)
        name.setStyleSheet("color:white; font-size:14px; font-weight:600; border:none;")
        text_col.addWidget(name)

        sub = QLabel("в сети" if online else "не в сети")
        sub.setStyleSheet("color:#b9bbbe; font-size:11px; border:none;")
        text_col.addWidget(sub)

        row.addLayout(text_col, 1)
        row.addStretch()

        # badge непрочитанных
        if unread_count > 0:
            badge = QLabel(str(unread_count))
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet("""
                QLabel {
                    background-color:#f04747;
                    color:white;
                    border:none;
                    border-radius:10px;
                    min-width:20px;
                    padding:2px 6px;
                    font-size:11px;
                    font-weight:700;
                }
            """)
            row.addWidget(badge, alignment=Qt.AlignVCenter)

        root.addWidget(content, 1)

        if on_click:
            self.mousePressEvent = lambda event: on_click()
            content.mousePressEvent = lambda event: on_click()


class MessageBubble(QFrame):
    def __init__(self, text, is_outgoing=False, time_text="", status_text=""):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        container = QVBoxLayout()
        container.setSpacing(2)

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

        meta_layout = QHBoxLayout()
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(6)

        time_label = QLabel(time_text)
        time_label.setStyleSheet("color:#b9bbbe; font-size:10px;")

        status_label = QLabel(status_text)
        status_label.setStyleSheet("color:#b9bbbe; font-size:10px;")

        if is_outgoing:
            meta_layout.addStretch()
            meta_layout.addWidget(time_label)
            if status_text:
                meta_layout.addWidget(status_label)
        else:
            meta_layout.addWidget(time_label)
            meta_layout.addStretch()

        meta_widget = QWidget()
        meta_widget.setLayout(meta_layout)

        container.addWidget(label)
        container.addWidget(meta_widget)

        wrapper = QWidget()
        wrapper.setLayout(container)

        if is_outgoing:
            lay.addStretch()
            lay.addWidget(wrapper)
        else:
            lay.addWidget(wrapper)
            lay.addStretch()


class ChatsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = UserContext()

        # Для ThreadSafeMixin
        self._threads = []
        self._alive = True

        # Состояние
        self.active_friend = None
        self._loading_friends = False
        self._loading_messages = False
        self._sending = False
        self._loading_unread = False

        self.unread_counts = {}
        self.unread_total = 0
        self.on_unread_total_changed = None

        # UI
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(15)

        # Левая панель друзей
        self.friends_container = QWidget()
        self.friends_layout = QVBoxLayout(self.friends_container)
        self.friends_layout.setSpacing(6)
        self.friends_layout.addStretch()

        self.friends_scroll = QScrollArea()
        self.friends_scroll.setWidgetResizable(True)
        self.friends_scroll.setWidget(self.friends_container)
        self.friends_scroll.setStyleSheet("border:none;")
        root.addWidget(self.friends_scroll, 1)

        # Правая панель чата
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
        self.input_edit.returnPressed.connect(self.send_message)
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

        # Таймеры
        self.msg_timer = QTimer(self)
        self.msg_timer.setInterval(2000)
        self.msg_timer.timeout.connect(self.load_messages)

        self.friends_timer = QTimer(self)
        self.friends_timer.setInterval(3000)
        self.friends_timer.timeout.connect(self._friends_tick)

    # ==================================================
    # ================= Lifecycle ======================
    # ==================================================

    def start_auto_update(self):
        if not self._alive:
            return

        if not self.friends_timer.isActive():
            self.friends_timer.start()

        if self.active_friend and not self.msg_timer.isActive():
            self.msg_timer.start()

        self.load_unread_counts()

    def stop_auto_update(self):
        if self.msg_timer.isActive():
            self.msg_timer.stop()
        if self.friends_timer.isActive():
            self.friends_timer.stop()

    def reset_for_user(self):
        """
        Полный сброс состояния при перелогине/смене пользователя.
        """
        self.stop_auto_update()

        self.active_friend = None
        self._loading_friends = False
        self._loading_messages = False
        self._sending = False
        self._loading_unread = False

        self.unread_counts = {}
        self.unread_total = 0

        self.chat_header.setText("Выберите друга")
        self.input_edit.clear()

        self._clear_friends()
        self._clear_messages()

    def closeEvent(self, event):
        self._alive = False
        self.stop_auto_update()
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)

    # ==================================================
    # ================= Helpers ========================
    # ==================================================

    def _friends_tick(self):
        self.load_unread_counts()

    def _clear_friends(self):
        for i in reversed(range(self.friends_layout.count() - 1)):
            item = self.friends_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_section_header(self, text: str):
        header = QLabel(text)
        header.setStyleSheet("""
            QLabel {
                color:#b9bbbe;
                font-size:11px;
                font-weight:700;
                text-transform: uppercase;
                padding:6px 4px 2px 4px;
            }
        """)
        self.friends_layout.insertWidget(self.friends_layout.count() - 1, header)

    def _clear_messages(self):
        for i in reversed(range(self.messages_layout.count() - 1)):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    @staticmethod
    def _format_time(dt_str: str) -> str:
        if not dt_str:
            return ""
        try:
            return dt_str[11:16]
        except Exception:
            return ""

    # ==================================================
    # ================= Unread =========================
    # ==================================================

    def load_unread_counts(self):
        if not self._alive or self._loading_unread or not self.ctx.login:
            return

        self._loading_unread = True
        data = {"action": "get_unread_counts", "login": self.ctx.login}

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    return

                self.unread_counts = resp.get("counts", {}) or {}
                self.unread_total = int(resp.get("total", 0) or 0)

                if callable(self.on_unread_total_changed):
                    self.on_unread_total_changed(self.unread_total)

                self.load_friends()
            finally:
                self._loading_unread = False

        self.start_request(data, cb)

    def mark_chat_read(self, friend_login: str):
        if not self.ctx.login:
            return

        data = {
            "action": "mark_chat_read",
            "login": self.ctx.login,
            "friend_login": friend_login
        }

        def cb(_resp):
            self.load_unread_counts()

        self.start_request(data, cb)

    # ==================================================
    # ================= Friends list ===================
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
        if resp.get("status") != "ok":
            return

        friends = resp.get("friends", [])
        current_login = self.active_friend["login"] if self.active_friend else None

        self._clear_friends()

        # Если активный собеседник ещё существует, обновим его данные
        if current_login:
            found = next((f for f in friends if f["login"] == current_login), None)
            if found:
                self.active_friend = found
                self.chat_header.setText(found["nickname"])
            else:
                # собеседник исчез из списка (например, удалили дружбу)
                self.active_friend = None
                self.chat_header.setText("Выберите друга")
                self._clear_messages()
                if self.msg_timer.isActive():
                    self.msg_timer.stop()

        def sort_key(f):
            return (0 if f.get("online", False) else 1, f.get("nickname", "").lower())

        friends_sorted = sorted(friends, key=sort_key)
        online_friends = [f for f in friends_sorted if f.get("online", False)]
        offline_friends = [f for f in friends_sorted if not f.get("online", False)]

        if online_friends:
            self._add_section_header(f"В сети — {len(online_friends)}")
            for friend in online_friends:
                count = int(self.unread_counts.get(friend["login"], 0))
                item = ChatFriendItem(
                    login=friend["login"],
                    nickname=friend["nickname"],
                    avatar_path=friend.get("avatar", ""),
                    online=True,
                    is_active=(friend["login"] == current_login),
                    unread_count=count,
                    on_click=lambda f=friend: self.open_chat(f)
                )
                self.friends_layout.insertWidget(self.friends_layout.count() - 1, item)

        if offline_friends:
            self._add_section_header(f"Не в сети — {len(offline_friends)}")
            for friend in offline_friends:
                count = int(self.unread_counts.get(friend["login"], 0))
                item = ChatFriendItem(
                    login=friend["login"],
                    nickname=friend["nickname"],
                    avatar_path=friend.get("avatar", ""),
                    online=False,
                    is_active=(friend["login"] == current_login),
                    unread_count=count,
                    on_click=lambda f=friend: self.open_chat(f)
                )
                self.friends_layout.insertWidget(self.friends_layout.count() - 1, item)

        if not friends:
            empty = QLabel("У тебя пока нет друзей для чата")
            empty.setStyleSheet("color:#b9bbbe; padding:8px;")
            self.friends_layout.insertWidget(self.friends_layout.count() - 1, empty)

    # ==================================================
    # ================= Chat logic =====================
    # ==================================================

    def open_chat(self, friend):
        if not friend or not friend.get("login"):
            return

        self.active_friend = friend
        self.chat_header.setText(friend.get("nickname", friend["login"]))

        self.mark_chat_read(friend["login"])
        self.load_friends()   # чтобы сразу убрать badge у активного
        self.load_messages()

        if not self.msg_timer.isActive():
            self.msg_timer.start()

    def load_messages(self):
        if (
            not self._alive
            or not self.ctx.login
            or not self.active_friend
            or self._loading_messages
        ):
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
            time_text = self._format_time(msg.get("created_at", ""))

            status_text = ""
            if is_outgoing:
                status_text = "✓✓" if bool(msg.get("is_read", False)) else "✓"

            bubble = MessageBubble(
                text=text,
                is_outgoing=is_outgoing,
                time_text=time_text,
                status_text=status_text
            )
            self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)

        sb = self.messages_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send_message(self):
        if (
            not self._alive
            or not self.ctx.login
            or not self.active_friend
            or self._sending
        ):
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

        def cb(_resp):
            try:
                self.load_messages()
                self.load_unread_counts()
            finally:
                self._sending = False

        self.start_request(data, cb)
        self.input_edit.clear()
