"""Portable avatar payloads: bounded thumbnails, never workstation paths."""
import base64
from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImageReader

PREFIX = 'data:image/png;base64,'


def encode_avatar(path):
    reader = QImageReader(path)
    size = reader.size()
    if not size.isValid() or size.width()*size.height() > 25_000_000:
        raise ValueError('Выберите изображение размером до 25 мегапикселей')
    reader.setAutoTransform(True)
    reader.setScaledSize(size.scaled(QSize(128,128),Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError('Не удалось прочитать изображение')
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer,'PNG'):
        raise ValueError('Не удалось подготовить аватар')
    data = bytes(buffer.data())
    if len(data) > 100_000:
        raise ValueError('Изображение слишком большое')
    return PREFIX+base64.b64encode(data).decode('ascii')
