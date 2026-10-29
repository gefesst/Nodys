"""Persistent voice controls in the secondary sidebar, without shrinking chat history."""
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QLabel,QGraphicsOpacityEffect,QApplication
from PySide6.QtCore import Property,QPropertyAnimation,QEasingCurve,Qt,QTimer
from .motion import reduced
from .tokens import LIST_WIDTH, RAIL_WIDTH
from .widgets import Button, set_voice_button_state

class VoiceDock(QFrame):
    def __init__(self, main):
        super().__init__(main)
        self.main=main
        self.setFixedSize(LIST_WIDTH-26,140)
        self.divider=QFrame(self);self.divider.setGeometry(0,0,LIST_WIDTH-26,1)
        self.divider.setStyleSheet('background:#354152;border:0;')
        card=QFrame(self);self.card=card;card.setObjectName('VoiceDock');card.setGeometry(0,20,LIST_WIDTH-26,112)
        card.setStyleSheet('QFrame#VoiceDock {background:#233449;border:1px solid #405A7C;border-radius:12px;}')
        layout=QVBoxLayout(card);layout.setContentsMargins(14,9,14,10);layout.setSpacing(2)
        self.title=Button('Голос','wave');self.title.setProperty('flat',True);self.title.setProperty('align_left',True)
        self.title.setMinimumHeight(0);self.title.setFixedHeight(24);self.title.clicked.connect(main.open_voice_surface)
        layout.addWidget(self.title)
        self.status=QLabel();self.status.setStyleSheet('font-size:12px;color:#67D5AD;')
        from .microphone_check import MicrophoneMeter
        self.meter=MicrophoneMeter(82,18)
        self._meter_source=None
        self.status.setFixedHeight(16)
        layout.addWidget(self.status)
        self.meter_timer=QTimer(self);self.meter_timer.setInterval(125);self.meter_timer.timeout.connect(self.update_meter)
        row=QHBoxLayout();row.setSpacing(12)
        self.participants=QLabel();self.participants.setStyleSheet('font-size:11px;color:#ACB9CC;');self.participants.setFixedHeight(16);layout.addWidget(self.participants)
        self.controls={}
        for name,symbol,callback in [('Микрофон','mic',self.toggle_mic),('Звук','headphones',self.toggle_sound),('Отключиться','end',main.end_voice_surface)]:
            button=Button('',symbol);button.setMinimumHeight(0);button.setFixedSize(32,28);button.setAccessibleName(name)
            self.controls[symbol]=button
            if symbol=='end':button.setProperty('danger',True)
            button.clicked.connect(callback);row.addWidget(button)
        row.addStretch(1)
        row.addWidget(self.meter)
        layout.addLayout(row)
        self._progress=0.0
        self._present=False
        self.opacity=QGraphicsOpacityEffect(self);self.setGraphicsEffect(self.opacity)
        self.animation=QPropertyAnimation(self,b"progress",self)
        self.animation.setDuration(180);self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.finished.connect(lambda:self.hide() if not self._present else None)
        self.hide()

    def set_status(self, text, reconnecting=False):
        self.status.setText(text)
        self.status.setStyleSheet("font-size:12px;color:"+("#EAC184" if reconnecting else "#67D5AD")+";")

    def toggle_mic(self):
        if self.main.call_window:self.main.call_window._mic_clicked()
        else:self.main.channels_page.toggle_voice_mute()
        self.sync_controls()

    def toggle_sound(self):
        if self.main.call_window:self.main.call_window._sound_clicked()
        else:self.main.channels_page.toggle_voice_deafen()
        self.sync_controls()

    def sync_controls(self):
        panel=getattr(self.main,"call_window",None)
        channel=self.main.channels_page
        muted=not panel.mic_enabled if panel else bool(getattr(channel,"_voice_muted",False))
        deafened=not panel.sound_enabled if panel else bool(getattr(channel,"_voice_deafened",False))
        if muted:self.meter.reset()
        for symbol,off,label in (("mic",muted,"Микрофон"),("headphones",deafened,"Звук")):
            button=self.controls[symbol]
            set_voice_button_state(button,symbol,not off)

    def update_meter(self):
        panel=getattr(self.main,"call_window",None)
        channel=self.main.channels_page
        source=getattr(self.main,"voice_client",None) if panel else getattr(channel,"_voice_client",None)
        muted=not panel.mic_enabled if panel else bool(getattr(channel,"_voice_muted",False))
        if source is not self._meter_source:
            self.meter.reset()
            self._meter_source=source
        if muted or source is None:
            self.meter.reset();return
        activity=source.get_activity() or {}
        if activity.get('quality')=='Переподключение':self.meter.reset()
        else:self.meter.setAudioLevel(float(activity.get('mic_level',0)))

    def get_progress(self):
        return self._progress

    def set_progress(self,value):
        self._progress=value
        self.opacity.setOpacity(value)
        for page in (self.main.chats_page,self.main.channels_page):
            page.voice_dock_space.setFixedHeight(round(152*value))
            page.voice_dock_space.setVisible(value>0)
        self.position()

    progress=Property(float,get_progress,set_progress)

    def set_present(self,visible):
        if visible==self._present:
            return
        self._present=visible
        self.meter.reset()
        if visible:
            self.update_meter();self.meter_timer.start()
        else:self.meter_timer.stop()
        if not visible:
            focused=QApplication.focusWidget()
            if focused is not None and (focused is self or self.isAncestorOf(focused)):
                # Move focus before hiding/removing controls from the tab chain.
                # Qt otherwise chooses the first focusable control in the window.
                self.main.stack.currentWidget().setFocus(Qt.OtherFocusReason)
        self.animation.stop()
        if visible:self.show()
        if reduced():
            self.set_progress(float(visible));self.setVisible(visible)
        else:
            self.animation.setStartValue(self._progress)
            self.animation.setEndValue(float(visible));self.animation.start()

    def position(self):
        narrow=hasattr(self.main,"stack") and self.main.stack.currentWidget() is self.main.channels_page
        width=196 if narrow else LIST_WIDTH-26
        self.setFixedWidth(width)
        self.divider.setFixedWidth(width)
        self.card.setGeometry(0,20,width,112)
        self.participants.setVisible(not narrow)
        self.move(RAIL_WIDTH+12 if narrow else RAIL_WIDTH+14,max(42,self.main.height()-154)+round(12*(1-self._progress)))
        self.raise_()
