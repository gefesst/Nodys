import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QLineEdit, QPushButton, QSizePolicy
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QThread, Signal
from network import NetworkThread
from user_context import UserContext
import time

# -------------------- Friend Item --------------------
class ChatFriendItem(QFrame):
    def __init__(self, nickname, avatar_path="", on_click=None):
        super().__init__()
        self.setFixedHeight(56)
        self.setStyleSheet("""
            QFrame { background-color:#2f3136; border-radius:8px; }
            QFrame:hover { background-color:#3a3d42; }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        avatar = QLabel()
        avatar.setFixedSize(40, 40)
        avatar.setStyleSheet("background-color:#202225; border-radius:20px;")
        pix_loaded = False

        if avatar_path and os.path.exists(avatar_path):
            pix = QPixmap(avatar_path)
            pix_loaded = True
        else:
            for ext in (".png", ".jpg", ".jpeg"):
                path = os.path.join("avatars", f"{nickname}{ext}")
                if os.path.exists(path):
                    pix = QPixmap(path)
                    pix_loaded = True
                    break
        if pix_loaded:
            avatar.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(avatar)

        name = QLabel(nickname)
        name.setStyleSheet("color:white; font-weight:500;")
        layout.addWidget(name)
        layout.addStretch()

        if on_click:
            self.mousePressEvent = lambda event: on_click()

# -------------------- Message Bubble --------------------
class MessageBubble(QFrame):
    def __init__(self, text, is_outgoing=False):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)

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
            layout.addStretch()
            layout.addWidget(label)
        else:
            layout.addWidget(label)
            layout.addStretch()

# -------------------- Auto-refresh Thread --------------------
class AutoMessageThread(QThread):
    new_messages = Signal(dict)

    def __init__(self, from_user, to_user):
        super().__init__()
        self.from_user = from_user
        self.to_user = to_user
        self.running = True

    def run(self):
        while self.running:
            data = {"action":"get_messages","from_user":self.from_user,"to_user":self.to_user}
            thread = NetworkThread("127.0.0.1", 5555, data)
            thread.finished.connect(lambda resp: self.new_messages.emit(resp))
            thread.run()  # синхронный вызов внутри потока
            time.sleep(2)

    def stop(self):
        self.running = False

# -------------------- Chats Page --------------------
class ChatsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = UserContext()
        self.active_friend = None
        self.auto_thread = None
        self.send_thread = None

        root = QHBoxLayout(self)
        root.setContentsMargins(10,10,10,10)
        root.setSpacing(15)

        # Список друзей
        self.friends_container = QWidget()
        self.friends_layout = QVBoxLayout(self.friends_container)
        self.friends_layout.setSpacing(6)
        self.friends_layout.addStretch()

        self.friends_scroll = QScrollArea()
        self.friends_scroll.setWidgetResizable(True)
        self.friends_scroll.setWidget(self.friends_container)
        self.friends_scroll.setStyleSheet("border:none;")

        root.addWidget(self.friends_scroll, 1)

        # Окно чата
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0,0,0,0)
        self.chat_layout.setSpacing(5)

        self.chat_header = QLabel("Выберите друга")
        self.chat_header.setStyleSheet("font-weight:bold; color:white; font-size:16px;")
        self.chat_layout.addWidget(self.chat_header)

        # Сообщения
        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.addStretch()

        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setWidget(self.messages_container)
        self.messages_scroll.setStyleSheet("border:none; background-color:#36393f;")
        self.chat_layout.addWidget(self.messages_scroll)

        # Ввод сообщений
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Введите сообщение...")
        self.input_edit.setStyleSheet("""
            QLineEdit { background-color:#202225; color:white; border-radius:6px; padding:6px; }
        """)
        input_layout.addWidget(self.input_edit)

        self.send_btn = QPushButton("Отправить")
        self.send_btn.setStyleSheet("""
            QPushButton { background-color:#5865F2; color:white; border-radius:6px; padding:6px 10px; }
            QPushButton:hover { background-color:#4752c4; }
        """)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)
        self.chat_layout.addLayout(input_layout)

        root.addWidget(self.chat_container, 3)
        self.setStyleSheet("background-color:#36393f; color:white;")

        self.load_friends()

    # ------------------ Друзья ------------------
    def load_friends(self):
        data = {"action":"get_friends","login":self.ctx.login}
        self.thread = NetworkThread("127.0.0.1",5555,data)
        self.thread.finished.connect(self.handle_friends)
        self.thread.start()

    def handle_friends(self, resp):
        if resp.get("status") != "ok":
            return
        # очищаем список
        for i in reversed(range(self.friends_layout.count()-1)):
            item = self.friends_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        for friend in resp.get("friends", []):
            avatar_path = friend.get("avatar","")
            item = ChatFriendItem(friend["nickname"], avatar_path, lambda f=friend: self.open_chat(f))
            self.friends_layout.insertWidget(self.friends_layout.count()-1, item)

    # ------------------ Открыть чат ------------------
    def open_chat(self, friend):
        self.active_friend = friend
        self.chat_header.setText(friend["nickname"])
        self.load_messages()

        # Запуск одного автообновляющегося потока
        if self.auto_thread:
            self.auto_thread.stop()
            self.auto_thread.wait()
        self.auto_thread = AutoMessageThread(self.ctx.login, friend["login"])
        self.auto_thread.new_messages.connect(self.display_messages)
        self.auto_thread.start()

    # ------------------ Загрузка сообщений ------------------
    def load_messages(self):
        if not self.active_friend:
            return
        data = {"action":"get_messages","from_user":self.ctx.login,"to_user":self.active_friend["login"]}
        self.msg_thread = NetworkThread("127.0.0.1",5555,data)
        self.msg_thread.finished.connect(self.display_messages)
        self.msg_thread.start()

    # ------------------ Отображение сообщений ------------------
    def display_messages(self, resp):
        if resp.get("status") != "ok":
            return
        messages = resp.get("messages", [])
        # очищаем старые сообщения
        for i in reversed(range(self.messages_layout.count()-1)):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        for msg in messages:
            is_outgoing = msg.get("from_user") == self.ctx.login
            bubble = MessageBubble(msg["text"], is_outgoing)
            self.messages_layout.insertWidget(self.messages_layout.count()-1, bubble)
        # автоскролл вниз
        self.messages_scroll.verticalScrollBar().setValue(
            self.messages_scroll.verticalScrollBar().maximum()
        )

    # ------------------ Отправка сообщения ------------------
    def send_message(self):
        if not self.active_friend:
            return
        text = self.input_edit.text().strip()
        if not text:
            return
        data = {"action":"send_message","from_user":self.ctx.login,
                "to_user":self.active_friend["login"],"message":text}
        self.send_thread = NetworkThread("127.0.0.1",5555,data)
        self.send_thread.finished.connect(lambda resp: self.load_messages())
        self.send_thread.start()
        self.input_edit.clear()
