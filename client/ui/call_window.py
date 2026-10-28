from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame
from ui.avatar_widget import AvatarLabel
from ui.design.widgets import Button
from ui.design.motion import reduced


class ActiveCallWindow(QDialog):
    def __init__(
        self,
        my_login: str,
        peer_login: str,
        peer_nickname: str = "",
        peer_avatar: str = "",
        on_end=None,
        on_mic_toggle=None,
        on_sound_toggle=None,
        activity_provider=None,
        parent=None,
    ):
        super().__init__(parent)
        self.my_login = my_login
        self.peer_login = peer_login
        self.peer_nickname = peer_nickname or peer_login
        self.peer_avatar = peer_avatar or ""
        self.on_end = on_end
        self.on_mic_toggle = on_mic_toggle
        self.on_sound_toggle = on_sound_toggle
        self.activity_provider = activity_provider

        self.mic_enabled = True
        self.sound_enabled = True
        self._ending = False
        self._seconds = 0
        self._pulse = 0
        self._pulse_dir = 1

        self.setWindowTitle("Активный звонок")
        self.setModal(False)
        self.setMinimumSize(480, 590)
        self.setObjectName("ActiveCallWindow")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        card = QFrame()
        card.setObjectName("CallCard")
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(18, 18, 18, 18)
        card_l.setSpacing(10)

        title = QLabel("Идёт звонок")
        title.setObjectName("CallTitle")
        title.setAlignment(Qt.AlignCenter)
        card_l.addWidget(title)

        self.timer_lbl = QLabel("00:00")
        self.timer_lbl.setObjectName("CallTimer")
        self.timer_lbl.setAlignment(Qt.AlignCenter)
        card_l.addWidget(self.timer_lbl)

        self.avatar = AvatarLabel(size=120)
        self.avatar.set_avatar(path=self.peer_avatar, login=self.peer_login, nickname=self.peer_nickname)
        self.avatar.set_online(True, ring_color="#2b2d31")
        card_l.addWidget(self.avatar, alignment=Qt.AlignHCenter)

        self.name_lbl = QLabel(self.peer_nickname)
        self.name_lbl.setObjectName("CallPeerName")
        self.name_lbl.setAlignment(Qt.AlignCenter)
        card_l.addWidget(self.name_lbl)

        self.login_lbl = QLabel(self.peer_login)
        self.login_lbl.setObjectName("CallPeerLogin")
        self.login_lbl.setAlignment(Qt.AlignCenter)
        card_l.addWidget(self.login_lbl)

        self.state_lbl = QLabel("Подключение...")
        self.state_lbl.setObjectName("CallState")
        self.state_lbl.setAlignment(Qt.AlignCenter)
        card_l.addWidget(self.state_lbl)

        self.speaking_lbl = QLabel("Сейчас: тишина")
        self.speaking_lbl.setObjectName("CallSpeaking")
        self.speaking_lbl.setAlignment(Qt.AlignCenter)
        card_l.addWidget(self.speaking_lbl)

        self.quality_lbl = QLabel("Качество: —")
        self.quality_lbl.setObjectName("CallQuality")
        self.quality_lbl.setAlignment(Qt.AlignCenter)
        card_l.addWidget(self.quality_lbl)

        self.quality_bars_lbl = QLabel("▂▄▆█")
        self.quality_bars_lbl.setObjectName("CallQualityBars")
        self.quality_bars_lbl.setAlignment(Qt.AlignCenter)
        card_l.addWidget(self.quality_bars_lbl)

        root.addWidget(card, 1)

        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_end = Button('', 'end')
        self.btn_end.setObjectName("CallRoundEndButton")
        self.btn_end.clicked.connect(self._end_clicked)

        self.btn_mic = Button('', 'mic')
        self.btn_mic.setObjectName("CallRoundControlButton")
        self.btn_mic.clicked.connect(self._mic_clicked)

        self.btn_sound = Button('', 'headphones')
        self.btn_sound.setObjectName("CallRoundControlButton")
        self.btn_sound.clicked.connect(self._sound_clicked)


        for b in (self.btn_end, self.btn_mic, self.btn_sound):
            b.setFixedSize(56, 56)
        self.btn_end.setToolTip("Завершить звонок")
        self.btn_mic.setToolTip("Микрофон")
        self.btn_sound.setToolTip("Звук")
        btns.addWidget(self.btn_end)
        btns.addWidget(self.btn_mic)
        btns.addWidget(self.btn_sound)
        root.addLayout(btns)

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)

        self._activity_timer = QTimer(self)
        self._activity_timer.timeout.connect(self._update_activity)
        self._activity_timer.start(180)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_avatar)
        self._pulse_timer.start(70)

    def _tick(self):
        self._seconds += 1
        mm = self._seconds // 60
        ss = self._seconds % 60
        self.timer_lbl.setText(f"{mm:02d}:{ss:02d}")

    def _bars_for_quality(self, quality_score: float):
        if quality_score >= 75:
            return "▁▃▅█", "#67D5AD"
        if quality_score >= 50:
            return "▁▃▅▆", "#ACB9CC"
        if quality_score >= 30:
            return "▁▂▄▅", "#faa61a"
        return "▁▂▃▄", "#f04747"

    def _update_activity(self):
        if not callable(self.activity_provider):
            return
        try:
            a = self.activity_provider() or {}
        except Exception:
            return

        me = bool(a.get("me_speaking"))
        peer = bool(a.get("peer_speaking"))

        if peer and me:
            self.speaking_lbl.setText("Сейчас: говорите оба")
            self.state_lbl.setText("Двусторонний разговор")
            self.state_lbl.setStyleSheet("color:#67D5AD; font-size:12px; font-weight:700;")
        elif peer:
            self.speaking_lbl.setText(f"Сейчас говорит: {self.peer_nickname}")
            self.state_lbl.setText("Собеседник говорит")
            self.state_lbl.setStyleSheet("color:#67D5AD; font-size:12px; font-weight:700;")
        elif me:
            self.speaking_lbl.setText("Сейчас говорите: вы")
            self.state_lbl.setText("Вы говорите")
            self.state_lbl.setStyleSheet("color:#91ADFF; font-size:12px; font-weight:700;")
        else:
            self.speaking_lbl.setText("Сейчас: тишина")
            self.state_lbl.setText("Соединение активно")
            self.state_lbl.setStyleSheet("color:#ACB9CC; font-size:12px; font-weight:700;")

        quality = a.get("quality")
        lat = a.get("latency_ms")
        jit = a.get("jitter_ms")
        score = float(a.get("quality_score", 0.0) or 0.0)
        if quality is not None:
            self.quality_lbl.setText(f"Качество: {quality} • ping {lat} ms • jitter {jit} ms")
            bars, color = self._bars_for_quality(score)
            self.quality_bars_lbl.setText(bars)
            self.quality_bars_lbl.setStyleSheet(f"color:{color}; font-size:16px; font-weight:800; letter-spacing:2px;")

        # style avatar state for pulse timer
        if peer:
            self._avatar_mode = "peer"
        elif me:
            self._avatar_mode = "me"
        else:
            self._avatar_mode = "idle"

    def _pulse_avatar(self):
        mode = getattr(self, '_avatar_mode', 'idle')
        self._pulse = (self._pulse + 1) % 20
        self.avatar.setProperty('speaking', mode != 'idle')
        self.avatar.setProperty('pulse_alpha', 160 if reduced() else 100 + abs(10-self._pulse)*10)
        self.avatar.update()

    def _end_clicked(self):
        self._ending = True
        if self.on_end:
            self.on_end()
        self.close()

    def _mic_clicked(self):
        self.mic_enabled = not self.mic_enabled
        self.btn_mic.setToolTip("Выключить микрофон" if self.mic_enabled else "Включить микрофон")
        self.btn_mic.primary = not self.mic_enabled
        self.btn_mic.update()
        self.btn_mic.setProperty("off", "false" if self.mic_enabled else "true")
        self.btn_mic.style().unpolish(self.btn_mic)
        self.btn_mic.style().polish(self.btn_mic)
        if self.on_mic_toggle:
            self.on_mic_toggle(self.mic_enabled)

    def _sound_clicked(self):
        self.sound_enabled = not self.sound_enabled
        self.btn_sound.setToolTip("Выключить звук" if self.sound_enabled else "Включить звук")
        self.btn_sound.primary = not self.sound_enabled
        self.btn_sound.update()
        self.btn_sound.setProperty("off", "false" if self.sound_enabled else "true")
        self.btn_sound.style().unpolish(self.btn_sound)
        self.btn_sound.style().polish(self.btn_sound)
        if self.on_sound_toggle:
            self.on_sound_toggle(self.sound_enabled)
    def set_visual_state(self, state: str):
        """
        state: idle | me | peer | both
        """
        self.setProperty("talkState", state)
        self.style().unpolish(self)
        self.style().polish(self)
        # avatar accent
        if hasattr(self, "avatar_wrap"):
            self.avatar_wrap.setProperty("talkState", state)
            self.avatar_wrap.style().unpolish(self.avatar_wrap)
            self.avatar_wrap.style().polish(self.avatar_wrap)


    def closeEvent(self, event):
        try:
            self._tick_timer.stop()
            self._activity_timer.stop()
            self._pulse_timer.stop()
        except Exception:
            pass
        try:
            if (not self._ending) and self.on_end:
                self.on_end()
        except Exception:
            pass
        event.accept()

class OutgoingCallWindow(QDialog):
    """Ringing state tied to the server call identity; cancelling is a real action."""
    def __init__(self, peer, cancel, parent=None):
        super().__init__(parent)
        self.cancel = cancel
        self.finished_by_server = False
        self.setWindowTitle('Исходящий звонок')
        self.resize(440, 370)
        root = QVBoxLayout(self)
        root.setContentsMargins(32,32,32,32)
        avatar = AvatarLabel(96)
        avatar.set_avatar(login=peer, nickname=peer)
        root.addWidget(avatar,0,Qt.AlignCenter)
        name = QLabel(peer);name.setObjectName('CallPeerName');name.setAlignment(Qt.AlignCenter)
        root.addWidget(name)
        hint = QLabel('Вызываем…');hint.setAlignment(Qt.AlignCenter);root.addWidget(hint)
        button = Button('Отменить звонок','end');button.clicked.connect(self.close);root.addWidget(button)
    def closeEvent(self,event):
        if not self.finished_by_server:
            self.cancel()
        event.accept()
