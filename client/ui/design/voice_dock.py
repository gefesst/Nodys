"""Persistent voice controls in the secondary sidebar, without shrinking chat history."""
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QLabel
from .widgets import Button

class VoiceDock(QFrame):
    def __init__(self, main):
        super().__init__(main)
        self.main=main
        self.setObjectName('VoiceDock')
        self.setFixedSize(314,112)
        self.setStyleSheet('QFrame#VoiceDock {background:#233449;border:1px solid #405A7C;border-radius:12px;}')
        layout=QVBoxLayout(self);layout.setContentsMargins(14,9,14,10);layout.setSpacing(2)
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
        self.hide()

    def toggle_mic(self):
        if self.main.call_window:self.main.call_window._mic_clicked()
        else:self.main.channels_page.toggle_voice_mute()

    def toggle_sound(self):
        if self.main.call_window:self.main.call_window._sound_clicked()
        else:self.main.channels_page.toggle_voice_deafen()

    def position(self):
        self.move(102,max(230,self.main.height()-211))
        self.raise_()
