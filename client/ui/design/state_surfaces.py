"""Shared empty/error and loading surfaces from the approved desktop layouts."""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QVBoxLayout
from .widgets import Button, icon, draw_text
from .tokens import ACC, FG, SUB


class StateIcon(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(76, 76)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#263750"))
        painter.drawEllipse(self.rect())
        icon(painter, "chat", QRectF(22, 22, 32, 32), ACC)


class EmptyState(QFrame):
    def __init__(self, title, description, action=None, callback=None):
        super().__init__()
        self.setObjectName("EmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 114, 20, 20)
        layout.setSpacing(0)
        layout.addWidget(StateIcon(), 0, Qt.AlignHCenter)
        layout.addSpacing(16)
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignCenter)
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size:24px;font-weight:600;")
        heading.setMinimumHeight(29)
        layout.addWidget(heading)
        layout.addSpacing(15)
        subtitle = QLabel(description)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size:14px;color:" + SUB + ";")
        subtitle.setMinimumHeight(18)
        layout.addWidget(subtitle)
        if action:
            layout.addSpacing(25)
            button = Button(action, primary=True)
            button.setMinimumWidth(140)
            button.setFixedHeight(40)
            if callback:
                button.clicked.connect(callback)
            layout.addWidget(button, 0, Qt.AlignHCenter)
        layout.addStretch()


class LoadingState(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(400)
        self.setAccessibleName("Загружаем…")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for y, width in ((20, 430), (85, 310), (175, 490), (265, 360)):
            painter.setBrush(QColor("#293646"))
            painter.drawEllipse(QRectF(0, y - 1, 32, 32))
            width = max(40, min(width, self.width() - 58))
            painter.setBrush(QColor("#2B384A"))
            painter.drawRoundedRect(QRectF(42, y, width, 16), 6, 6)
            painter.setBrush(QColor("#253142"))
            painter.drawRoundedRect(QRectF(42, y + 27, max(25, width - 80), 11), 5, 5)
        draw_text(painter, 42, 382, "Загружаем…", 13, SUB)


class InlineNote(QLabel):
    """Status text occupies space only while a real message is present."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setMinimumHeight(46)
        self.set_tone("info")
        self.hide()

    def set_tone(self, tone):
        self.note_color = {"info": ACC, "success": "#67D5AD", "error": "#FFA7AE"}.get(
            tone, ACC
        )
        self.setStyleSheet(
            "background:#253142;border:1px solid #354152;border-radius:10px;padding:0 34px;font-size:13px;color:"
            + self.note_color
            + ";"
        )

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self):
        self.setText("")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.note_color))
        painter.drawEllipse(QRectF(16, self.height() / 2 - 3, 6, 6))
