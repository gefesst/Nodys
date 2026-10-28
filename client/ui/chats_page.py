"""Private conversations: real data, scoped requests and shared Nodus components."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QListView, QFrame
from application.request_scope import RequestScope
from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel
from ui.design.tokens import LIST_WIDTH
from ui.design.widgets import Button, DialogDelegate, Toast
from ui.design.models import DialogModel
from ui.design.conversation import Conversation


class ChatsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.host = parent
        self.ctx = UserContext()
        self._alive = True
        self._threads = []
        self.scope = RequestScope()
        self.active_friend = None
        self._loading_friends = self._loading_unread = False
        self.unread_counts = {}
        self.unread_total = 0
        self.on_unread_total_changed = None
        self.setObjectName('ChatsPage')
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('SectionSidebar')
        sidebar.setFixedWidth(LIST_WIDTH)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(22, 32, 20, 20)
        left.setSpacing(12)
        eyebrow = QLabel('ЛИЧНЫЕ')
        eyebrow.setObjectName('Eyebrow')
        left.addWidget(eyebrow)
        title = QLabel('Сообщения')
        title.setObjectName('PageTitle')
        left.addWidget(title)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти диалог')
        self.search.textChanged.connect(self.filter_friends)
        left.addWidget(self.search)
        self.dialog_model = DialogModel(self)
        self.dialogs = QListView()
        self.dialogs.setModel(self.dialog_model)
        self.dialogs.setItemDelegate(DialogDelegate(self.dialogs))
        self.dialogs.setUniformItemSizes(True)
        self.dialogs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.dialogs.setMouseTracking(True)
        self.dialogs.clicked.connect(lambda index: self.open_chat(index.data(Qt.UserRole)))
        self.dialogs.activated.connect(lambda index: self.open_chat(index.data(Qt.UserRole)))
        left.addWidget(self.dialogs, 1)
        self.list_status = QLabel('Загрузка диалогов…')
        self.list_status.setWordWrap(True)
        self.list_status.setObjectName('Muted')
        left.addWidget(self.list_status)
        root.addWidget(sidebar)
        body = QVBoxLayout()
        body.setContentsMargins(24, 24, 24, 14)
        body.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(14)
        header.setContentsMargins(8, 0, 8, 0)
        self.avatar = AvatarLabel(size=40)
        header.addWidget(self.avatar)
        labels = QVBoxLayout()
        labels.setSpacing(6)
        self.chat_header = QLabel('Выберите диалог')
        self.chat_header.setObjectName('ChatTitle')
        self.chat_header.setMinimumWidth(0)
        self.presence = QLabel('')
        self.presence.setObjectName('Muted')
        labels.addWidget(self.chat_header)
        labels.addWidget(self.presence)
        header.addLayout(labels, 1)
        self.call_button = Button('Позвонить', 'phone')
        self.call_button.setFixedSize(148, 46)
        self.call_button.setToolTip('Позвонить')
        self.call_button.clicked.connect(self.call_friend)
        header.addWidget(self.call_button)
        body.addLayout(header)
        line = QFrame()
        line.setObjectName('Divider')
        line.setFixedHeight(1)
        body.addWidget(line)
        self.conversation = Conversation(self)
        self.conversation.notice.connect(self.notify)
        self.conversation.read_latest.connect(self.mark_chat_read)
        body.addWidget(self.conversation, 1)
        self.input_edit = self.conversation.editor
        self.send_btn = self.conversation.send_button
        root.addLayout(body, 1)
        self.toast = Toast(self)
        self.msg_timer = QTimer(self)
        self.msg_timer.setInterval(2000)
        self.msg_timer.timeout.connect(self.load_messages)
        self.friends_timer = QTimer(self)
        self.friends_timer.setInterval(3000)
        self.friends_timer.timeout.connect(self.load_unread_counts)

    def notify(self, message):
        self.toast.show_message(message)

    def _is_poll_allowed(self):
        return self._alive and bool(self.ctx.login) and self.isVisible() and not self.window().isMinimized()

    def start_auto_update(self, force_refresh=False):
        if not self._alive:
            return
        self.msg_timer.start()
        self.friends_timer.start()
        self.load_unread_counts(force=True)
        self.load_friends(force=True)
        self.load_messages(force=True)

    def stop_auto_update(self):
        self.msg_timer.stop()
        self.friends_timer.stop()

    def reset_for_user(self):
        self.stop_auto_update()
        self.scope.invalidate()
        self.conversation.reset()
        self.active_friend = None
        self._loading_friends = self._loading_unread = False
        self.unread_counts = {}
        self.unread_total = 0
        self.dialog_model.replace([])
        self.chat_header.setText('Выберите диалог')
        self.presence.clear()

    def load_friends(self, force=False):
        if self._loading_friends or not self.ctx.login or not self._alive:
            return
        if not force and not self._is_poll_allowed():
            return
        self._loading_friends = True
        ticket = self.scope.capture('friends', self.ctx.login)
        def done(response):
            if not self.scope.accepts(ticket, self.ctx.login):
                return
            self._loading_friends = False
            self.handle_friends(response)
        self.start_request(dict(action='get_friends'), done)

    def handle_friends(self, response):
        if response.get('status') != 'ok':
            self.list_status.setText(response.get('message', 'Не удалось загрузить диалоги'))
            return  # A transient failure must not remove the selected friend/draft.
        rows = sorted(response.get('friends', []), key=lambda r: (not r.get('online'), r.get('nickname', '').casefold()))
        for row in rows:
            row['unread_count'] = self.unread_counts.get(row['login'], 0)
        self.dialog_model.replace(rows)
        self.filter_friends(self.search.text())
        self.list_status.setText('Добавьте друзей, чтобы начать общение' if not rows else '')
        if self.active_friend:
            found = next((r for r in rows if r['login'] == self.active_friend['login']), None)
            if found:
                self.active_friend = found
                self.update_header()
            else:
                self.active_friend = None
                self.conversation.select(None)
                self.chat_header.setText('Выберите диалог')

    def filter_friends(self, text):
        self.dialog_model.filter(text)
        if self.active_friend:
            for i, row in enumerate(self.dialog_model.rows):
                if row['login'] == self.active_friend['login']:
                    self.dialogs.setCurrentIndex(self.dialog_model.index(i))
                    break

    def update_header(self):
        friend = self.active_friend
        self.chat_header.setText(friend.get('nickname', friend['login']))
        self.avatar.set_avatar(friend.get('avatar', ''), friend['login'], friend.get('nickname', ''))
        self.avatar.set_online(friend.get('online', False))
        self.presence.setText('В сети' if friend.get('online') else 'Не в сети')

    def open_chat(self, friend):
        if not friend or not friend.get('login'):
            return
        if self.active_friend and self.active_friend['login'] == friend['login']:
            return
        self.active_friend = friend
        self.update_header()
        self.conversation.select(friend['login'], friend.get('nickname', friend['login']))
        self.filter_friends(self.search.text())

    def load_messages(self, force=False):
        if force or self._is_poll_allowed():
            self.conversation.load('poll')

    def send_message(self):
        self.conversation.send()

    def load_unread_counts(self, force=False):
        if self._loading_unread or not self.ctx.login or not self._alive:
            return
        if not force and not self._is_poll_allowed():
            return
        self._loading_unread = True
        ticket = self.scope.capture('unread', self.ctx.login)
        def done(response):
            if not self.scope.accepts(ticket, self.ctx.login):
                return
            self._loading_unread = False
            if response.get('status') == 'ok':
                self.unread_counts = response.get('counts', {})
                self.unread_total = int(response.get('total', 0))
                if self.on_unread_total_changed:
                    self.on_unread_total_changed(self.unread_total)
            self.load_friends(force=force)
        self.start_request(dict(action='get_unread_counts'), done)

    def mark_chat_read(self, friend_login=None):
        peer = friend_login or (self.active_friend or {}).get('login')
        if peer:
            self.start_request(dict(action='mark_chat_read', friend_login=peer), lambda _: None)

    def call_friend(self):
        if self.active_friend and self.host:
            self.host.start_outgoing_call(self.active_friend['login'])

    def closeEvent(self, event):
        self._alive = False
        self.scope.invalidate()
        self.stop_auto_update()
        self.shutdown_requests()
        super().closeEvent(event)
