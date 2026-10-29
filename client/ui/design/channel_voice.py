"""Voice channel layout; the page owns signaling and audio state."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLabel,QScrollArea,QGridLayout,QSizePolicy,QSpacerItem
from .widgets import Button
from .state_surfaces import InlineNote


class VoiceNotice(QWidget):
    def __init__(self):
        super().__init__()
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,39)
        self.note=InlineNote()
        self.note.setFixedHeight(46)
        layout.addWidget(self.note)
        self.hide()

    def setText(self,text):
        self.note.setText(text)

    def text(self):
        return self.note.text()


def build(page):
    surface=QWidget()
    outer=QVBoxLayout(surface)
    outer.setContentsMargins(0,0,0,0)
    outer.setSpacing(12)
    tab=QWidget()
    page.voice_content=tab
    scroll=QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(tab)
    page.voice_surface_scroll=scroll
    outer.addWidget(scroll,1)
    layout=QVBoxLayout(tab)
    page.voice_tab_layout=layout
    layout.setContentsMargins(16,12,16,12)
    layout.setSpacing(0)
    title=QLabel('Участники голосового')
    title.setStyleSheet('font-size:20px;font-weight:600;')
    title.setFixedHeight(24)
    title.setParent(tab);title.hide()
    page.voice_members_count=QLabel('Нет участников')
    page.voice_members_count.setObjectName('Muted')
    page.voice_members_count.setStyleSheet("font-size:13px;color:#ACB9CC;")
    page.voice_members_count.setFixedHeight(16)
    page.voice_members_count.setParent(tab);page.voice_members_count.hide()
    page.voice_members_scroll=QScrollArea()
    page.voice_members_scroll.setWidgetResizable(True)
    page.voice_members_scroll.setMinimumHeight(225)
    page.voice_members_container=QWidget()
    page.voice_members_layout=QGridLayout(page.voice_members_container)
    page.voice_members_layout.setContentsMargins(0,0,0,0)
    page.voice_members_layout.setSpacing(20)
    page.voice_members_layout.setAlignment(Qt.AlignTop)
    page.voice_members_scroll.setWidget(page.voice_members_container)
    layout.addWidget(page.voice_members_scroll,1)
    controls=QFrame()
    controls.setObjectName('VoiceControls')
    controls.setFixedHeight(64)
    box=QVBoxLayout(controls)
    box.setContentsMargins(12,12,12,12)
    box.setSpacing(0)
    page.voice_status_lbl=QLabel('Вы не в голосовом канале')
    page.voice_status_lbl.setStyleSheet('font-size:16px;font-weight:600;')
    page.voice_status_lbl.setWordWrap(False)
    page.voice_status_lbl.setFixedHeight(20)
    from .microphone_check import MicrophoneMeter
    page.voice_meter=MicrophoneMeter(90,20)
    page.voice_meter.hide()
    row=QHBoxLayout();row.setSpacing(8)
    page.voice_mute_btn=Button('','mic')
    page.voice_mute_btn.setFixedSize(40,40)
    page.voice_mute_btn.clicked.connect(page.toggle_voice_mute)
    row.addWidget(page.voice_mute_btn)
    page.voice_deafen_btn=Button('','headphones')
    page.voice_deafen_btn.setFixedSize(40,40)
    page.voice_deafen_btn.clicked.connect(page.toggle_voice_deafen)
    row.addWidget(page.voice_deafen_btn)
    row.addWidget(page.voice_status_lbl,1)
    row.addWidget(page.voice_meter,0,Qt.AlignVCenter)
    page.voice_before_join=QSpacerItem(0,0,QSizePolicy.Fixed,QSizePolicy.Minimum)
    row.addItem(page.voice_before_join)
    page.voice_join_btn=Button('Войти в голосовой',primary=True)
    page.voice_join_btn.setFixedSize(200,40)
    page.voice_join_btn.clicked.connect(page.toggle_voice_join)
    row.addWidget(page.voice_join_btn)
    page.voice_after_join=QSpacerItem(0,0,QSizePolicy.Expanding,QSizePolicy.Minimum)
    row.addItem(page.voice_after_join)
    box.addLayout(row)
    page.voice_quality_lbl=VoiceNotice()
    layout.addWidget(page.voice_quality_lbl)
    page.voice_access_hint_lbl=VoiceNotice()
    layout.addWidget(page.voice_access_hint_lbl)
    page.voice_controls=controls
    page.voice_microphone_host=QWidget()
    page.voice_microphone_layout=QVBoxLayout(page.voice_microphone_host)
    page.voice_microphone_layout.setContentsMargins(0,0,0,33)
    page.voice_microphone_layout.setSpacing(0)
    page.voice_microphone_host.hide()
    layout.addWidget(page.voice_microphone_host)
    footer=QHBoxLayout()
    footer.setContentsMargins(0,0,0,0)
    footer.addWidget(controls)
    outer.addLayout(footer)
    return surface
