"""Opt-in level check. Audio samples are never stored, sent, or played back."""

import threading
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
from .widgets import Button


class MeterSignals(QObject):
    error = Signal(str)
    ready = Signal()
    finished = Signal()


class MicrophoneCheck(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Проверка микрофона")
        self.resize(460, 260)
        self.stop_event = threading.Event()
        self.level = 0
        self.worker = None
        self.signals = MeterSignals(self)
        self.signals.error.connect(self.failed)
        self.signals.finished.connect(self.completed)
        self.signals.ready.connect(
            lambda: self.status.setText("Говорите: отображается только уровень сигнала")
        )
        root = QVBoxLayout(self)
        self.status = QLabel(
            "Проверка начинается только по кнопке. Звук не сохраняется и не передаётся."
        )
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        root.addWidget(self.meter)
        self.start_button = Button("Начать проверку", "mic", True)
        self.start_button.clicked.connect(self.start)
        root.addWidget(self.start_button)
        stop = Button("Остановить и закрыть")
        stop.clicked.connect(self.close)
        root.addWidget(stop)
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
