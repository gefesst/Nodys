"""Per-conversation reply drafts and scoped navigation to quoted originals."""
from copy import deepcopy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QAbstractItemView
from .widgets import Button


class MessageReplies:
    def __init__(self, conversation):
        self.c = conversation
        self.drafts = {}
        self.return_state = None
        self.strip = QFrame()
        self.strip.setObjectName('ReplyDraft')
        self.strip.setStyleSheet('QFrame#ReplyDraft {background:#383A40;border:1px solid #41434A;border-radius:10px;}')
        layout = QHBoxLayout(self.strip)
        layout.setContentsMargins(12, 6, 8, 6)
        self.label = QLabel()
        self.label.setTextFormat(Qt.PlainText)
        self.label.setMinimumWidth(0)
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.label, 1)
        cancel = Button('', 'close')
        cancel.setAccessibleName('Отменить ответ')
        cancel.setFixedSize(30, 30)
        cancel.clicked.connect(self.cancel)
        layout.addWidget(cancel)
        root = conversation.layout()
        root.insertWidget(root.indexOf(conversation.compose_frame), self.strip)
        self.back = Button('Вернуться к ответу', 'back')
        self.back.clicked.connect(self.go_back)
        self.back.setFixedSize(240, 34)
        root.insertWidget(1, self.back, 0, Qt.AlignRight)
        self.back.hide()
        self.strip.hide()
        self.highlight_timer = QTimer(conversation)
        self.highlight_timer.setSingleShot(True)
        self.highlight_timer.timeout.connect(self.clear_highlight)

    def begin(self, row):
        c = self.c
        if row.get('deleted_at') or not c.can_send or c.identity in c.pending:
            return
        c.message_actions.cancel()
        self.drafts[c.identity] = dict(id=row['id'], author=row['from_user'],
                                      text=row.get('text') or (row.get('attachment') or {}).get('name', 'Вложение'))
        self.update()
        c.editor.setFocus(Qt.OtherFocusReason)

    def cancel(self):
        self.drafts.pop(self.c.identity, None)
        self.update()

    def update(self):
        draft = self.drafts.get(self.c.identity)
        if draft and any(row['id'] == draft['id'] and row.get('deleted_at') for row in self.c.rows):
            self.drafts.pop(self.c.identity, None)
            draft = None
        self.strip.setVisible(bool(draft) and not self.c.message_actions.edit)
        if draft:
            author = 'Вы' if draft['author'] == self.c.owner.ctx.login else draft['author']
            text = ' '.join(draft['text'].split())[:100]
            self.label.setText(f'Ответ · {author}: {text}')
        self.back.setVisible(self.return_state is not None)

    def clear_highlight(self):
        self.c.delegate.highlight_id = None
        self.c.view.viewport().update()

    def clear_navigation(self):
        self.return_state = None
        self.highlight_timer.stop()
        self.clear_highlight()
        self.back.hide()

    def reset(self):
        self.drafts.clear()
        self.clear_navigation()
        self.strip.hide()

    def focus(self, identity):
        c = self.c
        index = next((i for i, row in enumerate(c.model.rows) if row.id == identity), None)
        if index is None:
            return
        c._applying = True
        c.view.reflow.stop()
        c.view.doItemsLayout()
        c.view.scrollTo(c.model.index(index), QAbstractItemView.PositionAtCenter)
        c._applying = False
        c.delegate.highlight_id = identity
        c.view.viewport().update()
        self.highlight_timer.start(1800)

    def jump(self, identity):
        c = self.c
        if not c.identity:
            return
        if any(row['id'] == identity and row.get('deleted_at') for row in c.rows):
            return
        snapshot = dict(rows=deepcopy(c.rows), older=c.older, newer=c.newer,
                        anchor=c.anchor(), scroll=c.view.verticalScrollBar().value())
        if any(row['id'] == identity for row in c.rows):
            if self.return_state is None:
                self.return_state = snapshot
            self.update()
            c.layout().activate()
            self.focus(identity)
            return
        c.scope.invalidate()
        ticket = c.scope.capture('history', c.identity)
        c.loading = True
        data = c.payload('get_channel_messages' if c.channel else 'get_messages')
        data.update(paged=True, around_id=identity, limit=c.PAGE)
        def done(result):
            if not c.scope.accepts(ticket, c.identity):
                return
            c.loading = False
            if result.get('status') != 'ok':
                c.send_error.setText(result.get('message', 'Исходное сообщение недоступно'))
                return
            if any(row['id'] == identity and row.get('deleted_at') for row in result['messages']):
                return
            if self.return_state is None:
                self.return_state = snapshot
            c.apply(result['messages'], 'latest', result)
            self.update()
            c.layout().activate()
            self.focus(identity)
        c.request(data, done)

    def go_back(self):
        c = self.c
        saved = self.return_state
        if saved is None:
            return
        c.scope.invalidate()
        c.loading = False
        self.clear_navigation()
        current = {row['id']: row for row in c.rows}
        rows = [current.get(row['id'], row) if current.get(row['id'], {}).get('revision', -1) >= row.get('revision', 0) else row for row in saved['rows']]
        c.apply(rows, 'latest', dict(has_older=saved['older'], has_newer=saved['newer']))
        c._applying = True
        c.restore_position(saved['anchor'], fallback=saved['scroll'])
        c._applying = False
        c.load('poll')
