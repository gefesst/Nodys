from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QFrame,
)
from ui.avatar_widget import AvatarLabel
from ui.design.widgets import Button, RoundCallButton
from ui.design.motion import reduced


from ui.design.overlay import OverlayDialog


class CallPanel(OverlayDialog):
    """The approved call card, contained by the application window."""

    def __init__(self, parent=None):
        super().__init__(parent, 550, 650, anchor="call")
        self.setObjectName("CallPanel")
        self.setStyleSheet(
            "QDialog#CallPanel {background:#202C3B;border:1px solid #465772;border-radius:18px;}"
        )
        self.shade.mousePressEvent = lambda event: event.accept()

    def reject(self):
        self.close()


class ActiveCallWindow(CallPanel):
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
        self.dim = False
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
        self.setMinimumSize(360, 480)
        self.setObjectName("CallPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 32)
        root.setSpacing(0)

        def centered(text, name, height):
            label = QLabel(text)
            label.setObjectName(name)
            label.setAlignment(Qt.AlignCenter)
            label.setFixedHeight(height)
            root.addWidget(label)
            return label

        self.timer_lbl = centered("00:00", "CallTimer", 29)
        self.timer_lbl.setStyleSheet("font-size:23px;font-weight:600;")
        root.addSpacing(37)
        self.avatar = AvatarLabel(size=116)
        self.avatar.setProperty("voice_ring",True)
        self.avatar.set_avatar(
            path=self.peer_avatar, login=self.peer_login, nickname=self.peer_nickname
        )
        self.avatar.set_online(True)
        root.addWidget(self.avatar, 0, Qt.AlignHCenter)
        root.addSpacing(31)
        self.name_lbl = centered(self.peer_nickname, "CallPeerName", 30)
        self.name_lbl.setStyleSheet("font-size:25px;font-weight:600;")
        root.addSpacing(12)
        self.login_lbl = centered("@" + self.peer_login, "CallPeerLogin", 18)
        root.addSpacing(31)
        self.state_lbl = centered("Подключение…", "CallState", 22)
        root.addSpacing(24)
        self.quality_lbl = centered("Качество: —", "CallQuality", 17)
        self.speaking_lbl = QLabel(self)
        self.speaking_lbl.hide()
        self.quality_bars_lbl = QLabel(self)
        self.quality_bars_lbl.hide()
        from ui.design.microphone_check import MicrophoneMeter
        self.voice_meter=MicrophoneMeter(130,22)
        root.addSpacing(12)
        root.addWidget(self.voice_meter,0,Qt.AlignHCenter)
        root.addSpacing(14)
        btns=QHBoxLayout();btns.setSpacing(0);btns.setContentsMargins(5,0,5,0)
        self.btn_mic=RoundCallButton('Микрофон','mic')
        self.btn_sound=RoundCallButton('Звук','headphones')
        self.btn_end=RoundCallButton('Завершить','end',danger=True)
        from ui.design.widgets import set_voice_button_state
        set_voice_button_state(self.btn_mic,'mic',True)
        set_voice_button_state(self.btn_sound,'headphones',True)
        for button,label,callback in [
            (self.btn_mic,'Микрофон',self._mic_clicked),
            (self.btn_sound,'Звук',self._sound_clicked),
            (self.btn_end,'Завершить',self._end_clicked)]:
            column=QVBoxLayout();column.setSpacing(0)
            button.clicked.connect(callback)
            column.addWidget(button,0,Qt.AlignHCenter)
            column.addSpacing(9)
            caption=QLabel(label);caption.setAlignment(Qt.AlignCenter);caption.setFixedHeight(15)
            caption.setStyleSheet('font-size:12px;color:'+('#FFA7AE' if button is self.btn_end else '#ACB9CC')+';')
            column.addWidget(caption)
            btns.addLayout(column,1)
        root.addLayout(btns)
        root.addStretch()

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

        if not a:
            self.voice_meter.reset()
            return
        if not self.mic_enabled or a.get("quality")=="Переподключение":
            self.voice_meter.reset()
        else:
            self.voice_meter.setAudioLevel(float(a.get("mic_level",0)))
        me = bool(a.get("me_speaking")) and self.mic_enabled
        peer = bool(a.get("peer_speaking"))

        if peer and me:
            self.speaking_lbl.setText("Сейчас: говорите оба")
            self.state_lbl.setText("Двусторонний разговор")
            self.state_lbl.setStyleSheet(
                "color:#67D5AD; font-size:15px; font-weight:400;"
            )
        elif peer:
            self.speaking_lbl.setText(f"Сейчас говорит: {self.peer_nickname}")
            self.state_lbl.setText("Собеседник говорит")
            self.state_lbl.setStyleSheet(
                "color:#67D5AD; font-size:15px; font-weight:400;"
            )
        elif me:
            self.speaking_lbl.setText("Сейчас говорите: вы")
            self.state_lbl.setText("Вы говорите")
            self.state_lbl.setStyleSheet(
                "color:#91ADFF; font-size:15px; font-weight:400;"
            )
        else:
            self.speaking_lbl.setText("Сейчас: тишина")
            self.state_lbl.setText("Соединение активно")
            self.state_lbl.setStyleSheet(
                "color:#ACB9CC; font-size:15px; font-weight:400;"
            )

        quality = a.get("quality")
        lat = a.get("latency_ms")
        jit = a.get("jitter_ms")
        score = float(a.get("quality_score", 0.0) or 0.0)
        if quality is not None:
            self.quality_lbl.setText(f"Качество: {quality} · {lat} мс")
            if quality == "Переподключение":
                self.state_lbl.setText("Восстанавливаем соединение…")
                self.state_lbl.setStyleSheet("color:#EAC184;font-size:15px;")
            elif score < 50:
                self.state_lbl.setText("Связь нестабильна")
                self.state_lbl.setStyleSheet("color:#ACB9CC;font-size:15px;")
            bars, color = self._bars_for_quality(score)
            self.quality_bars_lbl.setText(bars)
            self.quality_bars_lbl.setStyleSheet(
                f"color:{color}; font-size:16px; font-weight:800; letter-spacing:2px;"
            )

        # style avatar state for pulse timer
        if peer:
            self._avatar_mode = "peer"
        elif me:
            self._avatar_mode = "me"
        else:
            self._avatar_mode = "idle"

    def _pulse_avatar(self):
        mode = getattr(self, "_avatar_mode", "idle")
        self._pulse = (self._pulse + 1) % 20
        self.avatar.setProperty("speaking", mode != "idle")
        self.avatar.setProperty(
            "pulse_alpha", 160 if reduced() else 100 + abs(10 - self._pulse) * 10
        )
        self.avatar.update()

    def _end_clicked(self):
        if getattr(self,"_end_requested",False):return
        self._end_requested=True
        if self.on_end:self.on_end()
        QTimer.singleShot(1000,lambda:setattr(self,"_end_requested",False))

    def _mic_clicked(self):
        self.mic_enabled = not self.mic_enabled
        if not self.mic_enabled:self.voice_meter.reset()
        from ui.design.widgets import set_voice_button_state
        set_voice_button_state(self.btn_mic,"mic",self.mic_enabled)
        if self.on_mic_toggle:
            self.on_mic_toggle(self.mic_enabled)

    def _sound_clicked(self):
        self.sound_enabled = not self.sound_enabled
        from ui.design.widgets import set_voice_button_state
        set_voice_button_state(self.btn_sound,"headphones",self.sound_enabled)
        if self.on_sound_toggle:
            self.on_sound_toggle(self.sound_enabled)

    def set_visual_state(self, state: str):
        """
        state: idle | me | peer | both
        """
        self.setProperty("talkState", state)
        self.update()
        # avatar accent
        if hasattr(self, "avatar_wrap"):
            self.avatar_wrap.setProperty("talkState", state)
            self.avatar_wrap.update()

    def closeEvent(self, event):
        if not self._ending:
            self._end_clicked()
            event.ignore()
            return
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


class OutgoingCallWindow(CallPanel):
    """Ringing state tied to the server call identity; cancelling is a real action."""

    def __init__(self, peer, cancel, parent=None):
        super().__init__(parent)
        self.cancel = cancel
        self.finished_by_server = False
        self.setWindowTitle("Исходящий звонок")
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 32)
        root.setSpacing(0)
        title = QLabel("Звоним…")
        self.heading = title
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:23px;font-weight:600;")
        title.setFixedHeight(29)
        root.addWidget(title)
        root.addSpacing(37)
        contact = next(
            (
                p
                for p in getattr(parent.friends_page, "_friends_data", [])
                if p.get("login") == peer
            ),
            {},
        )
        nickname = contact.get("nickname") or peer
        avatar = AvatarLabel(116)
        avatar.set_avatar(path=contact.get("avatar", ""), login=peer, nickname=nickname)
        root.addWidget(avatar, 0, Qt.AlignHCenter)
        root.addSpacing(31)
        name = QLabel(nickname)
        name.setAlignment(Qt.AlignCenter)
        name.setFixedHeight(30)
        name.setStyleSheet("font-size:25px;font-weight:600;")
        root.addWidget(name)
        root.addSpacing(12)
        login = QLabel("@" + peer)
        login.setAlignment(Qt.AlignCenter)
        login.setFixedHeight(18)
        login.setStyleSheet("font-size:14px;color:#ACB9CC;")
        root.addWidget(login)
        root.addSpacing(31)
        hint = QLabel("Ожидаем ответа")
        self.status_label = hint
        hint.setAlignment(Qt.AlignCenter)
        hint.setFixedHeight(22)
        hint.setStyleSheet("font-size:15px;color:#ACB9CC;")
        root.addWidget(hint)
        root.addSpacing(99)
        button = Button("Отменить")
        self.action_button = button
        button.setFixedSize(220, 40)
        button.setProperty("danger", True)
        button.clicked.connect(self.close)
        root.addWidget(button, 0, Qt.AlignHCenter)
        root.addStretch()

    def closeEvent(self, event):
        if not self.finished_by_server:
            if not getattr(self,"_cancel_requested",False):
                self._cancel_requested=True
                self.cancel()
                QTimer.singleShot(1000,lambda:setattr(self,"_cancel_requested",False))
            if not getattr(self,"close_on_cancel",False):
                self.status_label.setText("Отменяем вызов…")
                event.ignore()
                return
        event.accept()


class CallResultWindow(OutgoingCallWindow):
    """Terminal call state; closing this card never sends a signaling action."""
    def __init__(self, result, parent):
        super().__init__(result.get("peer", ""), lambda: None, parent)
        self.finished_by_server = True
        self.heading.setText(result.get("title", "Звонок завершён"))
        self.heading.setToolTip(result.get("detail", ""))
        self.heading.setWordWrap(True)
        self.heading.setMinimumHeight(29)
        self.heading.setMaximumHeight(60)
        self.status_label.setText("Аудиозвонок")
        self.action_button.setText("Закрыть")
        self.action_button.setProperty("danger", False)
