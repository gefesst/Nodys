"""Bounded real-message view with keyset history, scoped replies and safe drafts."""

from datetime import datetime, timedelta
import uuid
from PySide6.QtCore import Qt, QTimer, QPoint, Signal, QEvent
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QApplication,
    QAbstractItemView,
    QStackedWidget,
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
        self.loading = False
        self.history_loaded = False
        self.history_error = False
        self.older = self.newer = False
        self.at_latest = True
        self.drafts = {}
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
        compose_frame = QFrame()
        self.compose_frame = compose_frame
        compose_frame.setObjectName("ComposerFrame")
        compose = QHBoxLayout(compose_frame)
        compose.setContentsMargins(4, 4, 12, 4)
        compose.setSpacing(8)
        self.editor = Composer()
        self.editor.setObjectName("MessageComposer")
        self.editor.setAccessibleName("Текст сообщения")
        self.editor.submit.connect(self.send)
        self.editor.textChanged.connect(self.edited)
        self.send_button = Button("", "send", True)
        self.send_button.setAccessibleName("Отправить сообщение")
        self.send_button.setFixedSize(38, 38)
        self.send_button.clicked.connect(self.send)
        compose.addWidget(self.editor, 1)
        compose.addWidget(self.send_button, 0, Qt.AlignVCenter)
        root.addWidget(compose_frame)
        self.send_status = QLabel()
        self.send_status.setObjectName("Muted")
        self.send_status.setStyleSheet("QLabel {font-size:11px;}")
        self.send_status.setWordWrap(True)
        root.addWidget(self.send_status)
        self.update_controls()

    def edited(self):
        if not self._restoring and self.identity is not None:
            self.draft_versions[self.identity] = (
                self.draft_versions.get(self.identity, 0) + 1
            )
            self.remember_draft()

    def request(self, data, callback):
        sender = getattr(self.owner, "conversation_request", self.owner.start_request)
        sender(data, callback)

    def remember_draft(self):
        if self.identity is not None:
            self.drafts[self.identity] = self.editor.toPlainText()

    def select(self, identity, name="", can_send=True):
        self.remember_draft()
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
        self.update_controls()
        if identity is not None:
            self.load("latest")

    def reset(self):
        self.epoch += 1
        self.drafts.clear()
        self.draft_versions.clear()
        self.pending.clear()
        self.retries.clear()
        self.identity = None
        self.select(None)

    def payload(self, action):
        if self.channel:
            return dict(action=action, channel_id=self.identity)
        return dict(action=action, to_user=self.identity)

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
        if watched is self.view.viewport() and event.type()==QEvent.Resize:
            self.new_messages_button.move(max(0,watched.width()-260),max(0,watched.height()-60))
        return super().eventFilter(watched,event)

    def _update_new_messages(self):
        count=self.unseen_new
        noun='новое сообщение' if count%10==1 and count%100!=11 else 'новых сообщения' if count%10 in (2,3,4) and count%100 not in (12,13,14) else 'новых сообщений'
        self.new_messages_button.setText(f'{count} {noun}' if count and not self.newer else 'Новые сообщения')
        self.new_messages_button.setVisible(bool(self.newer or count))
        self.new_messages_button.raise_()

    def anchor(self):
        index = self.view.indexAt(QPoint(80, 12))
        if index.isValid() and index.row() < len(self.rows):
            return self.rows[index.row()]["id"], self.view.visualRect(index).top()
        return None

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
            merged.update({r["id"]: r for r in incoming})
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
        self.at_latest = not self.newer
        if direction == "latest" and not self.channel and not self.unread_initialized:
            self.unread_initialized = True
            unread = [row for row in self.rows if row['from_user'] != self.owner.ctx.login and not row.get('is_read')]
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
                    row["text"],
                    (row.get("created_at") or "")[11:16],
                    bool(row.get("is_read")),
                    author != previous_author or date != previous_date or row["id"] == self.unread_boundary,
                    date_label,
                    date != previous_date,
                    self.unread_count if row["id"] == self.unread_boundary else 0,
                    getattr(self.owner.ctx, "avatar", "") if own else person.get("avatar") or row.get("avatar", ""),
                )
            )
            previous_author, previous_date = author, date
        if rendered == self.model.rows:
            self._applying = False
            self.update_controls()
            return
        old_count = self.model.rowCount()
        self.model.sync(rendered)
        self.view.doItemsLayout()
        if direction == "latest" or (
            direction in ("poll", "newer") and near_bottom and self.at_latest
        ):
            self.view.scrollToBottom()
        elif anchor:
            row = next(
                (i for i, r in enumerate(self.rows) if r["id"] == anchor[0]), None
            )
            if row is not None:
                self.view.scrollTo(
                    self.model.index(row), QAbstractItemView.PositionAtTop
                )
                bar.setValue(bar.value() - anchor[1])
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

    def update_controls(self, keep_hint=False):
        self._update_new_messages()
        surface = self.view if self.rows else (
            self.loading_state if self.loading and not getattr(self, "history_loaded", False) else
            self.error_state if self.history_error else self.empty_state)
        self.history_stack.setCurrentWidget(surface)
        # Background polling must not insert a status row and shift the history.
        # Initial loading already has its own full-page skeleton.
        self.hint.setVisible(bool(self.rows) and self.history_error)
        self.previous.setEnabled(self.older and not self.loading)
        self.previous.setVisible(self.older)
        self.latest.setVisible(self.newer)
        self.send_button.setEnabled(
            self.identity is not None
            and self.can_send
            and self.identity not in self.pending
        )
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
        elif self.identity in self.pending:
            self.send_status.setText("Отправляем… Можно продолжать редактирование")
        else:
            self.send_status.clear()
        self.send_status.setVisible(bool(self.send_status.text()))

    def mark_connected(self):
        if self.offline_note.text():
            self.offline_note.clear()
            self.connection_restored.show()
            self.recovery_timer.start(4000)

    def send(self):
        text = self.editor.toPlainText().strip()
        if (
            not text
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
        key = (identity, text)
        message_id = self.retries.setdefault(key, str(uuid.uuid4()))
        self.send_error.clear()
        self.pending[identity] = message_id
        data = self.payload("send_channel_message" if self.channel else "send_message")
        data.update(text=text, client_message_id=message_id, request_id=message_id)
        self.update_controls()

        def done(response):
            if epoch != self.epoch:
                return
            self.pending.pop(identity, None)
            success = response.get("status") == "ok"
            if success:
                self.retries.pop(key, None)
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
            message = (
                "Сообщение отправлено"
                if success
                else response.get(
                    "message",
                    "Не удалось отправить. Текст сохранён — повторите отправку.",
                )
            )
            self.notice.emit(message)
            self.update_controls()
            if not success and self.identity == identity:
                if response.get('code') == 'network_error':
                    self.offline_note.setText('Нет соединения. Текст сохранён в этом окне.')
                else:
                    self.send_error.setText(message + " · Повторите отправку")

        self.request(data, done)

    def context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        text = index.data()
        from .action_menu import ActionMenu
        menu = ActionMenu(self)
        menu.addAction(
            "Копировать текст", lambda: QApplication.clipboard().setText(text)
        )
        menu.popup(self.view.viewport().mapToGlobal(pos))
        self._menu = menu
