"""Persistent voice controls in the secondary sidebar, without shrinking chat history."""
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QLabel,QGraphicsOpacityEffect
from PySide6.QtCore import Property,QPropertyAnimation,QEasingCurve
from .motion import reduced
from .widgets import Button

class VoiceDock(QFrame):
    def __init__(self, main):
        super().__init__(main)
        self.main=main
        self.setFixedSize(314,140)
        self.divider=QFrame(self);self.divider.setGeometry(0,0,314,1)
        self.divider.setStyleSheet('background:#354152;border:0;')
        card=QFrame(self);card.setObjectName('VoiceDock');card.setGeometry(0,20,314,112)
        card.setStyleSheet('QFrame#VoiceDock {background:#233449;border:1px solid #405A7C;border-radius:12px;}')
        layout=QVBoxLayout(card);layout.setContentsMargins(14,9,14,10);layout.setSpacing(2)
        self.title=Button('Голос','wave');self.title.setProperty('flat',True);self.title.setProperty('align_left',True)
        self.title.setMinimumHeight(0);self.title.setFixedHeight(27);self.title.clicked.connect(main.open_voice_surface)
        layout.addWidget(self.title)
        self.status=QLabel();self.status.setStyleSheet('font-size:12px;color:#67D5AD;');layout.addWidget(self.status)
        row=QHBoxLayout();row.setSpacing(12)
        self.participants=QLabel();self.participants.setStyleSheet('font-size:11px;color:#ACB9CC;');row.addWidget(self.participants,1)
        for name,symbol,callback in [('Микрофон','mic',self.toggle_mic),('Звук','headphones',self.toggle_sound),('Отключиться','end',main.end_voice_surface)]:
            button=Button('',symbol);button.setMinimumHeight(0);button.setFixedSize(32,28);button.setAccessibleName(name)
            if symbol=='end':button.setProperty('danger',True)
            button.clicked.connect(callback);row.addWidget(button)
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

    def toggle_sound(self):
        if self.main.call_window:self.main.call_window._sound_clicked()
        else:self.main.channels_page.toggle_voice_deafen()

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
        self.animation.stop()
        if visible:self.show()
        if reduced():
            self.set_progress(float(visible));self.setVisible(visible)
        else:
            self.animation.setStartValue(self._progress)
            self.animation.setEndValue(float(visible));self.animation.start()

    def position(self):
        self.move(102,max(42,self.main.height()-154)+round(12*(1-self._progress)))
        self.raise_()
