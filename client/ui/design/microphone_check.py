"""Opt-in level check. Audio samples are never stored, sent, or played back."""

import threading
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from .widgets import Button


class MeterSignals(QObject):
    error = Signal(str)
    ready = Signal()
    finished = Signal()


class MicrophoneCheck(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Проверка микрофона")
        self.setObjectName("MicrophoneCheck")
        self.setMinimumHeight(105)
        self.setStyleSheet("QFrame#MicrophoneCheck {background:#202D3D;border:1px solid #354152;border-radius:12px;}")
        self.stop_event = threading.Event()
        self.level = 0
        self.worker = None
        self.signals = MeterSignals(self)
        self.signals.error.connect(self.failed)
        self.signals.finished.connect(self.completed)
        self.signals.ready.connect(
            lambda: self.status.setText("Говорите: отображается только уровень сигнала")
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(22,16,18,16)
        root.setSpacing(16)
        column=QVBoxLayout();column.setSpacing(8)
        self.title=QLabel('Проверка микрофона')
        self.title.setStyleSheet('font-size:16px;font-weight:600;')
        column.addWidget(self.title)
        self.status=QLabel('Проверка начинается по кнопке. Звук не сохраняется и не передаётся.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('font-size:13px;color:#ACB9CC;')
        column.addWidget(self.status)
        root.addLayout(column,1)
        self.meter=QProgressBar();self.meter.setRange(0,100);self.meter.setTextVisible(False)
        self.meter.setFixedSize(140,12)
        self.meter.setStyleSheet('QProgressBar {background:#354152;border:0;border-radius:6px;} QProgressBar::chunk {background:#67D5AD;border-radius:6px;}')
        root.addWidget(self.meter)
        self.start_button=Button('Проверить',primary=True)
        self.start_button.setFixedSize(120,40)
        self.start_button.clicked.connect(self.start)
        root.addWidget(self.start_button)
        stop=Button('', 'close');stop.setFixedSize(28,28);stop.setAccessibleName('Остановить проверку микрофона')
        stop.clicked.connect(self.close);root.addWidget(stop)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(lambda: self.meter.setValue(self.level))

    def start(self):
        if self.worker and self.worker.is_alive():
            return
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
        if not self.stop_event.is_set() and not self.status.text().startswith(
            "Микрофон недоступен"
        ):
            self.status.setText("Проверка завершена. Звук не сохранялся.")

    def hideEvent(self, event):
        self.stop_event.set()
        self.timer.stop()
        super().hideEvent(event)

    def failed(self, message):
        self.status.setText(message)
        self.start_button.setEnabled(True)
        self.timer.stop()

    def closeEvent(self, event):
        self.stop_event.set()
        self.timer.stop()
        super().closeEvent(event)
