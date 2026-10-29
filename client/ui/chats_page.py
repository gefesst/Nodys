"""Private conversations: real data, scoped requests and shared Nodus components."""
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QListView, QFrame, QStackedWidget,QSizePolicy
from application.request_scope import RequestScope
from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel
from ui.design.tokens import LIST_WIDTH
from ui.design.widgets import Button, DialogDelegate, Toast, ElidedLabel, SearchField
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
        self._read_revision = 0
        self._read_pending = set()
        self._read_markers = {}
        self.unread_counts = {}
        self.dialog_summaries = {}
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
        left.setContentsMargins(12, 32, 12, 20)
        left.setSpacing(12)
        eyebrow = QLabel('ЛИЧНЫЕ')
        eyebrow.setObjectName('Eyebrow')
        eyebrow.setContentsMargins(10,0,10,0)
        left.addWidget(eyebrow)
        title = QLabel('Сообщения')
        title.setObjectName('PageTitle')
        title.setContentsMargins(10,0,10,0)
        left.addWidget(title)
        self.search = SearchField()
        self.search.setFixedHeight(40)
        self.search.setStyleSheet('QLineEdit {min-height:16px;max-height:16px;}')
        self.search.setPlaceholderText('Найти диалог')
        self.search.textChanged.connect(self.filter_friends)
        search_row=QHBoxLayout();search_row.setContentsMargins(10,2,10,0)
        search_row.addWidget(self.search);left.addLayout(search_row)
        left.addSpacing(5)
        self.dialog_model = DialogModel(self)
        self.dialogs = QListView()
        self.dialogs.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.dialogs.verticalScrollBar().setSingleStep(24)
        self.dialogs.setModel(self.dialog_model)
        self.dialogs.setItemDelegate(DialogDelegate(self.dialogs))
        self.dialogs.setUniformItemSizes(True)
        self.dialogs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.dialogs.setMouseTracking(True)
        self.dialogs.setResizeMode(QListView.Adjust)
        self.dialogs.setUniformItemSizes(True)
        self.dialogs.clicked.connect(lambda index: self.open_chat(index.data(Qt.UserRole)))
        self.dialogs.activated.connect(lambda index: self.open_chat(index.data(Qt.UserRole)))
        left.addWidget(self.dialogs, 1)
        self.list_status = QLabel('Загрузка диалогов…')
        self.list_status.setWordWrap(True)
        self.list_status.setObjectName('Muted')
        self.list_status.setStyleSheet('QLabel {font-size:11px;}')
        self.list_status.setContentsMargins(10,0,10,0)
        self.voice_dock_space=QWidget()
        self.voice_dock_space.setFixedHeight(170)
        self.voice_dock_space.hide()
        left.addWidget(self.list_status)
        left.addWidget(self.voice_dock_space)
        self.list_status.hide()
        root.addWidget(sidebar)
        self.workspace=QStackedWidget()
        root.addWidget(self.workspace,1)
        from ui.design.state_surfaces import EmptyState
        self.no_dialog=EmptyState("Выберите диалог","Все разговоры — здесь. Выберите человека слева.")
        self.no_dialog.layout().setContentsMargins(40,262,48,20)
        self.no_dialog.set_top_offset(262)
        self.workspace.addWidget(self.no_dialog)
        self.chat_body=QWidget()
        body = QVBoxLayout(self.chat_body)
        body.setContentsMargins(24, 22, 24, 24)
        body.setSpacing(14)
        header = QHBoxLayout()
        header.setSpacing(14)
        header.setContentsMargins(8, 0, 8, 0)
        self.avatar = AvatarLabel(size=40)
        header.addWidget(self.avatar)
        labels = QVBoxLayout()
        labels.setSpacing(6)
        self.chat_header = ElidedLabel('Выберите диалог')
        self.chat_header.setObjectName('ChatTitle')
        self.chat_header.setMinimumWidth(0)
        self.chat_header.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.presence = QLabel('')
        self.presence.setObjectName('Muted')
        labels.addWidget(self.chat_header)
        labels.addWidget(self.presence)
        header.addLayout(labels, 1)
        self.call_button = Button('Позвонить', 'phone')
        self.call_button.setFixedSize(140, 40)
        self.call_button.setToolTip('Позвонить')
        self.call_button.clicked.connect(self.call_friend)
        header.addWidget(self.call_button)
        self.info_button = Button("", "info")
        self.info_button.setProperty("flat", True)
        self.info_button.setFixedSize(32,40)
        self.info_button.setAccessibleName("Профиль собеседника")
        self.info_button.clicked.connect(self.show_peer_profile)
        header.addWidget(self.info_button)
        body.addLayout(header)
        body.addSpacing(9)
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
        self.workspace.addWidget(self.chat_body)
        self.workspace.setCurrentWidget(self.no_dialog)
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
        self._read_revision = 0
        self._read_pending = set()
        self._read_markers = {}
        self.unread_counts = {}
        self.dialog_summaries = {}
        self.unread_total = 0
        self.dialog_model.replace([])
        self.chat_header.setText('Выберите диалог')
        self.presence.clear()
        self.workspace.setCurrentWidget(self.no_dialog)

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
            self.list_status.show()
            return  # A transient failure must not remove the selected friend/draft.
        self._friends_received_at = time.monotonic()
        rows = sorted(response.get('friends', []), key=lambda r: r.get('nickname', r['login']).casefold())
        for row in rows:
            row['unread_count'] = self.unread_counts.get(row['login'], 0)
            row['summary'] = self.dialog_summaries.get(row['login'], {})
        # Presence changes must not reshuffle conversations while the user reads.
        rows.sort(key=lambda row: row['summary'].get('timestamp') or '', reverse=True)
        self.dialog_model.replace(rows)
        self.filter_friends(self.search.text())
        self.conversation.prefetch([row["login"] for row in sorted(rows,key=lambda r:bool(r.get("unread_count")),reverse=True)])
        if self.active_friend:
            found = next((r for r in rows if r['login'] == self.active_friend['login']), None)
            if found:
                self.active_friend = found
                self.update_header()
            else:
                self.active_friend = None
                self.conversation.select(None)
                self.chat_header.setText('Выберите диалог')
                self.workspace.setCurrentWidget(self.no_dialog)

    def filter_friends(self, text):
        self.dialog_model.filter(text)
        self.list_status.clear()
        self.list_status.hide()
        if self.active_friend and not self.dialogs.currentIndex().isValid():
            for i, row in enumerate(self.dialog_model.rows):
                if row['login'] == self.active_friend['login']:
                    self.dialogs.setCurrentIndex(self.dialog_model.index(i))
                    break

    def update_header(self):
        friend = self.active_friend
        name=friend.get('nickname',friend['login'])
        self.chat_header.setText(name)
        self.conversation.name=name
        self.avatar.set_avatar(friend.get('avatar', ''), friend['login'], friend.get('nickname', ''))
        self.avatar.set_online(friend.get('online', False))
        self.presence.setText('В сети' if friend.get('online') else 'Не в сети')
        self.presence.setStyleSheet("color:#67D5AD;" if friend.get("online") else "color:#ACB9CC;")

    def open_chat(self, friend):
        if not friend or not friend.get('login'):
            return
        if self.active_friend and self.active_friend['login'] == friend['login']:
            return
        self.active_friend = friend
        self.workspace.setCurrentWidget(self.chat_body)
        self.update_header()
        self.conversation.select(friend['login'], friend.get('nickname', friend['login']))
        if self.conversation.history_loaded:
            self.mark_chat_read(friend['login'])
        self.filter_friends(self.search.text())
        for i, row in enumerate(self.dialog_model.rows):
            if row['login'] == friend['login']:
                self.dialogs.setCurrentIndex(self.dialog_model.index(i))
                break

    def load_messages(self, force=False):
        if force or self._is_poll_allowed():
            self.conversation.load('poll')

    def send_message(self):
        self.conversation.send()

    def message_sent(self, peer, text, timestamp):
        # Fence a summary poll that started before the confirmed write.
        self._read_revision += 1
        self.dialog_summaries[peer] = dict(text=text[:160],timestamp=timestamp,outgoing=True)
        self.refresh_dialog_summaries()

    def refresh_dialog_summaries(self):
        rows=[dict(row,summary=self.dialog_summaries.get(row['login'],{}),
                   unread_count=self.unread_counts.get(row['login'],0))
              for row in self.dialog_model.all_rows]
        rows.sort(key=lambda row:row['summary'].get('timestamp') or '',reverse=True)
        self.dialog_model.replace(rows)
        self.filter_friends(self.search.text())

    def load_unread_counts(self, force=False):
        if self._loading_unread or not self.ctx.login or not self._alive:
            return
        if not force and not self._is_poll_allowed():
            return
        self._loading_unread = True
        ticket = self.scope.capture('unread', self.ctx.login)
        read_revision=self._read_revision
        def done(response):
            if not self.scope.accepts(ticket, self.ctx.login):
                return
            self._loading_unread = False
            if read_revision!=self._read_revision:
                self.load_unread_counts(force=True)
                return
            if response.get('status') == 'ok':
                self.unread_counts = dict(response.get('counts', {}))
                for peer in self._read_pending:self.unread_counts.pop(peer,None)
                summaries=response.get('summaries', {})
                for peer,summary in summaries.items():
                    if summary!=self.dialog_summaries.get(peer):
                        self.conversation.prefetched.pop(peer,None)
                self.dialog_summaries = summaries
                self.refresh_dialog_summaries()
                self.unread_total = sum(self.unread_counts.values())
                if self.on_unread_total_changed:
                    self.on_unread_total_changed(self.unread_total)
            self.load_friends(force=force)
        self.start_request(dict(action='get_unread_counts'), done)

    def mark_chat_read(self, friend_login=None):
        peer = friend_login or (self.active_friend or {}).get('login')
        if not peer or peer in self._read_pending:return
        last=max((row['id'] for row in self.conversation.rows if row['from_user']==peer),default=0)
        if not last or (self._read_markers.get(peer)==last and not self.unread_counts.get(peer)):return
        self._read_markers[peer]=last
        self._read_pending.add(peer)
        self._read_revision+=1
        self.unread_counts.pop(peer,None)
        self.unread_total=sum(self.unread_counts.values())
        if self.on_unread_total_changed:self.on_unread_total_changed(self.unread_total)
        rows=[dict(row,unread_count=self.unread_counts.get(row['login'],0)) for row in self.dialog_model.all_rows]
        self.dialog_model.replace(rows)
        epoch=self.scope.epoch
        def done(response):
            if epoch!=self.scope.epoch:return
            self._read_pending.discard(peer)
            self._read_revision+=1
            if response.get('status')!='ok':self._read_markers.pop(peer,None)
            self.load_unread_counts(force=True)
        self.start_request(dict(action='mark_chat_read',friend_login=peer,through_id=last),done)

    def show_peer_profile(self):
        if self.active_friend and self.host:
            self.host.friends_page.show_mini_profile(self.active_friend["login"])

    def call_friend(self):
        if self.active_friend and self.host:
            self.host.start_outgoing_call(self.active_friend['login'])

    def closeEvent(self, event):
        self._alive = False
        self.scope.invalidate()
        self.stop_auto_update()
        self.shutdown_requests()
        super().closeEvent(event)
