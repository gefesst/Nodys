"""Quiet session-restoration screen; animation follows actual visibility."""
import math
from PySide6.QtCore import Qt, QRectF, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from .widgets import Button, icon
from .motion import reduced
from .tokens import ACC


class StartupMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(84, 84)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, 84, 84)
        gradient.setColorAt(0, QColor('#30476A'))
        gradient.setColorAt(1, QColor('#202E42'))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient)
        p.drawRoundedRect(QRectF(0, 0, 84, 84), 24, 24)
        icon(p, 'n', QRectF(22, 22, 40, 40), ACC)


class StartupProgress(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(160, 4)
        self._phase = 0.0
        self.animation = QPropertyAnimation(self, b'phase', self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(1800)
        self.animation.setLoopCount(-1)
        self.animation.setEasingCurve(QEasingCurve.Linear)
        self.setAccessibleName('Подключение к Nodus')

    def get_phase(self):
        return self._phase

    def set_phase(self, value):
        self._phase = value
        self.update()

    phase = Property(float, get_phase, set_phase)

    def showEvent(self, event):
        super().showEvent(event)
        if reduced():
            self.set_phase(0.25)
        else:
            self.animation.start()

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#2B3B51'))
        p.drawRoundedRect(QRectF(0, 0, 160, 4), 2, 2)
        # Continuous there-and-back motion, with no fictitious percentage.
        position = (1 - math.cos(2*math.pi*self._phase)) / 2
        p.setBrush(QColor(ACC))
        p.drawRoundedRect(QRectF(position*120, 0, 40, 4), 2, 2)


class StartupPage(QWidget):
    def __init__(self, cancel):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(0)
        layout.addStretch()
        layout.addWidget(StartupMark(), 0, Qt.AlignHCenter)
        layout.addSpacing(22)
        title = QLabel('Nodus')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('font-size:30px;font-weight:600;')
        layout.addWidget(title)
        layout.addSpacing(10)
        status = QLabel('Подключаемся…')
        status.setAlignment(Qt.AlignCenter)
        status.setStyleSheet('font-size:13px;color:#9AA9BE;')
        layout.addWidget(status)
        layout.addSpacing(24)
        self.progress = StartupProgress()
        layout.addWidget(self.progress, 0, Qt.AlignHCenter)
        layout.addSpacing(24)
        self.cancel_button = Button('Войти вручную')
        self.cancel_button.setProperty('flat', True)
        self.cancel_button.setFixedSize(180, 40)
        self.cancel_button.clicked.connect(cancel)
        layout.addWidget(self.cancel_button, 0, Qt.AlignHCenter)
        layout.addStretch()
