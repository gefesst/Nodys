"""Keep the startup surface until initial reads and their dependent reads finish."""
from PySide6.QtCore import QObject, QTimer, Signal


class StartupBarrier(QObject):
    ready = Signal()
    failed = Signal(str)
    ACTIONS = frozenset({
        'get_friends', 'get_friend_requests', 'get_unread_counts',
        'get_my_channels', 'get_my_channel_invites', 'get_channel_rooms',
        'get_channel_details', 'get_messages', 'get_channel_messages',
    })

    def __init__(self, parent=None, timeout_ms=30000):
        super().__init__(parent)
        self.active = True
        self.pending = 0
        self.sealed = False
        self.error = None
        self.check = QTimer(self)
        self.check.setSingleShot(True)
        self.check.timeout.connect(self._finish)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)
        self.deadline.start(timeout_ms)

    def track(self, action, callback):
        if not self.active or action not in self.ACTIONS:
            return callback
        self.pending += 1
        self.check.stop()
        def done(response):
            if not self.active:
                return callback(response)
            try:
                if response.get('status') != 'ok':
                    self.error = 'Не удалось подготовить данные. Проверьте соединение и повторите запуск.'
                callback(response)  # May enqueue dependent history/room reads.
            except Exception:
                self.error = 'Не удалось подготовить интерфейс. Повторите загрузку.'
                raise
            finally:
                self.pending -= 1
                self.check.start(0)
        return done

    def seal(self):
        self.sealed = True
        self.check.start(0)

    def cancel(self):
        self.active = False
        self.check.stop()
        self.deadline.stop()

    def _timeout(self):
        self.error = 'Сервер не ответил вовремя. Повторите загрузку.'
        self.cancel()
        self.failed.emit(self.error)

    def _finish(self):
        if not self.active or not self.sealed or self.pending:
            return
        self.cancel()
        if self.error:
            self.failed.emit(self.error)
        else:
            self.ready.emit()
