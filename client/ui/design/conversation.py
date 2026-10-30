"""Bounded real-message view with keyset history, scoped replies and safe drafts."""

from datetime import datetime, timedelta
import uuid
from collections import OrderedDict
from copy import deepcopy
from PySide6.QtCore import Qt, QTimer, QPoint, Signal, QEvent
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QApplication,
    QAbstractItemView,
    QStackedWidget,
    QFileDialog,
)
from application.request_scope import RequestScope
from .models import Message, MessageModel
from .state_surfaces import EmptyState, LoadingState, InlineNote
from .widgets import MessageList, MessageDelegate, Composer, Button


class Conversation(QWidget):
    notice = Signal(str)
    read_latest = Signal()
    WINDOW = 240
    PAGE = 80

    def __init__(self, owner, channel=False):
        super().__init__(owner)
        self.owner = owner
        self.channel = channel
        self.identity = None
        self.name = ""
        self.scope = RequestScope()
        self.unread_boundary = None
        self.unread_count = 0
        self.unseen_new = 0
        self.unread_initialized = False
        self.rows = []
        self.history_cache = OrderedDict()
        self.prefetched = OrderedDict()
        self.prefetch_pending = set()
        self.prefetch_queue = []
        self.loading = False
        self.history_loaded = False
        self.history_error = False
        self.older = self.newer = False
        self.at_latest = True
        self.drafts = {}
        self.attachment_drafts = {}
        self.transfers = set()
        self.download_transfer = None
        self.draft_versions = {}
        self._restoring = False
        self.pending = {}
        self.retries = {}
        self.epoch = 0
        self._applying = False
        self.can_send = True
        self.is_channel = channel
        self.permission_text = "Писать в этом канале могут модераторы и администраторы."
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        history = QHBoxLayout()
        self.previous = Button("Раньше", "back")
        self.previous.clicked.connect(lambda: self.load("older"))
        history.addWidget(self.previous)
        self.hint = QLabel("Выберите диалог")
        self.hint.setObjectName("ChannelTextEmptyHint" if channel else "Muted")
        history.addWidget(self.hint, 1)
        self.latest = Button("К новым сообщениям", "arrowdown")
        self.latest.clicked.connect(lambda: self.load("latest"))
        history.addWidget(self.latest)
        root.addLayout(history)
        self.model = MessageModel(self)
        self.view = MessageList()
        self.view.setModel(self.model)
        self.delegate = MessageDelegate(
            self.view, owner.ctx.login, lambda: owner.ctx.nickname or owner.ctx.login
        )
        self.view.setItemDelegate(self.delegate)
        from .image_preview import ImageCache
        self.image_cache = ImageCache(self)
        self.delegate.image_cache = self.image_cache
        self.image_cache.changed.connect(self.image_ready)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setSelectionMode(QAbstractItemView.NoSelection)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.context_menu)
        self.view.verticalScrollBar().valueChanged.connect(self.scrolled)
        self.new_messages_button=Button('Новые сообщения','arrowdown',parent=self.view.viewport())
        self.new_messages_button.setFixedSize(240,40)
        self.new_messages_button.clicked.connect(lambda:self.load('latest'))
        self.new_messages_button.hide()
        self.view.viewport().installEventFilter(self)
        self.history_stack = QStackedWidget()
        self.history_stack.addWidget(self.view)
        self.empty_state = EmptyState('Здесь начинается разговор' if channel else 'Начните разговор',
            'Напишите первое сообщение в канале.' if channel else 'Напишите собеседнику — он увидит сообщение здесь.')
        self.loading_state = LoadingState()
        self.error_state = EmptyState('История пока недоступна' if channel else 'Не удалось загрузить сообщения',
            'Не удалось загрузить сообщения канала.' if channel else 'Проверьте соединение и попробуйте ещё раз.',
            'Повторить', lambda: self.load('latest'))
        if not channel:
            for surface in (self.empty_state,self.error_state):
                surface.set_top_offset(158)
        for surface in (self.empty_state, self.loading_state, self.error_state):
            self.history_stack.addWidget(surface)
        root.addWidget(self.history_stack, 1)
        self.connection_restored=QLabel('Соединение восстановлено')
        self.connection_restored.setStyleSheet('background:#203D3B;color:#67D5AD;border:1px solid #395D59;border-radius:10px;font-size:13px;padding:0 16px;')
        self.connection_restored.setFixedSize(270,40)
        self.connection_restored.hide()
        root.insertWidget(0,self.connection_restored,0,Qt.AlignHCenter)
        self.recovery_timer=QTimer(self);self.recovery_timer.setSingleShot(True)
        self.recovery_timer.timeout.connect(self.connection_restored.hide)
        self.offline_note=InlineNote()
        self.offline_note.set_tone('error')
        root.addWidget(self.offline_note)
        self.permission_note = InlineNote()
        root.addWidget(self.permission_note)
        self.send_error = InlineNote()
        self.send_error.set_tone("error")
        root.addWidget(self.send_error)
        self.download_strip = QWidget()
        download_layout = QHBoxLayout(self.download_strip)
        download_layout.setContentsMargins(0, 0, 0, 0)
        self.download_label = QLabel()
        download_layout.addWidget(self.download_label, 1)
        cancel_download = Button('Отменить')
        cancel_download.clicked.connect(self.cancel_download)
        download_layout.addWidget(cancel_download)
        root.addWidget(self.download_strip)
        self.download_strip.hide()
        self.attachment_strip = QFrame()
        self.attachment_strip.setObjectName('AttachmentDraft')
        self.attachment_strip.setStyleSheet('QFrame#AttachmentDraft {background:#383A40;border:1px solid #41434A;border-radius:10px;}')
        attachment_layout = QHBoxLayout(self.attachment_strip)
        attachment_layout.setContentsMargins(12, 8, 8, 8)
        self.attachment_label = QLabel()
        self.attachment_label.setWordWrap(True)
        self.attachment_preview = QLabel()
        self.attachment_preview.setFixedSize(44, 44)
        self.attachment_preview.hide()
        attachment_layout.addWidget(self.attachment_preview)
        attachment_layout.addWidget(self.attachment_label, 1)
        self.remove_attachment_button = Button('', 'close')
        self.remove_attachment_button.setAccessibleName('Убрать вложение')
        self.remove_attachment_button.setFixedSize(30, 30)
        self.remove_attachment_button.clicked.connect(self.remove_attachment)
        attachment_layout.addWidget(self.remove_attachment_button)
        root.addWidget(self.attachment_strip)
        self.attachment_strip.hide()
        compose_frame = QFrame()
        self.compose_frame = compose_frame
        compose_frame.setObjectName("ComposerFrame")
        compose = QHBoxLayout(compose_frame)
        compose.setContentsMargins(12, 4, 12, 4)
        compose.setSpacing(8)
        self.editor = Composer()
        self.editor.setObjectName("MessageComposer")
        self.editor.setAccessibleName("Текст сообщения")
        self.editor.submit.connect(self.send)
        self.editor.attachment_input.connect(self.accept_attachment_input)
        self.editor.textChanged.connect(self.edited)
        self.send_button = Button("", "send", True)
        self.send_button.setAccessibleName("Отправить сообщение")
        self.send_button.setFocusPolicy(Qt.NoFocus)
        self.send_button.setFixedSize(38, 38)
        self.send_button.clicked.connect(self.send)
        self.attach_button = Button('', 'attach')
        self.attach_button.setAccessibleName('Прикрепить файл')
        self.attach_button.setFocusPolicy(Qt.NoFocus)
        self.attach_button.setFixedSize(38, 38)
        self.attach_button.clicked.connect(self.choose_attachment)
        compose.addWidget(self.attach_button, 0, Qt.AlignVCenter)
        compose.addWidget(self.editor, 1)
        compose.addWidget(self.send_button, 0, Qt.AlignVCenter)
        root.addWidget(compose_frame)
        self.send_status = QLabel()
        self.send_status.setObjectName("Muted")
        self.send_status.setStyleSheet("QLabel {font-size:11px;}")
        self.send_status.setWordWrap(True)
        root.addWidget(self.send_status)
        self._drop_targets = (self, self.view.viewport(), self.editor.viewport(), self.editor,
                              self.compose_frame, self.empty_state, self.loading_state, self.error_state)
        for target in self._drop_targets:
            target.setAcceptDrops(True)
            target.installEventFilter(self)
        from .message_actions import MessageActions
        self.message_actions = MessageActions(self)
        from .message_replies import MessageReplies
        self.replies = MessageReplies(self)
        self.update_controls()

    def edited(self):
        if not self._restoring and self.identity is not None and not self.message_actions.edit:
            self.draft_versions[self.identity] = (
                self.draft_versions.get(self.identity, 0) + 1
            )
            self.remember_draft()

    def request(self, data, callback):
        sender = getattr(self.owner, "conversation_request", self.owner.start_request)
        sender(data, callback)

    def remember_draft(self):
        if self.identity is not None and not self.message_actions.edit:
            self.drafts[self.identity] = self.editor.toPlainText()

    def prefetch(self, peers):
        """Warm recent conversations without selecting or marking them read."""
        for peer in peers[:20]:
            if peer != self.identity and peer not in self.prefetched and peer not in self.history_cache and peer not in self.prefetch_pending and peer not in self.prefetch_queue:
                self.prefetch_queue.append(peer)
        self.prefetch_queue=self.prefetch_queue[:20]
        self._drain_prefetch()

    def _drain_prefetch(self):
        if not getattr(self.owner,"_alive",True):return
        while self.prefetch_queue and len(self.prefetch_pending)<2:
            peer=self.prefetch_queue.pop(0)
            self.prefetch_pending.add(peer)
            epoch=self.epoch
            token=getattr(self.owner.ctx,"session_token",None)
            def done(response,peer=peer,epoch=epoch,token=token):
                if epoch!=self.epoch or token!=getattr(self.owner.ctx,"session_token",None):return
                self.prefetch_pending.discard(peer)
                if response.get("status")=="ok" and peer!=self.identity:
                    self.prefetched[peer]=deepcopy(response)
                    self.prefetched.move_to_end(peer)
                    while len(self.prefetched)>20:self.prefetched.popitem(last=False)
                self._drain_prefetch()
            data=dict(action="get_channel_messages" if self.channel else "get_messages",paged=True,limit=self.PAGE)
            if self.channel and isinstance(peer,tuple):data.update(channel_id=peer[0],room_id=peer[1])
            else:data["channel_id" if self.channel else "to_user"]=peer
            self.request(data,done)

    def select(self, identity, name="", can_send=True):
        self.replies.clear_navigation()
        self.message_actions.cancel()
        self.remember_draft()
        if self.identity is not None and self.history_loaded:
            self.history_cache[self.identity] = dict(
                rows=deepcopy(self.rows), rendered=list(self.model.rows),
                older=self.older, newer=self.newer, at_latest=self.at_latest,
                unread_boundary=self.unread_boundary, unread_count=self.unread_count,
                unread_initialized=self.unread_initialized,
                scroll=self.view.verticalScrollBar().value(),
                anchor=self.anchor(),
                bottom=self.view.verticalScrollBar().maximum()-self.view.verticalScrollBar().value()<20)
            self.history_cache.move_to_end(self.identity)
            while len(self.history_cache)>20:
                self.history_cache.popitem(last=False)
        self.view.reflow.stop()
        self._applying = True
        warmed=self.prefetched.pop(identity,None)
        cached=self.history_cache.pop(identity,None)
        if cached is not None:self.history_cache[identity]=cached
        self.scope.invalidate()
        self.send_error.clear()
        self.offline_note.clear()
        self.connection_restored.hide();self.recovery_timer.stop()
        self.loading = False
        self.history_loaded = False
        self.history_error = False
        self.identity, self.name = identity, name
        self.unread_boundary = None
        self.unread_count = 0
        self.unseen_new = 0
        self.unread_initialized = False
        self.rows = []
        self.older = self.newer = False
        self.at_latest = True
        self.can_send = can_send
        self.model.replace([])
        self.delegate.me = self.owner.ctx.login
        self._restoring = True
        self.editor.setPlainText(self.drafts.get(identity, ""))
        self._restoring = False
        if cached is not None:
            self.rows=deepcopy(cached["rows"])
            for key in ("older","newer","at_latest","unread_boundary","unread_count","unread_initialized"):
                setattr(self,key,cached[key])
            self.history_loaded=True
            self.unread_initialized = False
            self.model.replace(cached["rendered"])
            self.view.doItemsLayout()
        if cached is None and warmed is not None:
            self.history_loaded=True
            self.apply(warmed.get("messages",[]),"latest",warmed)
        self.update_controls()
        if cached is not None:
            self.layout().activate()
            self.view.doItemsLayout()
            self.restore_position(cached["anchor"], cached["bottom"], cached["scroll"])
        self._applying = False
        if identity is not None:
            self.load("poll" if cached is not None or warmed is not None else "latest")

    def reset(self):
        self.replies.reset()
        self.message_actions.reset()
        self.image_cache.reset()
        viewer = getattr(self, "image_viewer", None)
        if viewer is not None:
            try:
                viewer.reject()
            except RuntimeError:
                pass
        self.epoch += 1
        for transfer in self.transfers:
            transfer.cancel()
        self.transfers.clear()
        self.download_transfer = None
        self.download_strip.hide()
        for identity in list(self.attachment_drafts):
            self.discard_attachment(identity)
        self.drafts.clear()
        self.draft_versions.clear()
        self.pending.clear()
        self.retries.clear()
        self.identity = None
        self.history_cache.clear()
        self.prefetched.clear()
        self.prefetch_pending.clear()
        self.prefetch_queue.clear()
        self.select(None)

    def payload(self, action, identity=None):
        identity = self.identity if identity is None else identity
        if self.channel:
            if isinstance(identity,tuple):return dict(action=action,channel_id=identity[0],room_id=identity[1])
            return dict(action=action, channel_id=identity)
        return dict(action=action, to_user=identity)

    def load(self, direction="poll"):
        if self.identity is None or self.loading:
            return
        if direction == "older" and not self.older:
            return
        if direction == "newer" and not self.newer:
            return
        # Poll the tail separately while reading old history; never splice a gap.
        action = "get_channel_messages" if self.channel else "get_messages"
        data = self.payload(action)
        data.update(paged=True, limit=self.PAGE)
        if self.rows:
            data["visible_versions"] = ",".join(f"{row['id']}:{row.get('revision', 0)}" for row in self.rows)
        if direction == "older" and self.rows:
            data["before_id"] = self.rows[0]["id"]
        elif direction == "newer" and self.rows:
            data["after_id"] = self.rows[-1]["id"]
        elif direction == "poll" and self.at_latest and self.rows:
            data["after_id"] = self.rows[-1]["id"]
        ticket = self.scope.capture("history", self.identity)
        self.loading = True
        self.update_controls()

        def done(response):
            if not self.scope.accepts(ticket, self.identity):
                return
            self.loading = False
            if response.get("status") != "ok":
                self.history_error = True
                if response.get("code") == "network_error":
                    self.offline_note.setText("Нет соединения. Текст сохранён в этом окне.")
                self.hint.setText(response.get("message", "История недоступна"))
                self.update_controls(keep_hint=True)
                return
            self.mark_connected()
            self.history_loaded = True
            self.history_error = False
            self.refresh_rows(response.get("updated_messages", []))
            incoming = response.get("messages", [])
            if direction == "poll" and not self.at_latest:
                if incoming and (
                    not self.rows or incoming[-1]["id"] != self.rows[-1]["id"]
                ):
                    self.newer = True
                    self.latest.setText("Есть новые сообщения ↓")
                self.update_controls()
                return
            self.apply(incoming, direction, response)
            if (
                self.at_latest
                and self.isVisible()
                and self.view.verticalScrollBar().maximum()
                - self.view.verticalScrollBar().value()
                < 70
            ):
                self.read_latest.emit()
            if direction == "poll" and response.get("has_newer"):
                # Catch up in bounded pages if a burst exceeds one response.
                QTimer.singleShot(0, lambda: self.load("newer"))

        self.request(data, done)

    def eventFilter(self, watched, event):
        if watched is getattr(self, 'editor', None) and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Up and event.modifiers() == Qt.NoModifier and not self.editor.toPlainText() and not self.message_actions.edit and self.identity not in self.replies.drafts:
            row = next((r for r in reversed(self.rows) if r['from_user'] == self.owner.ctx.login and not r.get('deleted_at')), None)
            if row and self.can_send:
                self.message_actions.begin(row)
                return True
        if watched is getattr(self, "editor", None) and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape and self.message_actions.edit:
            self.message_actions.cancel()
            return True
        if watched is getattr(self, "editor", None) and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape and self.identity in self.replies.drafts:
            self.replies.cancel()
            return True
        if watched in getattr(self, '_drop_targets', ()) and event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            from .attachment_input import is_attachment
            if is_attachment(event.mimeData()):
                allowed = self.identity is not None and self.can_send and self.identity not in self.pending and not self.message_actions.edit
                if allowed:
                    event.setDropAction(Qt.CopyAction)
                    event.accept()
                    if event.type() == QEvent.Drop:
                        self.accept_attachment_input(event.mimeData())
                else:
                    event.ignore()
                return True
        if watched is self.view.viewport() and event.type() == QEvent.MouseButtonPress:
            self._link_press = event.position().toPoint() if event.button() == Qt.LeftButton else None
        if watched is self.view.viewport() and event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            press = getattr(self, '_link_press', None)
            self._link_press = None
            point = event.position().toPoint()
            if press is not None and (press-point).manhattanLength() <= QApplication.startDragDistance():
                index = self.view.indexAt(point)
                if index.isValid():
                    from PySide6.QtCore import QPointF
                    emoji = self.delegate.reaction_at(index.data(Qt.UserRole), self.view.viewport().width(), QPointF(point-self.view.visualRect(index).topLeft()))
                    if emoji:
                        self.react(index.data(Qt.UserRole).id, emoji)
                        event.accept()
                        return True
                    quoted = self.delegate.reply_at(index.data(Qt.UserRole), self.view.viewport().width(), QPointF(point-self.view.visualRect(index).topLeft()))
                    if quoted:
                        self.replies.jump(quoted)
                        event.accept()
                        return True
                    url = self.delegate.link_at(index.data(Qt.UserRole), self.view.viewport().width(), QPointF(point-self.view.visualRect(index).topLeft()))
                    if url is not None:
                        from PySide6.QtGui import QDesktopServices
                        if not QDesktopServices.openUrl(url):
                            self.send_error.setText('Не удалось открыть браузер')
                        event.accept()
                        return True
                    if self.delegate.bubble_rect(index.data(Qt.UserRole), self.view.viewport().width()).contains(QPointF(point-self.view.visualRect(index).topLeft())):
                        self.open_attachment(index)
        if watched is self.view.viewport() and event.type()==QEvent.Resize:
            self.new_messages_button.move(max(0,watched.width()-260),max(0,watched.height()-60))
        return super().eventFilter(watched,event)

    def _update_new_messages(self):
        count=self.unseen_new
        noun='новое сообщение' if count%10==1 and count%100!=11 else 'новых сообщения' if count%10 in (2,3,4) and count%100 not in (12,13,14) else 'новых сообщений'
        self.new_messages_button.setText(f'{count} {noun}' if count and not self.newer else 'Новые сообщения')
        self.new_messages_button.setVisible(bool(self.newer or count))
        self.new_messages_button.raise_()

    def image_ready(self, identity):
        if not any((m.attachment or {}).get('id') == identity for m in self.model.rows):
            return
        anchor = self.anchor()
        bar = self.view.verticalScrollBar()
        bottom = bar.maximum() - bar.value() < 24
        self.view.doItemsLayout()
        self.restore_position(anchor, bottom)
        self.view.viewport().update()

    def anchor(self):
        index = self.view.indexAt(QPoint(80, 12))
        if index.isValid() and index.row() < len(self.model.rows):
            return self.model.rows[index.row()].id, self.view.visualRect(index).top()
        return None

    def restore_position(self, anchor, bottom=False, fallback=None):
        # A delayed resize anchor belongs to the previous layout/conversation.
        self.view.reflow.stop()
        bar = self.view.verticalScrollBar()
        if bottom:
            self.view.scrollToBottom()
        elif anchor:
            row = next((i for i, item in enumerate(self.model.rows) if item.id == anchor[0]), None)
            if row is not None:
                self.view.scrollTo(self.model.index(row), QAbstractItemView.PositionAtTop)
                bar.setValue(bar.value() - anchor[1])
            elif fallback is not None:
                bar.setValue(fallback)
        elif fallback is not None:
            bar.setValue(fallback)

    def refresh_rows(self, updated):
        known = {row['id']: row for row in self.rows}
        changed = [row for row in updated if row['id'] in known and row != known[row['id']]
                   and row.get('revision', 0) >= known[row['id']].get('revision', 0)]
        if changed:
            self.apply(changed, 'refresh', dict(has_newer=self.newer))

    def apply(self, incoming, direction, response):
        anchor = self.anchor()
        bar = self.view.verticalScrollBar()
        near_bottom = bar.maximum() - bar.value() < 70
        if (
            direction == "poll"
            and not near_bottom
            and len(self.rows) + len(incoming) > self.WINDOW
        ):
            self.newer = True
            self.at_latest = False
            self.latest.setText("Есть новые сообщения ↓")
            self.update_controls()
            return
        if direction == 'latest':
            self.unseen_new=0
        elif direction=='poll' and not near_bottom:
            known={row['id'] for row in self.rows}
            self.unseen_new+=sum(row['id'] not in known and row['from_user']!=self.owner.ctx.login for row in incoming)
        self._applying = True
        if direction == "latest":
            rows = incoming
            self.older = response.get("has_older", False)
            self.newer = response.get("has_newer", False)
        else:
            merged = {r["id"]: r for r in self.rows}
            merged.update({r["id"]: r for r in incoming
                           if r.get("revision", 0) >= merged.get(r["id"], {}).get("revision", 0)})
            rows = sorted(
                merged.values(), key=lambda r: (r.get("created_at", ""), r["id"])
            )
            if direction == "older":
                self.older = response.get("has_older", False)
                self.newer = self.newer or len(rows) > self.WINDOW
                rows = rows[: self.WINDOW]
            else:
                self.older = self.older or len(rows) > self.WINDOW
                self.newer = response.get("has_newer", False)
                rows = rows[-self.WINDOW :]
        self.rows = list(rows)
        read_through = response.get("read_through_id", 0)
        for row in self.rows:
            if row["from_user"] == self.owner.ctx.login and row["id"] <= read_through:
                row["is_read"] = True
        incoming_read = response.get('incoming_read_through_id', 0)
        for row in self.rows:
            if row['from_user'] != self.owner.ctx.login and row['id'] <= incoming_read:
                row['is_read'] = True
        self.at_latest = not self.newer
        if not self.channel and not self.unread_initialized:
            self.unread_initialized = True
            unread = [row for row in self.rows if row['from_user'] != self.owner.ctx.login and not row.get('is_read') and not row.get('deleted_at')]
            self.unread_boundary = unread[0]['id'] if unread else None
            self.unread_count = len(unread)
        rendered = []
        participants = {
            member.get("login"): member
            for member in getattr(self.owner, "_channel_details", {}).get("members", [])
        }
        peer = getattr(self.owner, "active_friend", None) or {}
        if peer.get("login"):
            participants[peer["login"]] = peer
        previous_author = previous_date = None
        for row in self.rows:
            if row.get("deleted_at"):
                continue
            author = row["from_user"]
            date = (row.get("created_at") or "")[:10]
            try:
                day = datetime.strptime(date, "%Y-%m-%d").date()
                today = datetime.now().date()
                months=("января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря")
                date_label = (
                    f"Сегодня, {day.day} {months[day.month-1]}"
                    if day == today
                    else f"Вчера, {day.day} {months[day.month-1]}"
                    if day == today - timedelta(days=1)
                    else day.strftime("%d.%m.%Y")
                )
            except ValueError:
                date_label = date
            person = participants.get(author, {})
            own = author == self.owner.ctx.login
            name = (
                "Вы"
                if own
                else person.get("nickname") or row.get("nickname") or (author if self.channel else self.name)
            )
            rendered.append(
                Message(
                    row["id"],
                    author,
                    name,
                    self.message_display_text(row),
                    (row.get("created_at") or "")[11:16],
                    bool(row.get("is_read")),
                    author != previous_author or date != previous_date or row["id"] == self.unread_boundary,
                    date_label,
                    date != previous_date,
                    self.unread_count if row["id"] == self.unread_boundary else 0,
                    getattr(self.owner.ctx, "avatar", "") if own else person.get("avatar") or row.get("avatar", ""),
                    row.get("attachment"),
                    row["text"],
                    bool(row.get("edited_at")) and not row.get("deleted_at"),
                    row.get("reply") if not row.get("deleted_at") else None,
                    tuple((r["emoji"], r["count"], r["mine"]) for r in row.get("reactions", [])),
                    tuple((r['emoji'], tuple((login,
                        'Вы' if login == self.owner.ctx.login else participants.get(login, {}).get('nickname', login),
                        getattr(self.owner.ctx, 'avatar', '') if login == self.owner.ctx.login else participants.get(login, {}).get('avatar', ''))
                        for login in r.get('users', []))) for r in row.get('reactions', [])),
                )
            )
            previous_author, previous_date = author, date
        if rendered == self.model.rows:
            self._applying = False
            self.update_controls()
            return
        old_count = self.model.rowCount()
        self.model.sync(rendered)
        self.update_controls()
        self.layout().activate()
        self.view.doItemsLayout()
        self.view.reflow.stop()
        if direction == "latest" or (
            direction in ("poll", "newer", "refresh") and near_bottom and self.at_latest
        ):
            self.view.scrollToBottom()
        elif anchor:
            self.restore_position(anchor)
        if direction == "poll" and len(rendered) > old_count and rendered:
            self.delegate.animate_row(len(rendered) - 1)
        self._applying = False
        self.update_controls()

    def scrolled(self, value):
        if self._applying or self.loading or not self.rows:
            return
        bar = self.view.verticalScrollBar()
        if value >= bar.maximum()-20 and not self.newer:
            self.unseen_new=0;self._update_new_messages()
        if value < 20 and self.older:
            QTimer.singleShot(0, lambda: self.load("older"))
        elif value >= bar.maximum() - 20 and self.newer:
            QTimer.singleShot(0, lambda: self.load("newer"))

    @staticmethod
    def message_display_text(row):
        from shared.attachments import size_label
        if row.get('deleted_at'):
            return 'Сообщение удалено'
        attachment = row.get('attachment')
        if not attachment:
            return row['text']
        from shared.attachments import is_image_attachment
        if is_image_attachment(attachment):
            return row['text']
        label = f"📎 {attachment['name']} · {size_label(attachment['size'])}\n↓ Скачать файл"
        return (row['text'] + '\n\n' if row['text'] else '') + label

    def choose_attachment(self):
        if self.identity is None or not self.can_send or self.identity in self.pending or self.message_actions.edit:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Прикрепить файл', '', 'Все файлы (*)')
        if not path:
            return
        self.attach_file(path)

    def accept_attachment_input(self, mime):
        if self.identity is None or not self.can_send or self.identity in self.pending or self.message_actions.edit:
            return
        from .attachment_input import local_files, ClipboardFiles
        files = local_files(mime)
        if files:
            if len(files) != 1:
                self.send_error.setText('Прикрепляйте по одному файлу к сообщению')
                return
            self.attach_file(files[0])
        elif mime.hasImage():
            try:
                if not hasattr(self, '_clipboard_files'):
                    self._clipboard_files = ClipboardFiles()
                path = self._clipboard_files.image_path(mime)
                if not self.attach_file(path, temporary=True):
                    self._clipboard_files.remove(path)
            except (ValueError, OSError) as error:
                self.send_error.setText(str(error))

    def discard_attachment(self, identity):
        draft = self.attachment_drafts.pop(identity, None)
        if draft and draft.get('temporary'):
            try:
                self._clipboard_files.remove(draft['path'])
            except OSError:
                pass

    def attach_file(self, path, temporary=False):
        from pathlib import Path
        from shared.attachments import MAX_FILE_SIZE
        if self.identity is None or not self.can_send or self.identity in self.pending or self.message_actions.edit:
            return False
        try:
            file = Path(path)
            size = file.stat().st_size
            if not file.is_file() or not 0 < size <= MAX_FILE_SIZE:
                raise ValueError('Выберите файл от 1 байта до 10 МБ')
            self.discard_attachment(self.identity)
            self.attachment_drafts[self.identity] = dict(path=path, name=file.name, size=size, temporary=temporary)
            self.update_controls()
            self.editor.setFocus(Qt.OtherFocusReason)
            self.send_error.clear()
            return True
        except (OSError, ValueError) as error:
            self.send_error.setText(str(error))
            return False

    def remove_attachment(self):
        if self.identity not in self.pending:
            self.discard_attachment(self.identity)
            self.update_controls()
            self.editor.setFocus(Qt.OtherFocusReason)

    def cancel_download(self):
        if self.download_transfer is not None:
            self.download_transfer.cancel()
            self.transfers.discard(self.download_transfer)
            self.download_transfer = None
        self.download_strip.hide()

    def open_attachment(self, index):
        meta = getattr(index.data(Qt.UserRole), 'attachment', None)
        if not meta:
            return
        from shared.attachments import is_image_attachment
        if is_image_attachment(meta):
            from .image_preview import ImageViewer
            self.image_viewer = ImageViewer(self, meta)
            self.image_viewer.show()
        else:
            self.download_metadata(meta)

    def download_attachment(self, index):
        meta = getattr(index.data(Qt.UserRole), 'attachment', None)
        if meta:
            self.download_metadata(meta)

    def download_metadata(self, meta):
        if self.download_transfer is not None:
            return
        from pathlib import Path
        from application.attachment_transfer import AttachmentTransfer
        # Never accept directories supplied by a remote filename.
        name = Path(meta['name'].replace('\\', '/')).name
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить файл', name, 'Все файлы (*)')
        if not path:
            return
        epoch = self.epoch
        transfer = AttachmentTransfer(self.owner.ctx.session_token, {}, path, meta)
        self.download_transfer = transfer
        self.download_label.setText('Скачивание · 0%')
        self.download_strip.show()
        transfer.progress.connect(lambda value: self.download_label.setText(f'Скачивание · {value}%')
            if self.download_transfer is transfer else None)
        self.transfers.add(transfer)
        def done(result):
            self.transfers.discard(transfer)
            if self.download_transfer is transfer:
                self.download_transfer = None
                self.download_strip.hide()
            if epoch == self.epoch and result.get('status') != 'ok':
                self.send_error.setText(result.get('message', 'Не удалось скачать файл'))
        transfer.finished.connect(done)
        transfer.start()

    def update_controls(self, keep_hint=False):
        if hasattr(self, "replies"):
            self.replies.update()
        self._update_new_messages()
        surface = self.view if self.model.rows else (
            self.view if self.identity is not None and not self.history_loaded and not self.rows and not self.history_error else
            self.error_state if self.history_error else self.empty_state)
        self.history_stack.setCurrentWidget(surface)
        # Background polling must not insert a status row and shift the history.
        # Initial loading already has its own full-page skeleton.
        self.hint.setVisible(bool(self.model.rows) and self.history_error)
        self.previous.setEnabled(self.older and not self.loading)
        self.previous.setVisible(self.older)
        self.latest.setVisible(self.newer)
        self.send_button.setEnabled(
            self.identity is not None
            and self.can_send
        )
        self.attach_button.setEnabled(self.identity is not None and self.can_send and self.identity not in self.pending and not self.message_actions.edit)
        draft = self.attachment_drafts.get(self.identity)
        self.attachment_strip.setVisible(bool(draft) and not self.message_actions.edit)
        path = draft.get('path') if draft else None
        if getattr(self, '_preview_path', None) != path:
            self._preview_path = path
            self.attachment_preview.clear()
            self.attachment_preview.hide()
            if path:
                from PySide6.QtGui import QImageReader, QPixmap
                from PySide6.QtCore import QSize
                reader = QImageReader(path)
                dimensions = reader.size()
                if reader.format().data() in (b'png', b'jpeg', b'webp', b'gif') and 0 < dimensions.width()*dimensions.height() <= 20000000:
                    reader.setScaledSize(dimensions.scaled(QSize(44, 44), Qt.KeepAspectRatio))
                    image = reader.read()
                    if not image.isNull():
                        self.attachment_preview.setPixmap(QPixmap.fromImage(image))
                        self.attachment_preview.show()
        self.remove_attachment_button.setEnabled(self.identity not in self.pending)
        if draft:
            from shared.attachments import size_label
            self.attachment_label.setText(draft['name'] + ' · ' + size_label(draft['size']) +
                (f" · Отправка {draft['progress']}%" if 'progress' in draft else ''))
        self.editor.setReadOnly(not self.can_send or self.identity is None)
        self.editor.setPlaceholderText(
            "Недостаточно прав для отправки" if not self.can_send
            else "Сообщение в канал…" if self.is_channel else "Сообщение…"
        )
        if not keep_hint:
            self.hint.setText(
                "Загрузка…"
                if self.loading
                else (
                    ""
                    if self.rows
                    else (
                        "Сообщений пока нет"
                        if self.identity is not None
                        else "Выберите диалог"
                    )
                )
            )
        self.permission_note.setText(
            self.permission_text
            if self.is_channel and not self.can_send else "")
        if not self.can_send:
            self.send_status.setText(
                "У вас нет права отправлять сообщения в этом канале"
            )
        else:
            self.send_status.clear()
        self.send_status.setVisible(bool(self.send_status.text()))

    def mark_connected(self):
        if self.offline_note.text():
            self.offline_note.clear()
            self.connection_restored.show()
            self.recovery_timer.start(4000)

    def send(self):
        if self.message_actions.edit:
            self.message_actions.submit()
            return
        text = self.editor.toPlainText().strip()
        reply = self.replies.drafts.get(self.identity)
        if (
            (not text and self.identity not in self.attachment_drafts)
            or self.identity is None
            or not self.can_send
            or self.identity in self.pending
        ):
            return
        if len(text) > 8000:
            self.notice.emit("Сообщение должно содержать не больше 8000 символов")
            return
        identity, epoch = self.identity, self.epoch
        revision = self.draft_versions.get(identity, 0)
        attachment = self.attachment_drafts.get(identity)
        if attachment and not attachment.get('id'):
            from application.attachment_transfer import AttachmentTransfer
            scope = self.payload('begin_attachment')
            scope.pop('action')
            transfer = AttachmentTransfer(self.owner.ctx.session_token, scope, attachment['path'],
                upload_id=attachment.setdefault('upload_id', uuid.uuid4().hex))
            self.transfers.add(transfer)
            self.pending[identity] = 'upload'
            attachment['progress'] = 0
            self.update_controls()
            def progress(value):
                if epoch == self.epoch:
                    attachment['progress'] = value
                    if self.identity == identity:
                        self.update_controls()
            def uploaded(result):
                self.transfers.discard(transfer)
                if epoch != self.epoch:
                    return
                self.pending.pop(identity, None)
                attachment.pop('progress', None)
                if result.get('status') == 'ok':
                    attachment.update(result['attachment'])
                    self._submit(identity, text, attachment, epoch, revision, restore_focus=False, reply=reply)
                else:
                    self.send_error.setText(result.get('message', 'Не удалось загрузить файл'))
                    self.update_controls()
            transfer.progress.connect(progress)
            transfer.finished.connect(uploaded)
            transfer.start()
            return
        self._submit(identity, text, attachment, epoch, revision, reply=reply)

    def _submit(self, identity, text, attachment, epoch, revision, restore_focus=True, reply=None):
        key = (identity, text, attachment.get('id') if attachment else None, reply['id'] if reply else None)
        message_id = self.retries.setdefault(key, str(uuid.uuid4()))
        self.send_error.clear()
        self.pending[identity] = message_id
        data = self.payload("send_channel_message" if self.channel else "send_message", identity)
        data.update(text=text, client_message_id=message_id, request_id=message_id)
        if reply:
            data["reply_to_id"] = reply["id"]
        if attachment:
            data["attachment_id"] = attachment["id"]
        # Disabling a focused send button lets Qt advance to an unrelated control.
        # Return focus as part of the user action, never from a delayed reply.
        if restore_focus and self.identity == identity and self.editor.isVisible():
            self.editor.setFocus(Qt.OtherFocusReason)
        self.update_controls()

        def done(response):
            if epoch != self.epoch:
                return
            self.pending.pop(identity, None)
            success = response.get("status") == "ok"
            if success:
                self.retries.pop(key, None)
                if reply is not None and self.replies.drafts.get(identity) is reply:
                    self.replies.drafts.pop(identity, None)
                if attachment and self.attachment_drafts.get(identity) is attachment:
                    self.discard_attachment(identity)
                if not self.channel:
                    sent_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    update_summary=getattr(self.owner,"message_sent",None)
                    if update_summary is not None:update_summary(identity,text or ('📎 ' + attachment['name'] if attachment else ''),sent_at)
                if (
                    self.draft_versions.get(identity, 0) == revision
                    and self.drafts.get(identity, "").strip() == text
                ):
                    self.drafts[identity] = ""
                if self.identity == identity:
                    # A successful write supersedes any older in-flight poll.
                    # Refresh immediately and ignore its eventual stale failure.
                    self.scope.invalidate()
                    self.loading = False
                    self.mark_connected()
                    if (
                        self.draft_versions.get(identity, 0) == revision
                        and self.editor.toPlainText().strip() == text
                    ):
                        self.editor.clear()
                    self.load("latest")
            message = response.get(
                "message", "Не удалось отправить. Текст сохранён — повторите отправку."
            )
            if not success:
                self.notice.emit(message)
            self.update_controls()
            if not success and self.identity == identity:
                if response.get('code') == 'network_error':
                    self.offline_note.setText('Нет соединения. Текст сохранён в этом окне.')
                else:
                    self.send_error.setText(message + " · Повторите отправку")

        self.request(data, done)

    def react(self, identity, emoji):
        row = next((r for r in self.rows if r['id'] == identity), None)
        if not row or row.get('deleted_at') or not self.can_send:
            return
        pending = getattr(self, '_reaction_pending', set())
        self._reaction_pending = pending
        key = (self.epoch, self.identity, identity, emoji)
        if key in pending:
            return
        pending.add(key)
        epoch, conversation = self.epoch, self.identity
        active = not any(r['emoji'] == emoji and r['mine'] for r in row.get('reactions', []))
        data = self.payload('set_message_reaction')
        data.update(message_id=identity, emoji=emoji, active=active, request_id=str(uuid.uuid4()))
        def done(result):
            pending.discard(key)
            if epoch != self.epoch:
                return
            self.history_cache.pop(conversation, None)
            self.prefetched.pop(conversation, None)
            if conversation != self.identity:
                return
            if result.get('status') == 'ok':
                self.refresh_rows([result['message']])
                self.send_error.clear()
            else:
                self.send_error.setText(result.get('message', 'Не удалось изменить реакцию'))
        self.request(data, done)

    def context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        message = index.data(Qt.UserRole)
        row = next((r.copy() for r in self.rows if r["id"] == message.id), None)
        if not row or row.get("deleted_at"):
            return
        identity, epoch = self.identity, self.epoch
        def current():
            return self.identity == identity and self.epoch == epoch
        text = row["text"]
        from .action_menu import ActionMenu
        menu = ActionMenu(self)
        if self.can_send:
            from shared.reactions import REACTIONS
            selected = {r['emoji'] for r in row.get('reactions', []) if r['mine']}
            menu.addChoices(REACTIONS, selected, lambda emoji: self.react(row['id'], emoji) if current() else None)
        if getattr(index.data(Qt.UserRole), 'attachment', None):
            menu.addAction('Скачать файл', lambda: self.download_attachment(index))
        menu.addAction(
            "Копировать текст", lambda: QApplication.clipboard().setText(text)
        )
        if self.can_send:
            menu.addAction('Ответить', lambda: self.replies.begin(row) if current() else None)
        if row['from_user'] == self.owner.ctx.login:
            if self.can_send:
                menu.addAction('Редактировать', lambda: self.message_actions.begin(row) if current() else None)
            menu.addAction('Удалить', lambda: self.message_actions.ask_delete(row) if current() else None)
        menu.popup(self.view.viewport().mapToGlobal(pos))
        self._menu = menu
