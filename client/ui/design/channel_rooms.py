"""Room navigation and editing. Space membership remains owned by ChannelsPage."""
from PySide6.QtCore import Qt,QTimer,QVariantAnimation
from PySide6.QtGui import QPainter,QPen,QColor
from .motion import reduced
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QScrollArea,QLineEdit,QSizePolicy
from .widgets import Button,ElidedLabel
from .overlay import OverlayDialog


class OccupiedRoom(QWidget):
    """Reveal only the outline, keeping participant geometry stationary."""
    def __init__(self, animate=False):
        super().__init__()
        self.reveal=0.0 if animate and not reduced() else 1.0
        self.animation=QVariantAnimation(self)
        self.animation.setDuration(180)
        self.animation.setStartValue(0.0);self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._advance)
        if self.reveal==0:self.animation.start()

    def _advance(self,value):
        self.reveal=value;self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(0,0,self.width(),int(self.height()*self.reveal))
        painter.setPen(QPen(QColor('#354152'),1));painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1,1,-1,-1),10,10)


class RoomNavigationMixin:
    def build_room_navigation(self):
        self.text_room_id=0
        self.voice_room_id=1
        self.connected_voice_room_id=None
        self._rooms=[]
        self._rooms_cache={}
        self._rooms_manage=False
        self._rooms_loading=False
        self._rooms_revision=0
        self._rooms_signature=None
        self._room_avatars={}
        self._occupied_rooms=set()
        panel=QWidget();panel.setFixedWidth(180)
        panel.setObjectName('RoomNavigation')
        panel.setStyleSheet('QWidget#RoomNavigation {background:#1B2936;border:1px solid #354152;border-radius:12px;}')
        outer=QVBoxLayout(panel);outer.setContentsMargins(8,12,8,8);outer.setSpacing(10)
        self.rooms_scroll=QScrollArea();self.rooms_scroll.setWidgetResizable(True)
        self.rooms_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body=QWidget();self.rooms_layout=QVBoxLayout(body)
        self.rooms_layout.setContentsMargins(0,0,8,0);self.rooms_layout.setSpacing(5)
        self.rooms_scroll.setWidget(body);outer.addWidget(self.rooms_scroll)
        self.rooms_panel=panel
        self.room_poll=QTimer(self);self.room_poll.setInterval(2500)
        self.room_poll.timeout.connect(lambda:self.load_rooms() if self.isVisible() and self.active_channel else None)
        self.room_poll.start()
        return panel

    def load_rooms(self,force=False):
        cid=self._active_channel_id()
        if not cid or not self._alive or self._rooms_loading and not force:return
        self._rooms_revision+=1;revision=self._rooms_revision
        token=self.ctx.session_token
        self._rooms_loading=True
        def done(response):
            if revision!=self._rooms_revision or cid!=self._active_channel_id() or token!=self.ctx.session_token:return
            self._rooms_loading=False
            if response.get('status')!='ok':
                if force:self.show_toast(response.get('message','Не удалось загрузить каналы'))
                return
            self._rooms=response.get('rooms',[])
            self._rooms_manage=bool(response.get('can_manage'))
            self._rooms_cache[cid]=(self._rooms,self._rooms_manage)
            self.conversation.prefetch([(cid,r['id']) for r in self._rooms if r['kind']=='text'])
            self.render_rooms()
        self.start_request(dict(action='get_channel_rooms',channel_id=cid),done)

    def render_rooms(self):
        selected=('text',self.text_room_id) if self.channel_inner_stack.currentIndex()==0 else ('voice',self.voice_room_id)
        for room in self._rooms:
            if (room['kind'],room['id'])==selected:self.room_title.setText(('# ' if room['kind']=='text' else 'Голосовой · ')+room['name'])
        rooms=[dict(r) for r in self._rooms]
        for room in rooms:
            if room['kind']=='voice' and room['id']==self.voice_room_id:
                room['participants']=self._voice_participants
            # Server list snapshots can arrive after leave or after selecting another room.
            # Only the locally confirmed connection may display our own membership.
            room['participants']=[p for p in room.get('participants',[]) if p.get('login')!=self.ctx.login or (self._voice_joined and room['id']==self.connected_room_id())]
        for room in rooms:
            if self._voice_joined and room['id']==self.connected_room_id():
                people=list(room.get('participants',[]))
                if not any(p.get('login')==self.ctx.login for p in people):
                    people.append(dict(login=self.ctx.login,nickname=self.ctx.nickname or self.ctx.login,avatar=self.ctx.avatar or ''))
                if self._voice_client is not None:
                    speaking=bool(self._voice_client.get_activity().get('me_speaking',False)) and not self._voice_muted
                    people=[dict(p,speaking=speaking) if p.get('login')==self.ctx.login else p for p in people]
                room['participants']=people
        for room in rooms:
            for person in room.get('participants',[]):
                avatar=self._room_avatars.get((room['id'],person['login']))
                if avatar:
                    avatar.setProperty('speaking',bool(person.get('speaking')));avatar.update()
        signature=repr(([dict(r,participants=[{k:v for k,v in p.items() if k!='speaking'} for p in r.get('participants',[])]) for r in rooms],self._rooms_manage,selected,self._voice_joined,self.voice_room_id))
        if signature==self._rooms_signature:return
        self._rooms_signature=signature
        self._room_avatars={}
        occupied={(r["id"]) for r in rooms if r.get("participants")}
        newly_occupied=occupied-self._occupied_rooms
        self._occupied_rooms=occupied
        scroll_position=self.rooms_scroll.verticalScrollBar().value()
        while self.rooms_layout.count():
            item=self.rooms_layout.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
        for kind,title in [('text','Текстовые'),('voice','Голосовые')]:
            heading=QWidget();row=QHBoxLayout(heading);row.setContentsMargins(4,12,0,4)
            label=QLabel(title);label.setStyleSheet('font-size:12px;color:#9BAFC6;font-weight:600;');row.addWidget(label,1)
            add=Button('+');add.setMinimumWidth(0);add.setFixedSize(24,26);add.setProperty('flat',True);add.setAccessibleName('Создать '+('текстовый' if kind=='text' else 'голосовой')+' канал')
            add.setVisible(self._rooms_manage);add.clicked.connect(lambda _,k=kind:self.edit_room_dialog(kind=k));row.addWidget(add)
            self.rooms_layout.addWidget(heading)
            divider=QWidget();divider.setFixedHeight(1);divider.setStyleSheet('background:#354152;')
            self.rooms_layout.addWidget(divider)
            for room in (r for r in rooms if r['kind']==kind):
                container=QWidget();line=QHBoxLayout(container);line.setContentsMargins(0,0,0,0);line.setSpacing(2)
                button=Button(room['name'],'hash' if kind=='text' else 'wave',primary=selected==(kind,room['id']))
                button.setMinimumWidth(0);button.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed);button.setFixedHeight(34);button.setProperty('flat',True);button.setProperty('align_left',True)
                button.setAccessibleName(('Текстовый ' if kind=='text' else 'Голосовой ')+room['name'])
                button.clicked.connect(lambda _,r=dict(room):self.select_room(r))
                group=OccupiedRoom(room['id'] in newly_occupied) if room.get('participants') else QWidget()
                group_layout=QVBoxLayout(group);group_layout.setContentsMargins(0,0,0,6 if room.get('participants') else 0);group_layout.setSpacing(3)
                group_layout.addWidget(button)
                line.addWidget(group,1)
                if self._rooms_manage:
                    edit=Button('⋯');edit.setMinimumWidth(0);edit.setFixedSize(22,34);edit.setProperty('flat',True);edit.setAccessibleName('Переименовать '+room['name'])
                    edit.clicked.connect(lambda _,r=dict(room):self.edit_room_dialog(room=r));line.addWidget(edit,0,Qt.AlignTop)
                self.rooms_layout.addWidget(container)
                for person in room.get('participants',[]):
                    from ui.avatar_widget import AvatarLabel
                    member=QWidget();member_row=QHBoxLayout(member);member_row.setContentsMargins(20,2,0,2);member_row.setSpacing(6)
                    avatar=AvatarLabel(20);avatar.set_avatar(person.get('avatar',''),login=person['login'],nickname=person.get('nickname',person['login']))
                    avatar.setProperty('speaking',bool(person.get('speaking')))
                    self._room_avatars[(room['id'],person['login'])]=avatar
                    member_row.addWidget(avatar)
                    name=ElidedLabel(person.get('nickname',person['login']))
                    name.setStyleSheet('font-size:11px;color:#A9B8CD;')
                    member_row.addWidget(name,1);group_layout.addWidget(member)
        self.rooms_layout.addStretch()
        self.rooms_layout.activate()
        self.rooms_scroll.verticalScrollBar().setValue(scroll_position)

    def select_room(self,room):
        if room['kind']=='text':
            self.text_room_id=room['id'];self.switch_to_text_tab()
        else:
            if self.voice_room_id!=room['id']:
                self.voice_room_id=room['id']
                self._voice_participants=[p for p in room.get('participants',[]) if p.get('login')!=self.ctx.login];self._voice_participants_signature=''
                self._render_voice_participants()
            self.switch_to_voice_tab()
        self.room_title.setText(('# ' if room['kind']=='text' else 'Голосовой · ')+room['name'])
        self.render_rooms()
        main=getattr(self,"_main_window",None)
        if main is not None:main.refresh_voice_dock()

    def connected_room_id(self):
        return self.connected_voice_room_id if self.connected_voice_room_id is not None else self.voice_room_id

    def viewing_connected_room(self):
        return self._voice_joined and self.voice_room_id==self.connected_room_id()

    def edit_room_dialog(self,kind='text',room=None):
        cid=self._active_channel_id();token=self.ctx.session_token
        if not cid or not self._rooms_manage:return
        dialog=OverlayDialog(self,460,260,anchor='modal')
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        layout=QVBoxLayout(dialog);layout.setContentsMargins(28,24,28,24);layout.setSpacing(16)
        title=QLabel('Переименовать канал' if room else ('Новый текстовый канал' if kind=='text' else 'Новый голосовой канал'))
        title.setWordWrap(True);title.setStyleSheet('font-size:20px;font-weight:600;');layout.addWidget(title)
        field=QLineEdit(room['name'] if room else '');field.setMaxLength(64);field.setPlaceholderText('Название канала');layout.addWidget(field)
        feedback=QLabel();feedback.setWordWrap(True);feedback.setStyleSheet('color:#FF9C9C;font-size:12px;');layout.addWidget(feedback)
        actions=QHBoxLayout();cancel=Button('Отмена');save=Button('Сохранить' if room else 'Создать',primary=True);actions.addWidget(cancel);actions.addWidget(save);layout.addLayout(actions)
        cancel.clicked.connect(dialog.reject)
        def submit():
            if not save.isEnabled():return
            if not field.text().strip():feedback.setText('Введите название');return
            save.setEnabled(False)
            payload=dict(action='rename_channel_room' if room else 'create_channel_room',channel_id=cid,name=field.text().strip())
            if room:payload['room_id']=room['id']
            else:payload['kind']=kind
            def done(response):
                from shiboken6 import isValid
                if token!=self.ctx.session_token:return
                if response.get('status')=='ok':
                    if isValid(dialog):dialog.accept()
                    if cid==self._active_channel_id():self.load_rooms(force=True)
                elif isValid(dialog):
                    save.setEnabled(True);feedback.setText(response.get('message','Не удалось сохранить'))
            self.start_request(payload,done)
        save.clicked.connect(submit);field.returnPressed.connect(submit)
        self._room_editor=dialog;dialog.open();field.setFocus()
