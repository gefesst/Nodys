"""Real persisted preferences and read-only live audio diagnostics."""

import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QPlainTextEdit
from config import load_config, save_config
from .widgets import Button


class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 28)
        title = QLabel("Настройки приложения")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        root.addWidget(QLabel("Внешний вид и диагностика текущего подключения"))
        self.reduce = QCheckBox("Уменьшить движение")
        self.reduce.setChecked(bool(load_config().get("reduce_motion", False)))
        self.reduce.toggled.connect(self.set_reduced_motion)
        root.addWidget(self.reduce)
        self.transparency = QCheckBox("Полупрозрачный фон (96%)")
        self.transparency.setChecked(load_config().get("translucent_background", True))
        self.transparency.toggled.connect(self.set_transparency)
        root.addWidget(self.transparency)
        self.platform = QLabel("Размытие: безопасное оформление без системного blur")
        self.platform.setWordWrap(True)
        root.addWidget(self.platform)
        root.addWidget(
            QLabel("Аудиодиагностика · счётчики текущего сеанса, без записи звука")
        )
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        root.addWidget(self.diagnostics, 1)
        copy = Button("Копировать диагностику", "copy")
        copy.clicked.connect(self.copy)
        root.addWidget(copy)
        microphone = Button("Проверить микрофон", "mic")
        microphone.clicked.connect(self.check_microphone)
        root.addWidget(microphone)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def check_microphone(self):
        if self.main.voice_client or getattr(
            self.main.channels_page, "_voice_client", None
        ):
            self.platform.setText(
                "Завершите голосовое подключение перед проверкой микрофона"
            )
            return
        from .microphone_check import MicrophoneCheck

        self.microphone_check = MicrophoneCheck(self)
        self.microphone_check.show()

    def set_reduced_motion(self, value):
        from PySide6.QtWidgets import QApplication

        save_config({"reduce_motion": value})
        QApplication.instance().setProperty("reduce_motion", value)

    def set_transparency(self, value):
        save_config({"translucent_background": value})
        self.window().setProperty("translucent_background", value)
        self.window().update()

    def refresh(self):
        session = self.main.voice_client or getattr(
            self.main.channels_page, "_voice_client", None
        )
        data = (
            session.get_diagnostics()
            if session and hasattr(session, "get_diagnostics")
            else {"state": "Голосовое подключение не активно"}
        )
        self.diagnostics.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
        self.platform.setText(
            getattr(
                self.window(),
                "backdrop_description",
                "Размытие: безопасное оформление без системного blur",
            )
        )

    def copy(self):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.diagnostics.toPlainText())
