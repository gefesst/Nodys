"""One scalable brand asset for the rail, startup and window chrome."""
from pathlib import Path
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

class BrandMark(QWidget):
    def __init__(self, size=44, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAccessibleName("Nodus")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.renderer = QSvgRenderer(str(Path(__file__).parent / "assets/logo.svg"), self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self.renderer.render(painter, QRectF(self.rect()))
