"""Bounded real-message view with keyset history, scoped replies and safe drafts."""

from datetime import datetime, timedelta
import uuid
from PySide6.QtCore import Qt, QTimer, QPoint, Signal
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
from .state_surfaces import EmptyState, LoadingState
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
        self.rows = []
        self.loading = False
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
        self.history_stack = QStackedWidget()
        self.history_stack.addWidget(self.view)
        self.empty_state = EmptyState('Здесь начинается разговор',
            'Напишите первое сообщение в канале.' if channel else 'Напишите первое сообщение.')
        self.loading_state = LoadingState()
        self.error_state = EmptyState('История пока недоступна',
            'Не удалось загрузить сообщения канала.' if channel else 'Не удалось загрузить сообщения.',
            'Повторить', lambda: self.load('latest'))
        for surface in (self.empty_state, self.loading_state, self.error_state):
            self.history_stack.addWidget(surface)
        root.addWidget(self.history_stack, 1)
        compose_frame = QFrame()
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
        self.send_status = QLabel("Enter — отправить · Shift + Enter — новая строка")
        self.send_status.setObjectName("Muted")
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
        self.loading = False
        self.history_error = False
        self.identity, self.name = identity, name
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
                self.hint.setText(response.get("message", "История недоступна"))
                self.update_controls(keep_hint=True)
                return
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
        rendered = []
        previous_author = previous_date = None
        for row in self.rows:
            author = row["from_user"]
            date = (row.get("created_at") or "")[:10]
            try:
                day = datetime.strptime(date, "%Y-%m-%d").date()
                today = datetime.now().date()
                date_label = (
                    "Сегодня"
                    if day == today
                    else "Вчера"
                    if day == today - timedelta(days=1)
                    else day.strftime("%d.%m.%Y")
                )
            except ValueError:
                date_label = date
            name = (
                "Вы"
                if author == self.owner.ctx.login
                else row.get("nickname") or (author if self.channel else self.name)
            )
            rendered.append(
                Message(
                    row["id"],
                    author,
                    name,
                    row["text"],
                    (row.get("created_at") or "")[11:16],
                    bool(row.get("is_read")),
                    author != previous_author or date != previous_date,
                    date_label,
                    date != previous_date,
                )
            )
            previous_author, previous_date = author, date
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
        if value < 20 and self.older:
            QTimer.singleShot(0, lambda: self.load("older"))
        elif value >= bar.maximum() - 20 and self.newer:
            QTimer.singleShot(0, lambda: self.load("newer"))

    def update_controls(self, keep_hint=False):
        surface = self.view if self.rows else (
            self.loading_state if self.loading else
            self.error_state if self.history_error else self.empty_state)
        self.history_stack.setCurrentWidget(surface)
        self.hint.setVisible(bool(self.rows) and (self.loading or self.history_error))
        self.previous.setEnabled(self.older and not self.loading)
        self.previous.setVisible(self.older)
        self.latest.setVisible(self.newer)
        self.send_button.setEnabled(
            self.identity is not None
            and self.can_send
            and self.identity not in self.pending
        )
        self.editor.setReadOnly(not self.can_send or self.identity is None)
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
        if not self.can_send:
            self.send_status.setText(
                "У вас нет права отправлять сообщения в этом канале"
            )
        elif self.identity in self.pending:
            self.send_status.setText("Отправляем… Можно продолжать редактирование")
        else:
            self.send_status.setText("Enter — отправить · Shift + Enter — новая строка")

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
                self.send_status.setText(message + " · Повторите отправку")

        self.request(data, done)

    def context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        text = index.data()
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.addAction(
            "Копировать текст", lambda: QApplication.clipboard().setText(text)
        )
        menu.addAction("К последним сообщениям", lambda: self.load("latest"))
        menu.popup(self.view.viewport().mapToGlobal(pos))
        self._menu = menu
