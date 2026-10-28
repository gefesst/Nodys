"""Real persisted preferences and read-only live audio diagnostics."""

import json
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QPlainTextEdit, QHBoxLayout, QFrame, QScrollArea, QPushButton
from config import load_config, save_config
from .widgets import Button


class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        outer=QHBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName('SectionSidebar');sidebar.setFixedWidth(340)
        side=QVBoxLayout(sidebar);side.setContentsMargins(22,32,20,20);side.setSpacing(12)
        eyebrow=QLabel('ПРИЛОЖЕНИЕ');eyebrow.setObjectName('Eyebrow');side.addWidget(eyebrow)
        heading=QLabel('Настройки');heading.setObjectName('PageTitle');side.addWidget(heading)
        side.addSpacing(14)
        for text in ('Внешний вид', 'Звук', 'Диагностика'):
            button=QPushButton(text);button.setObjectName('SectionTab');side.addWidget(button)
            button.clicked.connect(lambda checked=False,t=text:self.scroll.ensureWidgetVisible(self.reduce if t=='Внешний вид' else self.diagnostics))
        side.addStretch();outer.addWidget(sidebar)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);outer.addWidget(self.scroll,1)
        content=QWidget();self.scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setSpacing(20)
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
        self.diagnostics.setMinimumHeight(160)
        self.diagnostics.setMaximumHeight(220)
        root.addWidget(self.diagnostics)
        copy = Button("Копировать диагностику", "copy")
        copy.clicked.connect(self.copy)
        root.addWidget(copy,0,Qt.AlignLeft)
        microphone = Button("Проверить микрофон", "mic")
        microphone.clicked.connect(self.check_microphone)
        root.addWidget(microphone,0,Qt.AlignLeft)
        root.addStretch()
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
