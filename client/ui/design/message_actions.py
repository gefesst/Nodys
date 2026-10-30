"""Editing state belongs to a conversation; ordinary drafts remain untouched."""
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel
from .widgets import Button
from .dialogs import confirm


class MessageActions:
    def __init__(self, conversation):
        self.conversation = conversation
        self.edit = None
        self.pending = False
        self.operation = 0
        self.strip = QFrame()
        self.strip.setObjectName('MessageEditStrip')
        self.strip.setStyleSheet('QFrame#MessageEditStrip {background:#383A40;border:1px solid #41434A;border-radius:10px;}')
        layout = QHBoxLayout(self.strip)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.addWidget(QLabel('Редактирование сообщения'), 1)
        self.cancel_button = Button('Отмена')
        self.cancel_button.clicked.connect(self.cancel)
        layout.addWidget(self.cancel_button)
        self.strip.hide()
        root = conversation.layout()
        root.insertWidget(root.indexOf(conversation.compose_frame), self.strip)

    def begin(self, row):
        c = self.conversation
        if self.pending or c.identity in c.pending or not c.can_send:
            return
        self.cancel()
        self.edit = dict(row=row.copy(), identity=c.identity, draft=c.editor.toPlainText())
        c.editor.setPlainText(row['text'])
        self.strip.show()
        c.editor.setFocus(Qt.OtherFocusReason)
        c.update_controls()

    def cancel(self):
        c = self.conversation
        edit, self.edit = self.edit, None
        if edit and c.identity == edit['identity']:
            c._restoring = True
            c.editor.setPlainText(edit['draft'])
            c._restoring = False
        self.strip.hide()
        c.update_controls()

    def reset(self):
        self.operation += 1
        self.pending = False
        self.cancel()

    def submit(self):
        c = self.conversation
        if not self.edit or self.pending:
            return
        text = c.editor.toPlainText().strip()
        if len(text) > 8000 or (not text and not self.edit['row'].get('attachment')):
            c.send_error.setText('Введите сообщение до 8000 символов')
            return
        edit = self.edit
        if text == edit['row']['text']:
            self.cancel()
            return
        self._mutate('edit_message', edit['row'], text, edit=edit)

    def ask_delete(self, row):
        c = self.conversation
        identity = c.identity
        epoch = c.epoch
        confirm(c, 'Удалить сообщение?',
                'Текст и вложение будут удалены у всех участников переписки.',
                'Удалить', lambda: self._mutate('delete_message', row) if c.identity == identity and c.epoch == epoch else None,
                danger=True)

    def _mutate(self, action, row, text='', edit=None):
        c = self.conversation
        if self.pending:
            return
        identity, epoch = c.identity, c.epoch
        data = c.payload(action)
        data.update(message_id=row['id'], expected_revision=row.get('revision', 0), text=text,
                    request_id=str(uuid.uuid4()))
        self.pending = True
        self.operation += 1
        operation = self.operation
        c.send_error.clear()
        def done(result):
            if epoch != c.epoch or operation != self.operation:
                return
            self.pending = False
            c.history_cache.pop(identity, None)
            c.prefetched.pop(identity, None)
            if c.identity != identity:
                return
            if result.get('status') != 'ok':
                c.send_error.setText(result.get('message', 'Не удалось изменить сообщение'))
                c.load('poll')
                return
            c.scope.invalidate()
            c.loading = False
            c.refresh_rows([result['message']])
            if edit is not None and self.edit is edit:
                # Do not discard typing made while the request was in flight.
                if c.editor.toPlainText().strip() == text:
                    self.cancel()
                else:
                    edit['row'] = result['message']
            elif self.edit and self.edit['row']['id'] == row['id']:
                self.cancel()
            refresh = getattr(c.owner, 'load_unread_counts', None)
            if not c.channel and refresh:
                refresh(force=True)
            c.update_controls()
        c.request(data, done)
