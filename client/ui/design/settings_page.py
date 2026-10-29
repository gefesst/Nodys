"""Real persisted preferences and read-only live audio diagnostics."""

import json
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QCheckBox,
    QPlainTextEdit,
    QHBoxLayout,
    QFrame,
    QScrollArea,
    QPushButton,
)
from config import load_config, save_config
from .widgets import Button, ScrollSafeComboBox


class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        from PySide6.QtWidgets import QStackedWidget
        from concurrent.futures import ThreadPoolExecutor

        self.preferences = load_config()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("SectionSidebar")
        sidebar.setFixedWidth(340)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 32, 20, 20)
        side.setSpacing(10)
        eyebrow = QLabel("ЛИЧНЫЕ")
        eyebrow.setObjectName("Eyebrow")
        eyebrow.setFixedHeight(12)
        side.addWidget(eyebrow)
        heading = QLabel("Настройки")
        heading.setObjectName("PageTitle")
        heading.setFixedHeight(31)
        side.addWidget(heading)
        side.addSpacing(18)
        self.panels = QStackedWidget()
        for text in ("Внешний вид", "Звук", "Подключение"):
            button = Button(text)
            button.setProperty("flat", True)
            button.setProperty("align_left", True)
            button.setFixedHeight(46)
            side.addWidget(button)
            button.clicked.connect(lambda checked=False, t=text: self.select_section(t))
        side.addStretch()
        outer.addWidget(sidebar)
        outer.addWidget(self.panels, 1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.panels.addWidget(self.scroll)
        content = QWidget()
        self.scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(40, 32, 40, 30)
        root.setSpacing(0)
        title = QLabel("Настройки приложения")
        title.setObjectName("FriendsTitle")
        title.setFixedHeight(34)
        root.addWidget(title)
        root.addSpacing(8)
        subtitle = QLabel("Оформление, звук и подключение")
        subtitle.setObjectName("FriendsSubtitle")
        subtitle.setFixedHeight(17)
        root.addWidget(subtitle)
        root.addSpacing(18)
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        root.addWidget(divider)
        root.addSpacing(53)
        fields = QVBoxLayout()
        fields.setContentsMargins(22, 0, 0, 0)
        fields.setSpacing(0)

        def label(text):
            widget = QLabel(text)
            widget.setObjectName("FieldTitle")
            widget.setFixedHeight(17)
            fields.addWidget(widget)
            fields.addSpacing(13)

        def combo():
            widget = ScrollSafeComboBox()
            widget.setMaximumWidth(720)
            fields.addWidget(widget)
            return widget

        label("Оформление")
        self.appearance = combo()
        self.appearance.addItem("Графит · 96% непрозрачности", True)
        self.appearance.addItem("Графит · непрозрачный фон", False)
        self.appearance.setCurrentIndex(
            0 if self.preferences.get("translucent_background", True) else 1
        )
        fields.addSpacing(32)
        sound = QLabel("Звук")
        sound.setObjectName("FieldHeading")
        sound.setFixedHeight(26)
        fields.addWidget(sound)
        fields.addSpacing(28)
        label("Микрофон")
        self.input_device = combo()
        self.input_device.addItem("Системное устройство", None)
        fields.addSpacing(23)
        label("Вывод звука")
        self.output_device = combo()
        self.output_device.addItem("Системное устройство", None)
        fields.addSpacing(50)
        self.microphone_button = Button("Проверьте микрофон перед разговором.", "mic")
        self.microphone_button.setFixedHeight(46)
        self.microphone_button.setMaximumWidth(860)
        self.microphone_button.clicked.connect(self.check_microphone)
        fields.addWidget(self.microphone_button)
        self.microphone_host=QWidget()
        self.microphone_layout=QVBoxLayout(self.microphone_host)
        self.microphone_layout.setContentsMargins(0,12,0,0)
        fields.addWidget(self.microphone_host)
        self.microphone_host.hide()
        fields.addSpacing(53)
        save = Button("Сохранить", primary=True)
        save.setFixedSize(170, 40)
        save.clicked.connect(self.save_preferences)
        fields.addWidget(save, 0, Qt.AlignLeft)
        self.saved_status = QLabel()
        self.saved_status.setObjectName("Muted")
        self.saved_status.setWordWrap(True)
        fields.addWidget(self.saved_status)
        root.addLayout(fields)
        root.addStretch()
        diagnostics_page = QWidget()
        self.panels.addWidget(diagnostics_page)
        details = QVBoxLayout(diagnostics_page)
        details.setContentsMargins(40, 32, 40, 30)
        details.setSpacing(20)
        diagnostic_title = QLabel("Подключение и диагностика")
        diagnostic_title.setObjectName("FriendsTitle")
        details.addWidget(diagnostic_title)
        self.reduce = QCheckBox("Уменьшить движение")
        self.reduce.setChecked(bool(self.preferences.get("reduce_motion", False)))
        self.reduce.toggled.connect(self.set_reduced_motion)
        details.addWidget(self.reduce)
        self.transparency = QCheckBox("Полупрозрачный фон (96%)")
        self.transparency.setChecked(
            self.preferences.get("translucent_background", True)
        )
        self.transparency.toggled.connect(self.set_transparency)
        details.addWidget(self.transparency)
        self.platform = QLabel()
        self.platform.setWordWrap(True)
        details.addWidget(self.platform)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMinimumHeight(160)
        self.diagnostics.setMaximumHeight(220)
        details.addWidget(self.diagnostics)
        copy = Button("Копировать диагностику", "copy")
        copy.clicked.connect(self.copy)
        details.addWidget(copy, 0, Qt.AlignLeft)
        details.addStretch()
        self.device_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="nodus-device-list"
        )
        self.device_future = self.device_executor.submit(self.enumerate_devices)
        self.device_executor.shutdown(wait=False)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    @staticmethod
    def enumerate_devices():
        import sounddevice as sd
        from audio.devices import list_devices

        return list_devices(sd)

    def select_section(self, section):
        self.panels.setCurrentIndex(1 if section == "Подключение" else 0)
        if section == "Звук":
            self.scroll.ensureWidgetVisible(self.input_device)
        elif section == "Внешний вид":
            self.scroll.verticalScrollBar().setValue(0)

    def save_preferences(self):
        save_config(
            {
                "audio_input_device": self.input_device.currentData(),
                "audio_output_device": self.output_device.currentData(),
            }
        )
        self.set_transparency(bool(self.appearance.currentData()))
        self.saved_status.setText(
            "Настройки сохранены. Устройства применятся при следующем подключении."
        )

    def stop_microphone_check(self):
        panel=getattr(self,'microphone_check',None)
        if panel is None:
            return True
        panel.close()
        self.microphone_host.hide()
        return not (panel.worker and panel.worker.is_alive())

    def check_microphone(self):
        if self.main.voice_client or getattr(
            self.main.channels_page, "_voice_client", None
        ):
            self.saved_status.setText(
                "Завершите голосовое подключение перед проверкой микрофона"
            )
            return
        from .microphone_check import MicrophoneCheck

        previous=getattr(self,'microphone_check',None)
        if previous is not None:
            previous.close()
            if previous.worker and previous.worker.is_alive():
                self.saved_status.setText('Проверка останавливается. Повторите через секунду.')
                return
            previous.deleteLater()
        channels=self.main.channels_page
        if channels.active_channel:
            self.main.show_channels()
            channels.close_channel_settings()
            channels.switch_to_voice_tab()
            self.microphone_check=MicrophoneCheck(channels.voice_microphone_host)
            channels.voice_content.setMinimumHeight(560)
            self.microphone_check.closed.connect(lambda:channels.voice_content.setMinimumHeight(0))
            self.microphone_check.closed.connect(channels.voice_microphone_host.hide)
            channels.voice_microphone_layout.addWidget(self.microphone_check)
            channels.voice_microphone_host.show()
        else:
            self.microphone_check=MicrophoneCheck(self.microphone_host)
            self.microphone_layout.addWidget(self.microphone_check)
            self.microphone_host.show()
        self.microphone_check.show()
        if not channels.active_channel:
            QTimer.singleShot(0,lambda:self.scroll.ensureWidgetVisible(self.microphone_check))

    def set_reduced_motion(self, value):
        from PySide6.QtWidgets import QApplication

        save_config({"reduce_motion": value})
        QApplication.instance().setProperty("reduce_motion", value)

    def set_transparency(self, value):
        save_config({"translucent_background": value})
        window = self.window()
        changed = window.property("translucent_background") != value
        window.setProperty("translucent_background", value)
        self.transparency.blockSignals(True)
        self.transparency.setChecked(value)
        self.transparency.blockSignals(False)
        self.appearance.setCurrentIndex(0 if value else 1)
        if changed:
            from .backdrop import install

            install(window)
        window.update()

    def refresh(self):
        if self.device_future is not None and self.device_future.done():
            future, self.device_future = self.device_future, None
            try:
                devices = future.result()
                for direction, combo in [
                    ("input", self.input_device),
                    ("output", self.output_device),
                ]:
                    selection = self.preferences.get("audio_" + direction + "_device")
                    for device in devices:
                        if device[direction]:
                            value = {"name": device["name"], "host": device["host"]}
                            combo.addItem(device["name"], value)
                            if value == selection:
                                combo.setCurrentIndex(combo.count() - 1)
                    if selection and combo.currentData() != selection:
                        combo.addItem(
                            selection.get("name", "Устройство") + " — недоступно",
                            selection,
                        )
                        combo.setCurrentIndex(combo.count() - 1)
            except Exception:
                self.saved_status.setText(
                    "Список устройств недоступен. Можно использовать системное устройство."
                )
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
