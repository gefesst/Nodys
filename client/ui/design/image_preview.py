"""Memory-only image previews and a viewer contained by the application window."""
from collections import OrderedDict
from PySide6.QtCore import QObject, Signal, QTimer, Qt, QRectF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from .overlay import OverlayDialog
from .widgets import Button


class ImageCache(QObject):
    changed = Signal(str)
    BUDGET = 64 * 1024 * 1024

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.images = OrderedDict()
        self.errors = {}
        self.pending = {}
        self.queue = OrderedDict()
        self.generation = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._drain)

    def get(self, metadata):
        aid = metadata['id']
        image = self.images.get(aid)
        if image is not None:
            self.images.move_to_end(aid)
        return image

    def ensure(self, metadata):
        aid = metadata['id']
        if aid in self.images or aid in self.errors or aid in self.pending or aid in self.queue:
            return
        if len(self.queue) < 24:
            self.queue[aid] = dict(metadata)
            self.timer.start(0)

    def retry(self, metadata):
        self.errors.pop(metadata['id'], None)
        self.ensure(metadata)

    def reset(self):
        self.generation += 1
        self.timer.stop()
        for transfer in self.pending.values():
            transfer.cancel()
        self.pending.clear()
        self.queue.clear()
        self.images.clear()
        self.errors.clear()

    def _drain(self):
        from application.attachment_transfer import AttachmentTransfer
        token = getattr(self.owner.owner.ctx, 'session_token', '')
        if not token or not getattr(self.owner.owner, '_alive', True):
            self.queue.clear()
            return
        while self.queue and len(self.pending) < 2:
            aid, meta = self.queue.popitem(last=False)
            transfer = AttachmentTransfer(token, {}, None, meta, preview=True)
            self.pending[aid] = transfer
            generation = self.generation
            def done(result, aid=aid, generation=generation, token=token):
                if generation != self.generation:
                    return
                self.pending.pop(aid, None)
                if token != getattr(self.owner.owner.ctx, 'session_token', ''):
                    return
                if result.get('status') == 'ok':
                    self.images[aid] = result['image']
                    while sum(image.sizeInBytes() for image in self.images.values()) > self.BUDGET:
                        self.images.popitem(last=False)
                else:
                    self.errors[aid] = result.get('message', 'Не удалось открыть изображение')
                    if len(self.errors) > 240:
                        self.errors.pop(next(iter(self.errors)))
                self.changed.emit(aid)
                self._drain()
            transfer.finished.connect(done)
            transfer.start()


class ImageCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.message = 'Открываем изображение…'
        self.setMinimumSize(80, 80)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor('#1E1F22'))
        if self.image is not None:
            size = self.image.size().scaled(self.size(), Qt.KeepAspectRatio)
            target = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2, size.width(), size.height())
            painter.drawImage(target, self.image)
        else:
            painter.setPen(QColor('#B5BAC1'))
            painter.drawText(self.rect().adjusted(24, 24, -24, -24), Qt.AlignCenter | Qt.TextWordWrap, self.message)


class ImageViewer(OverlayDialog):
    def __init__(self, conversation, metadata):
        super().__init__(conversation, width=1600, height=1100)
        self.metadata = metadata
        self.cache = conversation.image_cache
        self.setAccessibleName('Просмотр изображения')
        self.setStyleSheet('QDialog#OverlayDialog {background:#2B2D31;border:1px solid #41434A;border-radius:14px;}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        header = QHBoxLayout()
        title = QLabel(metadata['name'])
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        header.addWidget(title, 1)
        save = Button('Сохранить')
        save.clicked.connect(lambda: conversation.download_metadata(metadata))
        header.addWidget(save)
        retry = Button('Повторить')
        retry.clicked.connect(lambda: self.cache.retry(metadata))
        header.addWidget(retry)
        self.retry = retry
        close = Button('', 'close')
        close.setAccessibleName('Закрыть изображение')
        close.setFixedSize(36, 36)
        close.clicked.connect(self.reject)
        header.addWidget(close)
        layout.addLayout(header)
        self.canvas = ImageCanvas()
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        layout.addWidget(self.canvas, 1)
        self.cache.changed.connect(self.refresh)
        self.finished.connect(self._detach)
        self.cache.ensure(metadata)
        self.refresh(metadata['id'])

    def showEvent(self, event):
        super().showEvent(event)
        self.canvas.setFocus(Qt.OtherFocusReason)

    def _detach(self, *_):
        if getattr(self, "_detached", False):
            return
        self._detached = True
        self.cache.changed.disconnect(self.refresh)
        self.deleteLater()

    def refresh(self, aid):
        if aid != self.metadata['id']:
            return
        self.canvas.image = self.cache.get(self.metadata)
        self.canvas.message = self.cache.errors.get(aid, 'Открываем изображение…')
        self.retry.setVisible(aid in self.cache.errors)
        self.canvas.update()
