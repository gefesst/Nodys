"""Native movable frameless shell; content retains full opacity."""

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from .widgets import Button, icon, font
from .tokens import FG, ACC, SUB


class TitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(40)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 8, 0)
        logo = QLabel("N  Nodus")
        logo.setObjectName("WindowBrand")
        import sys

        controls = [
            ("—", "Свернуть", parent.showMinimized),
            ("□", "Развернуть", self.maximize),
            ("×", "Закрыть", parent.close),
        ]
        if sys.platform == "darwin":
            controls = [controls[2], controls[0], controls[1]]
        else:
            row.addWidget(logo)
            row.addStretch()
        for text, tip, callback in controls:
            button = Button(text)
            button.setFixedSize(36, 32)
            button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(callback)
            row.addWidget(button)
        if sys.platform == "darwin":
            row.addSpacing(16)
            row.addWidget(logo)
            row.addStretch()

    def maximize(self):
        self.window().showNormal() if self.window().isMaximized() else self.window().showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        self.maximize()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1B2430"))


class NavButton(Button):
    def __init__(self, text, name, parent=None):
        super().__init__(text, name, parent=parent)
        self.setFixedSize(64, 68)
        self.setToolTip(text)

    def sizeHint(self):
        return QSize(64, 68)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        active = bool(self.property("active"))
        if active or self._hover:
            color = QColor("#2B3B51")
            color.setAlpha(255 if active else int(150 * self._hover))
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(3, 2, 58, 64), 14, 14)
        icon(p, self.icon_name, QRectF(21, 11, 22, 22), ACC if active else SUB)
        p.setPen(QColor(FG if active else SUB))
        p.setFont(font(10, True))
        p.drawText(QRectF(0, 38, 64, 25), Qt.AlignCenter, self.text().split(" (")[0])
        if "(" in self.text():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACC))
            p.drawEllipse(QRectF(45, 6, 8, 8))
