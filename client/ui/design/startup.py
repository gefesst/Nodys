"""Quiet session-restoration screen; animation follows actual visibility."""
import math
from PySide6.QtCore import Qt, QRectF, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from .widgets import Button
from .motion import reduced
from .tokens import ACC


from .brand import BrandMark

class StartupMark(BrandMark):
    def __init__(self):
        super().__init__(84)


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
        self.setAccessibleName('Подключение к noda')

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
        p.setBrush(QColor('#404249'))
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
        title = QLabel('noda')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('font-size:30px;font-weight:600;')
        layout.addWidget(title)
        layout.addSpacing(10)
        self.status = status = QLabel('Подключаемся…')
        status.setAlignment(Qt.AlignCenter)
        status.setStyleSheet('font-size:13px;color:#949BA4;')
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

    def set_status(self, text, retry=None):
        self.status.setText(text)
        self.progress.setVisible(retry is None)
        if not hasattr(self, 'retry_button'):
            self.retry_button = Button('Повторить')
            self.retry_button.setFixedSize(180, 40)
            self.retry_button.clicked.connect(lambda: self._retry() if self._retry else None)
            self.layout().insertWidget(self.layout().count()-2, self.retry_button, 0, Qt.AlignHCenter)
        self.retry_button.setVisible(retry is not None)
        self._retry = retry
