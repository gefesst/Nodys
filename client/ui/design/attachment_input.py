"""Normalize native paste/drop input into the existing attachment draft flow."""
from pathlib import Path
import uuid
from PySide6.QtCore import QTemporaryDir
from PySide6.QtGui import QImage, QPixmap, QImageWriter


def local_files(mime):
    return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]


def is_attachment(mime):
    return mime.hasImage() or bool(local_files(mime))


class ClipboardFiles:
    def __init__(self):
        self.directory = QTemporaryDir()
        if not self.directory.isValid():
            raise OSError('Не удалось подготовить изображение из буфера')

    def image_path(self, mime):
        image = mime.imageData()
        if isinstance(image, QPixmap):
            image = image.toImage()
        if not isinstance(image, QImage) or image.isNull():
            raise ValueError('В буфере нет изображения')
        if image.width()*image.height() > 40000000:
            raise ValueError('Изображение слишком большое для вставки')
        path = str(Path(self.directory.path()) / ('Изображение-' + uuid.uuid4().hex[:8] + '.png'))
        writer = QImageWriter(path, b'png')
        if not writer.write(image):
            raise ValueError('Не удалось подготовить изображение из буфера')
        return path

    def remove(self, path):
        file = Path(path)
        if file.parent == Path(self.directory.path()):
            file.unlink(missing_ok=True)
