"""Opt-in level check. Audio samples are never stored, sent, or played back."""

import threading
import time
from PySide6.QtCore import QObject, Signal, QTimer, Qt, QRectF, QByteArray
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from .widgets import Button, ASSETS
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtGui import QPainter, QColor


class MicrophoneMeter(QWidget):
    """Ten sample bars, matching the approved microphone-check indicator."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(160,52)
        self.samples=[0]*10
        self.setAccessibleName('Уровень микрофона')

    def setValue(self,value):
        level=max(0,min(100,int(value)))
        self.samples=self.samples[1:]+[level]
        self.setAccessibleDescription(str(level)+'%')
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for index,level in enumerate(self.samples):
            height=max(4,26*level/100)
            painter.setBrush(QColor('#67D5AD' if level>1 else '#3C4E66'))
            painter.drawRoundedRect(QRectF(index*17,29-height,6,height),3,3)


class MeterSignals(QObject):
    error = Signal(str)
    ready = Signal()
    finished = Signal()


class MicrophoneCheck(QFrame):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Проверка микрофона")
        self.setObjectName("MicrophoneCheck")
        self.setMinimumHeight(105)
        self.setStyleSheet("QFrame#MicrophoneCheck {background:#202D3D;border:1px solid #354152;border-radius:12px;}")
        self.stop_event = threading.Event()
        self.level = 0
        self.last_signal = time.monotonic()
        self.worker = None
        self.failed_state = False
        self.signals = MeterSignals(self)
        self.signals.error.connect(self.failed)
        self.signals.finished.connect(self.completed)
        self.signals.ready.connect(self.listening)
        root = QHBoxLayout(self)
        root.setContentsMargins(22,16,112,16)
        root.setSpacing(16)
        symbol=QSvgWidget();symbol.load(QByteArray((ASSETS/"mic.svg").read_bytes().replace(b"#ACB9CC",b"#91ADFF")));symbol.setFixedSize(22,22)
        symbol_column=QVBoxLayout();symbol_column.setContentsMargins(0,7,0,0)
        symbol_column.addWidget(symbol);symbol_column.addStretch()
        root.addLayout(symbol_column)
        column=QVBoxLayout();column.setSpacing(8);column.setContentsMargins(0,7,0,0)
        self.title=QLabel('Проверка микрофона');self.title.setFixedHeight(20)
        self.title.setStyleSheet('font-size:16px;font-weight:600;')
        column.addWidget(self.title)
        self.status=QLabel('Проверка начинается по кнопке. Звук не сохраняется и не передаётся.')
        self.status.setWordWrap(True);self.status.setAlignment(Qt.AlignLeft|Qt.AlignTop)
        self.status.setStyleSheet('font-size:13px;color:#ACB9CC;')
        column.addWidget(self.status)
        root.addLayout(column,1)
        self.meter=MicrophoneMeter()
        root.addWidget(self.meter)
        self.start_button=Button('Проверить',primary=True)
        self.start_button.setFixedSize(120,40)
        self.start_button.clicked.connect(self.start)
        root.addWidget(self.start_button)
        stop=Button('', 'close');stop.setFixedSize(28,28);stop.setAccessibleName('Остановить проверку микрофона')
        stop.clicked.connect(self.close);stop.setParent(self);self.stop_button=stop
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_meter)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.stop_button.move(self.width()-46,(self.height()-28)//2)

    def listening(self):
        self.failed_state = False
        self.start_button.hide()
        self.meter.show()
        self.last_signal = time.monotonic()
        self.title.setText("Проверка микрофона")
        self.status.setText("Скажите несколько слов — индикатор покажет уровень.")

    def update_meter(self):
        self.meter.setValue(self.level)
        if self.level > 1:
            self.start_button.hide()
            self.last_signal = time.monotonic()
            self.title.setText("Проверка микрофона")
            self.status.setText("Скажите несколько слов — индикатор покажет уровень.")
        elif time.monotonic() - self.last_signal >= 3:
            self.title.setText("Пока не слышим микрофон")
            self.status.setText("Проверьте выбранное устройство и уровень громкости.")
            self.start_button.setEnabled(True)
            self.start_button.show()

    def start(self):
        if self.worker and self.worker.is_alive():
            self.listening()
            self.start_button.setEnabled(False)
            return
        self.listening()
        self.start_button.setEnabled(False)
        self.stop_event.clear()
        self.timer.start()
        self.worker = threading.Thread(
            target=self.capture, daemon=True, name="microphone-level-check"
        )
        self.worker.start()

    def capture(self):
        try:
            import numpy as np
            import sounddevice as sd

            def callback(data, frames, timing, status):
                self.level = min(100, int(float(np.max(np.abs(data))) * 250))

            from config import load_config
            from audio.devices import resolve_device
            device=resolve_device(sd,load_config().get("audio_input_device"),"input")
            with sd.InputStream(device=device,channels=1, callback=callback):
                self.signals.ready.emit()
                self.stop_event.wait(30)
        except Exception as error:
            if not self.stop_event.is_set():
                self.signals.error.emit(
                    "Микрофон недоступен. Проверьте устройство и разрешение системы. "
                    + str(error)
                )
        finally:
            self.level = 0
            self.signals.finished.emit()

    def completed(self):
        self.start_button.setEnabled(True)
        self.timer.stop()
        self.meter.setValue(0)
        if not self.failed_state:
            self.start_button.show()
        if not self.stop_event.is_set() and not self.failed_state:
            self.status.setText("Проверка завершена. Звук не сохранялся.")

    def hideEvent(self, event):
        self.stop_event.set()
        self.timer.stop()
        super().hideEvent(event)

    def failed(self, message):
        self.failed_state = True
        denied=any(term in message.casefold() for term in ("permission", "not permitted", "access denied", "разрешение запрещено"))
        self.title.setText("Нет доступа к микрофону" if denied else "Микрофон недоступен")
        self.status.setText("Разрешите доступ к микрофону в настройках системы." if denied else message)
        self.status.setToolTip(message)
        self.meter.setVisible(not denied)
        self.start_button.setVisible(not denied)
        self.start_button.setEnabled(True)
        self.timer.stop()

    def closeEvent(self, event):
        self.closed.emit()
        self.stop_event.set()
        self.timer.stop()
        super().closeEvent(event)
