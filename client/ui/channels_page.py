from application.avatars import encode_avatar
from application.request_scope import RequestScope
from application.sequence import clock as voice_sequence
import time
from functools import partial

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QLineEdit,
    QScrollArea,
    QStackedWidget,
    QFileDialog,
    QComboBox,
    QMenu,
    QSizePolicy,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer, QSignalBlocker

from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel
from ui.micro_interactions import install_opacity_feedback
from ui.toast import InlineToast
from application.voice_session import VoiceSession
from settings import get_voice_endpoint

from ui.design.motion import TransitionStack as QStackedWidget


def participants_text(count):
    count=int(count)
    suffix='участник' if count%10==1 and count%100!=11 else 'участника' if count%10 in (2,3,4) and count%100 not in (12,13,14) else 'участников'
    return f'{count} {suffix}'


class ChannelListItem(QFrame):
    def __init__(self, channel: dict, active: bool = False, on_click=None):
        super().__init__()
        self.channel = channel or {}
        self._on_click = on_click

        self.setObjectName("ChannelListItem")
        self.setProperty("active", bool(active))
        self.setFixedHeight(70)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(12)

        avatar = AvatarLabel(size=40)
        avatar.set_avatar(
            path=self.channel.get("avatar", ""),
            login=f"channel_{self.channel.get('id', '')}",
            nickname=self.channel.get("name", "Канал"),
        )
        avatar.set_online(None, ring_color="#2b2d31")
        lay.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        name = QLabel(self.channel.get("name", "Без названия"))
        name.setObjectName("ChannelListItemName")
        name.setMinimumWidth(0)
        name.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        text_col.addWidget(name)

        role = (self.channel.get("my_role") or "member").strip().lower()
        if role == "owner":
            role_text = "Владелец"
        elif role == "admin":
            role_text = "Админ"
        elif role == "moderator":
            role_text = "Модератор"
        else:
            role_text = "Участник"

        participants_count = int(
            self.channel.get("participants_count")
            or self.channel.get("members_count")
            or 0
        )
        sub = QLabel(participants_text(participants_count))
        self.setToolTip(role_text)
        sub.setObjectName("ChannelListItemSub")
        text_col.addWidget(sub)

        lay.addLayout(text_col, 1)

    def mousePressEvent(self, event):
        if callable(self._on_click):
            self._on_click()
        super().mousePressEvent(event)


class ChannelMessageBubble(QFrame):
    def __init__(self, text: str, author: str, is_outgoing: bool = False, time_text: str = ""):
        super().__init__()
        self.setObjectName("ChannelMessageRow")
        self.setProperty("outgoing", "true" if is_outgoing else "false")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 6)
        row.setSpacing(8)

        avatar = AvatarLabel(size=32)
        avatar.set_avatar(path="", login=author or "user", nickname=author or "Пользователь")
        avatar.set_online(None)

        card = QFrame()
        card.setObjectName("ChannelMsgCard")
        card.setProperty("outgoing", "true" if is_outgoing else "false")

        col = QVBoxLayout(card)
        col.setContentsMargins(12, 9, 12, 9)
        col.setSpacing(5)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)

        author_lbl = QLabel(author)
        author_lbl.setObjectName("ChannelMsgAuthor")
        head.addWidget(author_lbl)

        head.addStretch(1)

        if time_text:
            meta = QLabel(time_text)
            meta.setObjectName("ChannelMsgMeta")
            head.addWidget(meta)

        col.addLayout(head)

        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bubble.setObjectName("ChannelMsgText")
        bubble.setProperty("outgoing", "true" if is_outgoing else "false")
        col.addWidget(bubble)

        card.setMaximumWidth(740)

        if is_outgoing:
            row.addStretch(1)
            row.addWidget(card, 0, Qt.AlignRight)
            row.addWidget(avatar, 0, Qt.AlignBottom)
        else:
            row.addWidget(avatar, 0, Qt.AlignBottom)
            row.addWidget(card, 0, Qt.AlignLeft)
            row.addStretch(1)


class ChannelMemberItem(QFrame):
    def __init__(
        self,
        member: dict,
        current_login: str,
        permissions: dict,
        on_toggle_role=None,
        on_remove=None,
    ):
        super().__init__()
        self.member = member or {}

        self.setObjectName("ChannelMemberItem")
        self.setFixedHeight(90)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(18)

        login = self.member.get("login", "")
        nickname = self.member.get("nickname", login or "Пользователь")
        role = (self.member.get("role") or "member").strip().lower()
        online = bool(self.member.get("online", False))

        avatar = AvatarLabel(size=42)
        avatar.set_avatar(path=self.member.get("avatar", ""), login=login, nickname=nickname)
        avatar.set_online(online, ring_color="#2b2d31")
        lay.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        name_lbl = QLabel(nickname)
        name_lbl.setObjectName("ChannelMemberName")
        name_lbl.setStyleSheet("font-size:16px;font-weight:600;")
        name_lbl.setMinimumWidth(0)
        name_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_col.addWidget(name_lbl)

        role_name = {"owner":"Владелец", "admin":"Администратор", "moderator":"Модератор", "member":"Участник"}.get(role, "Участник")
        sub_lbl = QLabel(role_name)
        sub_lbl.setObjectName("ChannelMemberSub")
        sub_lbl.setStyleSheet("font-size:13px;color:#91ADFF;")
        text_col.addWidget(sub_lbl)

        lay.addLayout(text_col, 1)

        if role == "owner":
            owner = QPushButton("Владелец")
            owner.setObjectName("ChannelSecondaryButton")
            owner.setFixedSize(168,40)
            owner.setEnabled(False)
            lay.addWidget(owner)

        can_assign = bool(permissions.get("assign_roles", False))
        can_manage = bool(permissions.get("manage_members", False))
        my_role = (permissions.get("my_role") or "member").strip().lower()

        if can_assign and role != "owner" and login and login != current_login:
            role_actions = []
            if my_role == "owner":
                if role == "member":
                    role_actions.append(("Сделать модератором", "moderator"))
                    role_actions.append(("Сделать админом", "admin"))
                elif role == "moderator":
                    role_actions.append(("Сделать участником", "member"))
                    role_actions.append(("Сделать админом", "admin"))
                elif role == "admin":
                    role_actions.append(("Сделать модератором", "moderator"))
                    role_actions.append(("Сделать участником", "member"))
            elif my_role == "admin":
                if role == "member":
                    role_actions.append(("Сделать модератором", "moderator"))
                elif role == "moderator":
                    role_actions.append(("Сделать участником", "member"))

            if role_actions:
                btn = QPushButton('Сменить роль')
                btn.setFixedSize(168,40)
                btn.setObjectName('ChannelTinyActionButton')
                menu = QMenu(btn)
                for txt, new_role in role_actions:
                    menu.addAction(txt, partial(on_toggle_role, login, new_role))
                btn.setMenu(menu)
                lay.addWidget(btn)

        if can_manage and role != "owner" and login and login != current_login:
            from ui.design.widgets import Button
            remove_btn = Button("", "more")
            remove_btn.setProperty("flat",True)
            remove_btn.setFixedSize(40,40)
            remove_btn.setAccessibleName("Действия с участником")
            remove_btn.setObjectName("ChannelTinyDangerButton")
            remove_menu = QMenu(remove_btn)
            remove_menu.addAction("Удалить из канала", partial(on_remove, login))
            remove_btn.setMenu(remove_menu)
            lay.addWidget(remove_btn)


class VoiceParticipantItem(QFrame):
    def __init__(self, participant: dict, current_login: str):
        super().__init__()
        self.participant = participant or {}
        login=self.participant.get('login','')
        name=self.participant.get('nickname') or login or 'Участник'
        speaking=bool(self.participant.get('speaking'))
        self.setObjectName('ChannelVoiceMemberItem')
        self.setProperty('speaking',speaking)
        self.setFixedWidth(290)
        self.setFixedHeight(225)
        layout=QVBoxLayout(self);layout.setContentsMargins(20,28,20,24);layout.setSpacing(0)
        avatar=AvatarLabel(72);avatar.setProperty('own_avatar',login==current_login);avatar.set_avatar(self.participant.get('avatar',''),login,name)
        avatar.setProperty('speaking',speaking)
        layout.addWidget(avatar,0,Qt.AlignHCenter)
        layout.addSpacing(19)
        title=QLabel('Вы' if login==current_login else name);title.setObjectName('ChannelVoiceMemberName')
        title.setAlignment(Qt.AlignCenter);title.setWordWrap(True);layout.addWidget(title)
        layout.addSpacing(12)
        state=QLabel('Говорит' if speaking else 'Микрофон выключен' if self.participant.get('muted') else 'Слушает');state.setObjectName('ChannelVoiceMemberMeta')
        state.setAlignment(Qt.AlignCenter);layout.addWidget(state)
        layout.addStretch()


class ChannelInviteItem(QFrame):
    def __init__(self, invite: dict, on_accept, on_decline, parent=None):
        super().__init__(parent)
        self.invite = invite or {}
        self.setObjectName("ChannelInviteItem")

        from ui.design.widgets import Button
        self.setFixedHeight(121)
        lay=QHBoxLayout(self);lay.setContentsMargins(22,20,16,20);lay.setSpacing(24)
        channel_name=self.invite.get('channel_name') or 'Приглашение в канал'
        avatar=AvatarLabel(52);avatar.set_avatar(self.invite.get('avatar',''),nickname=channel_name);lay.addWidget(avatar)
        names=QVBoxLayout();names.setSpacing(8)
        title=QLabel(channel_name);title.setStyleSheet('font-size:19px;font-weight:600;');title.setWordWrap(True);names.addWidget(title)
        sender=self.invite.get('from_nickname') or self.invite.get('from_user') or 'пользователь'
        subtitle=QLabel(f'Пригласил: {sender}');subtitle.setObjectName('Muted');subtitle.setWordWrap(True);names.addWidget(subtitle)
        lay.addLayout(names,1)
        for label,width,callback,primary in [('Принять',130,on_accept,True),('Отклонить',136,on_decline,False)]:
            button=Button(label,primary=primary);button.setFixedSize(width,40)
            button.clicked.connect(lambda checked=False,cb=callback:cb(int(self.invite.get('invite_id') or 0)))
            lay.addWidget(button)




class ChannelsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_window = parent
        self.ctx = UserContext()

        self._threads = []
        self._alive = True

        self.channels = []
        self.active_channel = None

        self._loading_channels = False
        self._loading_invites = False
        self._loading_messages = False
        self._loading_channel_details = False

        self._creating_channel = False
        self._joining_channel = False
        self._sending_channel_invite = False
        self._responding_channel_invite = False
        self._saving_channel_settings = False
        self._changing_member_role = False
        self._removing_member = False
        self._leaving_channel = False
        self._deleting_channel = False

        self._sending_channel_msg = False
        self._message_send_inflight = False
        self._messages_signature = None
        self._channels_signature = None
        self._invites_signature = None
        self._channels_loaded_once = False
        self._channels_skeleton_visible = False

        self._create_avatar_path = ""
        self._settings_avatar_path = ""
        self._channel_details = {}
        self._settings_permissions = {}
        self._confirm_action = None

        self._voice_client = None
        self._voice_joined = False
        self._voice_transitioning = False
        self._voice_presence_syncing = False
        self._voice_participants_loading = False
        self._last_voice_participants_pull_ts = 0.0
        self._last_voice_presence_push_ts = 0.0
        self._voice_participants = []
        self._voice_participants_signature = ""
        self._voice_muted = False
        self._voice_deafened = False
        self._invites = []

        # callback в MainWindow для индикации приглашений на кнопке "Каналы"
        self.on_invites_count_changed = None

        self.setObjectName("ChannelsPage")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===== Left: channels sidebar =====
        sidebar = QFrame()
        sidebar.setObjectName("ChannelsSidebarCard")
        from ui.design.tokens import LIST_WIDTH
        sidebar.setFixedWidth(LIST_WIDTH)
        sb_l = QVBoxLayout(sidebar)
        sb_l.setContentsMargins(12, 30, 12, 20)
        sb_l.setSpacing(10)

        eyebrow=QLabel('ПРОСТРАНСТВА');eyebrow.setObjectName('Eyebrow');eyebrow.setContentsMargins(10,0,0,0);sb_l.addWidget(eyebrow)
        heading=QLabel('Каналы');heading.setObjectName('PageTitle');heading.setContentsMargins(10,0,0,0);sb_l.addWidget(heading);sb_l.addSpacing(12)
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(10,0,10,0)
        actions_row.setSpacing(10)

        self.create_channel_btn = QPushButton("Создать")
        self.create_channel_btn.setObjectName("ChannelCircleButton")
        self.create_channel_btn.setProperty("variant", "create")
        self.create_channel_btn.setFixedHeight(40)
        self.create_channel_btn.setObjectName("ChannelPrimaryButton")
        self.create_channel_btn.clicked.connect(self.open_create_page)
        actions_row.addWidget(self.create_channel_btn)
        install_opacity_feedback(self.create_channel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.join_channel_btn = QPushButton("Подключиться")
        self.join_channel_btn.setObjectName("ChannelCircleButton")
        self.join_channel_btn.setProperty("variant", "join")
        self.join_channel_btn.setFixedHeight(40)
        self.join_channel_btn.clicked.connect(self.open_join_page)
        actions_row.addWidget(self.join_channel_btn)
        install_opacity_feedback(self.join_channel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        sb_l.addLayout(actions_row)

        self.sidebar_actions_separator = QFrame()
        self.sidebar_actions_separator.setObjectName("ChannelsSidebarSeparator")
        self.sidebar_actions_separator.setFixedHeight(1)
        sb_l.addWidget(self.sidebar_actions_separator)

        invites_header = QFrame()
        invites_header.setObjectName("ChannelsInvitesHeader")
        invites_header_l = QHBoxLayout(invites_header)
        invites_header_l.setContentsMargins(10, 0, 10, 0)
        invites_header_l.setSpacing(6)

        self.invites_toggle_btn = QPushButton("Приглашения")
        self.invites_toggle_btn.setObjectName("ChannelsInvitesToggle")
        self.invites_toggle_btn.setCheckable(True)
        self.invites_toggle_btn.setChecked(False)
        self.invites_toggle_btn.toggled.connect(self._toggle_invites_dropdown)
        invites_header_l.addWidget(self.invites_toggle_btn, 1)
        install_opacity_feedback(self.invites_toggle_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.invites_badge = QLabel("")
        self.invites_badge.setObjectName("ChannelsInviteBadge")
        self.invites_badge.setVisible(False)
        self.invites_badge.setAlignment(Qt.AlignCenter)
        invites_header_l.addWidget(self.invites_badge, 0, Qt.AlignRight)

        sb_l.addWidget(invites_header)

        self.invites_dropdown = QFrame()
        self.invites_dropdown.setObjectName("ChannelsInvitesDropdown")
        self.invites_dropdown.setVisible(False)

        invites_dd_l = QVBoxLayout(self.invites_dropdown)
        invites_dd_l.setContentsMargins(0, 0, 0, 0)
        invites_dd_l.setSpacing(0)

        self.invites_scroll = QScrollArea()
        self.invites_scroll.setObjectName("ChannelsInvitesScroll")
        self.invites_scroll.setWidgetResizable(True)
        self.invites_scroll.setMinimumHeight(120)
        self.invites_scroll.setMaximumHeight(230)

        self.invites_container = QWidget()
        self.invites_layout = QVBoxLayout(self.invites_container)
        self.invites_layout.setContentsMargins(0, 0, 0, 0)
        self.invites_layout.setSpacing(8)
        self.invites_layout.addStretch(1)
        self.invites_scroll.setWidget(self.invites_container)

        invites_dd_l.addWidget(self.invites_scroll)
        sb_l.addWidget(self.invites_dropdown)

        list_head = QHBoxLayout()
        list_head.setContentsMargins(10, 0, 10, 0)
        list_head.setSpacing(6)

        list_title = QLabel("МОИ КАНАЛЫ")
        list_title.setObjectName("ChannelsListHeader")
        list_head.addWidget(list_title)
        list_head.addStretch(1)


        sb_l.addLayout(list_head)

        self.channels_scroll = QScrollArea()
        self.channels_scroll.setObjectName("ChannelsListScroll")
        self.channels_scroll.setWidgetResizable(True)

        self.channels_container = QWidget()
        self.channels_layout = QVBoxLayout(self.channels_container)
        self.channels_layout.setContentsMargins(0, 0, 0, 0)
        self.channels_layout.setSpacing(12)
        self.channels_layout.addStretch()

        self.channels_scroll.setWidget(self.channels_container)
        sb_l.addSpacing(13)
        sb_l.addWidget(self.channels_scroll, 1)
        self.voice_dock_space=QWidget()
        self.voice_dock_space.setFixedHeight(170)
        self.voice_dock_space.hide()
        sb_l.addWidget(self.voice_dock_space)
        sb_l.removeWidget(self.sidebar_actions_separator)
        sb_l.addWidget(self.sidebar_actions_separator)
        sb_l.removeWidget(invites_header);sb_l.addWidget(invites_header)
        sb_l.removeWidget(self.invites_dropdown);sb_l.addWidget(self.invites_dropdown)
        sb_l.addStretch()

        root.addWidget(sidebar, 1)

        # ===== Right: main panel =====
        right = QFrame()
        right.setObjectName("ChannelsMainCard")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(24, 24, 24, 16)
        right_l.setSpacing(10)

        self.main_stack = QStackedWidget()
        right_l.addWidget(self.main_stack, 1)

        # Placeholder page
        self.placeholder_page = QWidget()
        ph_l = QVBoxLayout(self.placeholder_page)
        ph_l.setContentsMargins(0, 0, 0, 0)
        ph_l.setContentsMargins(16, 8, 24, 0)
        ph_l.setSpacing(0)
        placeholder_title=QLabel('Ваши пространства');placeholder_title.setObjectName('FriendsTitle');placeholder_title.setFixedHeight(34);ph_l.addWidget(placeholder_title)
        ph_l.addSpacing(8)
        subtitle=QLabel('Текст и голос — рядом');subtitle.setObjectName('FriendsSubtitle');subtitle.setFixedHeight(17);ph_l.addWidget(subtitle)
        ph_l.addSpacing(18)
        divider=QFrame();divider.setObjectName('Divider');divider.setFixedHeight(1);ph_l.addWidget(divider)
        ph_l.addSpacing(38)
        self.channel_state_stack=QStackedWidget();ph_l.addWidget(self.channel_state_stack,1)
        self._set_channel_list_state('empty')
        self.main_stack.addWidget(self.placeholder_page)

        self.invites_page=QWidget()
        ip=QVBoxLayout(self.invites_page);ip.setContentsMargins(16,8,24,0);ip.setSpacing(0)
        title=QLabel('Приглашения');title.setObjectName('FriendsTitle');title.setFixedHeight(34);ip.addWidget(title)
        ip.addSpacing(8)
        subtitle=QLabel('Вас ждут в новых пространствах');subtitle.setObjectName('FriendsSubtitle');subtitle.setFixedHeight(17);ip.addWidget(subtitle)
        ip.addSpacing(18)
        divider=QFrame();divider.setObjectName('Divider');divider.setFixedHeight(1);ip.addWidget(divider)
        ip.addSpacing(52)
        sb_l.removeWidget(self.invites_dropdown)
        self.invites_dropdown.setObjectName("ChannelInvitesPageBody")
        self.invites_scroll.setMaximumHeight(16777215)
        self.invites_layout.setSpacing(24)
        ip.addWidget(self.invites_dropdown,1)
        self.main_stack.addWidget(self.invites_page)
        # Create channel page
        self.create_page = QWidget()
        cp_root = QVBoxLayout(self.create_page)
        cp_root.setContentsMargins(0, 0, 0, 0)
        cp_root.setContentsMargins(16, 8, 16, 0)

        create_card = QFrame()
        create_card.setObjectName("FlatForm")
        create_card.setMaximumWidth(840)
        create_card.setMinimumWidth(440)
        create_l = QVBoxLayout(create_card)
        create_l.setContentsMargins(0, 0, 0, 0)
        create_l.setSpacing(0)

        create_title = QLabel("Создание канала")
        create_title.setObjectName("FriendsTitle")
        create_title.setFixedHeight(34)
        create_l.addWidget(create_title)
        create_l.addSpacing(8)
        create_hint = QLabel("Форма остаётся открытой до вашего действия")
        create_hint.setObjectName("FriendsSubtitle");create_hint.setFixedHeight(17)
        create_l.addWidget(create_hint)
        create_l.addSpacing(65)

        avatar_row = QHBoxLayout()
        avatar_row.setContentsMargins(26,0,0,0);avatar_row.setSpacing(24)
        self.create_avatar_preview = AvatarLabel(size=72)
        self.create_avatar_preview.set_avatar(path="", login="channel", nickname="Канал")
        self.create_avatar_preview.set_online(None)
        avatar_row.addWidget(self.create_avatar_preview)

        self.select_avatar_btn = QPushButton("Установить аватар")
        self.select_avatar_btn.setObjectName("ChannelSecondaryButton")
        self.select_avatar_btn.setFixedSize(210,40)
        self.select_avatar_btn.setStyleSheet("padding:0;font-size:13px;min-height:38px;max-height:38px;")
        self.select_avatar_btn.clicked.connect(self.pick_create_avatar)
        install_opacity_feedback(self.select_avatar_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)
        avatar_row.addWidget(self.select_avatar_btn)
        avatar_row.addStretch()
        create_l.addLayout(avatar_row)
        create_l.addSpacing(40)
        create_fields = QVBoxLayout();create_fields.setContentsMargins(26,0,0,0);create_fields.setSpacing(14)
        create_label = QLabel("Название канала");create_label.setObjectName("FieldTitle");create_label.setFixedHeight(17)
        create_fields.addWidget(create_label)

        self.create_name_input = QLineEdit()
        self.create_name_input.setObjectName("ChannelInput")
        self.create_name_input.setPlaceholderText("Название канала")
        self.create_name_input.setMaximumWidth(670);self.create_name_input.setFixedHeight(46)
        self.create_name_input.setStyleSheet("min-height:22px;max-height:22px;")
        self.create_name_input.returnPressed.connect(self.create_channel)
        create_fields.addWidget(self.create_name_input)
        create_l.addLayout(create_fields)
        create_l.addSpacing(84)

        create_actions = QHBoxLayout()
        create_actions.setContentsMargins(26,0,0,0);create_actions.setSpacing(16)


        self.create_cancel_btn = QPushButton("Отмена")
        self.create_cancel_btn.setFixedSize(132,40);self.create_cancel_btn.setStyleSheet("padding:0;font-size:13px;min-height:38px;max-height:38px;")
        self.create_cancel_btn.setObjectName("ChannelSecondaryButton")
        self.create_cancel_btn.clicked.connect(self.open_default_view)
        create_actions.addWidget(self.create_cancel_btn)
        install_opacity_feedback(self.create_cancel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.create_confirm_btn = QPushButton("Создать")
        self.create_confirm_btn.setFixedSize(200,40);self.create_confirm_btn.setStyleSheet("padding:0;font-size:13px;min-height:38px;max-height:38px;")
        self.create_confirm_btn.setObjectName("ChannelPrimaryButton")
        self.create_confirm_btn.clicked.connect(self.create_channel)
        create_actions.insertWidget(0, self.create_confirm_btn)
        create_actions.addStretch()
        install_opacity_feedback(self.create_confirm_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        create_l.addLayout(create_actions)

        cp_root.addWidget(create_card)
        cp_root.addStretch()
        self.main_stack.addWidget(self.create_page)

        # Join page
        self.join_page = QWidget()
        jp_root = QVBoxLayout(self.join_page)
        jp_root.setContentsMargins(0, 0, 0, 0)
        jp_root.setContentsMargins(16, 8, 16, 0)

        join_card = QFrame()
        join_card.setObjectName("FlatForm")
        join_card.setMaximumWidth(840)
        join_card.setMinimumWidth(440)
        join_l = QVBoxLayout(join_card)
        join_l.setContentsMargins(0, 0, 0, 0)
        join_l.setSpacing(0)

        join_title = QLabel("Подключение к каналу")
        join_title.setObjectName("FriendsTitle");join_title.setFixedHeight(34)
        join_l.addWidget(join_title)
        join_l.addSpacing(8)

        join_hint = QLabel("Форма остаётся открытой до вашего действия")
        join_hint.setObjectName("FriendsSubtitle");join_hint.setFixedHeight(17)
        join_l.addWidget(join_hint)
        join_l.addSpacing(80)
        join_fields = QVBoxLayout();join_fields.setContentsMargins(26,0,0,0);join_fields.setSpacing(0)
        join_label = QLabel("Код приглашения");join_label.setObjectName("FieldTitle");join_label.setFixedHeight(17)
        join_fields.addWidget(join_label);join_fields.addSpacing(14)

        self.join_code_input = QLineEdit()
        self.join_code_input.setObjectName("ChannelInput")
        self.join_code_input.setPlaceholderText("Например: A1B2C3D4")
        self.join_code_input.returnPressed.connect(self.join_channel)
        self.join_code_input.setMaximumWidth(670);self.join_code_input.setFixedHeight(46)
        self.join_code_input.setStyleSheet("min-height:22px;max-height:22px;")
        join_fields.addWidget(self.join_code_input);join_fields.addSpacing(18)
        code_hint = QLabel("Код можно получить у участника канала.");code_hint.setObjectName("FriendsSubtitle");code_hint.setFixedHeight(17)
        join_fields.addWidget(code_hint);join_l.addLayout(join_fields)
        from ui.design.state_surfaces import InlineNote
        feedback_space=QWidget();feedback_space.setFixedHeight(146)
        feedback_layout=QVBoxLayout(feedback_space)
        feedback_layout.setContentsMargins(26,38,0,62)
        self.join_feedback=InlineNote();self.join_feedback.set_tone('error');self.join_feedback.setMaximumWidth(800)
        feedback_layout.addWidget(self.join_feedback)
        join_l.addWidget(feedback_space)

        join_actions = QHBoxLayout()
        join_actions.setContentsMargins(26,0,0,0);join_actions.setSpacing(16)


        self.join_cancel_btn = QPushButton("Отмена")
        self.join_cancel_btn.setFixedSize(132,40);self.join_cancel_btn.setStyleSheet("padding:0;font-size:13px;min-height:38px;max-height:38px;")
        self.join_cancel_btn.setObjectName("ChannelSecondaryButton")
        self.join_cancel_btn.clicked.connect(self.open_default_view)
        join_actions.addWidget(self.join_cancel_btn)
        install_opacity_feedback(self.join_cancel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.join_confirm_btn = QPushButton("Подключиться")
        self.join_confirm_btn.setFixedSize(200,40);self.join_confirm_btn.setStyleSheet("padding:0;font-size:13px;min-height:38px;max-height:38px;")
        self.join_confirm_btn.setObjectName("ChannelPrimaryButton")
        self.join_confirm_btn.clicked.connect(self.join_channel)
        join_actions.insertWidget(0, self.join_confirm_btn)
        join_actions.addStretch()
        install_opacity_feedback(self.join_confirm_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        join_l.addLayout(join_actions)

        jp_root.addWidget(join_card)
        jp_root.addStretch()
        self.main_stack.addWidget(self.join_page)

        # Opened channel page
        self.channel_page = QWidget()
        ch_root = QVBoxLayout(self.channel_page)
        ch_root.setContentsMargins(0, 0, 0, 0)
        ch_root.setSpacing(0)

        top = QFrame()
        top.setObjectName("ChannelTopBar")
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(8, 0, 0, 24)
        top.setFixedHeight(66)
        self.channel_header_avatar=AvatarLabel(40)
        top_l.addWidget(self.channel_header_avatar)
        top_l.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(1)

        from ui.design.widgets import ElidedLabel
        self.channel_name_lbl = ElidedLabel("Канал")
        self.channel_name_lbl.setObjectName("ChannelOpenTitle")
        self.channel_name_lbl.setMinimumWidth(0)
        self.channel_name_lbl.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        title_col.addWidget(self.channel_name_lbl)

        self.channel_code_lbl = QLabel("")
        self.channel_code_lbl.setObjectName("ChannelOpenCode")
        title_col.addWidget(self.channel_code_lbl)

        top_l.addLayout(title_col,1)
        top_l.addStretch()

        self.channel_settings_btn = QPushButton("Настройки")
        self.channel_settings_btn.setObjectName("ChannelSecondaryButton")
        self.channel_settings_btn.setFixedSize(140,40)
        self.channel_settings_btn.clicked.connect(self.open_channel_settings)
        top_l.addWidget(self.channel_settings_btn)
        from ui.design.widgets import Button
        self.channel_info_btn=Button('', 'info')
        self.channel_info_btn.setProperty('flat',True)
        self.channel_info_btn.setFixedSize(32,40)
        self.channel_info_btn.setAccessibleName('Информация о канале')
        self.channel_info_btn.clicked.connect(lambda:(self.open_channel_settings(),self.show_settings_section('general')))
        top_l.addWidget(self.channel_info_btn)
        install_opacity_feedback(self.channel_settings_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        ch_root.addWidget(top)
        divider=QFrame();divider.setObjectName("Divider");divider.setFixedHeight(1);ch_root.addWidget(divider)
        ch_root.addSpacing(17)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(10)

        nav = QFrame()
        nav.setObjectName("ChannelInnerNav")
        nav_l = QHBoxLayout(nav)
        nav_l.setContentsMargins(16, 0, 24, 0)
        nav_l.setSpacing(12)
        nav.setFixedHeight(40)

        self.voice_tab_btn = QPushButton("Голосовой")
        self.voice_tab_btn.setObjectName("ChannelInnerNavButton")
        self.voice_tab_btn.setCheckable(True)
        self.voice_tab_btn.toggled.connect(lambda checked: self.switch_to_voice_tab() if checked else None)
        nav_l.addWidget(self.voice_tab_btn)

        self.text_tab_btn = QPushButton("# Текстовый")
        self.text_tab_btn.setObjectName("ChannelInnerNavButton")
        self.text_tab_btn.setCheckable(True)
        self.text_tab_btn.toggled.connect(lambda checked: self.switch_to_text_tab() if checked else None)
        nav_l.addWidget(self.text_tab_btn)

        nav_l.removeWidget(self.text_tab_btn);nav_l.insertWidget(0,self.text_tab_btn)
        self.text_tab_btn.setFixedSize(158,40);self.voice_tab_btn.setFixedSize(158,40)
        nav_l.addStretch()
        ch_root.addWidget(nav)

        self.channel_inner_stack = QStackedWidget()

        # text tab
        text_tab = QWidget()
        t_l = QVBoxLayout(text_tab)
        t_l.setContentsMargins(0, 0, 0, 0)
        t_l.setSpacing(8)

        from ui.design.conversation import Conversation
        self.conversation = Conversation(self, channel=True)
        self.conversation.notice.connect(self.show_toast)
        self.channel_messages_scroll = self.conversation.view
        self.channel_msg_input = self.conversation.editor
        self.channel_send_btn = self.conversation.send_button
        self.channel_msg_input.setPlaceholderText('Сообщение в канал…')
        t_l.addWidget(self.conversation, 1)

        self.channel_inner_stack.addWidget(text_tab)

        from ui.design.channel_voice import build as build_voice
        voice_tab = build_voice(self)
        self.channel_inner_stack.addWidget(voice_tab)

        middle.addWidget(self.channel_inner_stack, 1)
        ch_root.addLayout(middle, 1)

        self.main_stack.addWidget(self.channel_page)

        # Settings page (stage 2)
        from ui.design.channel_settings import build as build_settings
        build_settings(self)

        root.addWidget(right, 3)

        # Inline toast (inside Channels page, shared component)
        self._toast = InlineToast(
            self,
            object_name="InlineToast",
            min_width=260,
            max_width=560,
            horizontal_margin=8,
            bottom_margin=16,
        )

        self._settings_layout_mode = None

        # Timers
        self.channels_timer = QTimer(self)
        self.channels_timer.setInterval(7000)
        self.channels_timer.timeout.connect(self.load_channels)

        self.invites_timer = QTimer(self)
        self.invites_timer.setInterval(5000)
        self.invites_timer.timeout.connect(self.load_channel_invites)

        self.messages_timer = QTimer(self)
        self.messages_timer.setInterval(2200)
        self.messages_timer.timeout.connect(self.load_channel_messages)

        self.voice_stats_timer = QTimer(self)
        self.voice_stats_timer.setInterval(800)
        self.voice_stats_timer.timeout.connect(self.update_voice_status)

        self.voice_presence_timer = QTimer(self)
        self.voice_presence_timer.setInterval(900)
        self.voice_presence_timer.timeout.connect(self.sync_voice_presence)

        # defaults
        self.main_stack.setCurrentWidget(self.placeholder_page)
        self.switch_to_text_tab()
        self.settings_text_perm_combo.setCurrentIndex(0)
        self.settings_voice_perm_combo.setCurrentIndex(0)
        self._set_invites_dropdown_open(False)
        self._render_voice_participants()
        self._apply_voice_local_controls()
        self._render_invites()
        self._show_channels_skeleton(count=6)
        self._apply_settings_responsive_layout(force=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _mark_settings_edited(self, *_args):
        self._settings_revision = getattr(self, "_settings_revision", 0) + 1

    def start_request(self, data, callback, host=None, port=None):
        if not hasattr(self, "_request_scope"):
            self._request_scope = RequestScope()
        action = data.get("action")
        scoped = action in {
            "get_channel_messages", "get_channel_details",
            "get_channel_voice_participants", "update_channel_settings",
        }
        if not scoped:
            return super().start_request(data, callback, host, port)
        def identity():
            return (self.ctx.session_token, self._active_channel_id(),
                    getattr(self, "_voice_epoch", 0) if action == "get_channel_voice_participants" else 0)
        ticket = self._request_scope.capture(action, identity())
        def guarded(response):
            if self._request_scope.accepts(ticket, identity()):
                callback(response)
        return super().start_request(data, guarded, host, port)

    def _invalidate_channel_requests(self):
        if hasattr(self, "_request_scope"):
            self._request_scope.invalidate()
        self._loading_messages = False
        self._loading_channel_details = False
        self._voice_participants_loading = False
        self._saving_channel_settings = False

    def start_auto_update(self):
        if not self._alive:
            return
        if not self._is_poll_allowed():
            self.stop_auto_update()
            return

        started_any = False
        if not self.channels_timer.isActive():
            self.channels_timer.start()
            started_any = True
        if not self.invites_timer.isActive():
            self.invites_timer.start()
            started_any = True

        if started_any:
            self.load_channels(force_refresh=True)
            self.load_channel_invites(force=True)

        if self.active_channel and self.main_stack.currentWidget() == self.channel_page and self.channel_inner_stack.currentIndex() == 0:
            if not self.messages_timer.isActive():
                self.messages_timer.start()
        else:
            if self.messages_timer.isActive():
                self.messages_timer.stop()

        if self._voice_joined and not self.voice_presence_timer.isActive():
            self.voice_presence_timer.start()

    def stop_auto_update(self):
        if self.channels_timer.isActive():
            self.channels_timer.stop()
        if self.invites_timer.isActive():
            self.invites_timer.stop()
        if self.messages_timer.isActive():
            self.messages_timer.stop()

    def reset_for_user(self):
        self.conversation.reset()
        self._invalidate_channel_requests()
        self._alive = True
        self.stop_auto_update()
        self.stop_voice_session(show_toast=False)
        if self.voice_presence_timer.isActive():
            self.voice_presence_timer.stop()

        self.channels = []
        self.active_channel = None

        self._loading_channels = False
        self._loading_invites = False
        self._loading_messages = False
        self._loading_channel_details = False

        self._creating_channel = False
        self._joining_channel = False
        self._sending_channel_invite = False
        self._responding_channel_invite = False
        self._saving_channel_settings = False
        self._changing_member_role = False
        self._removing_member = False
        self._leaving_channel = False
        self._deleting_channel = False
        self._sending_channel_msg = False
        self._message_send_inflight = False
        self._messages_signature = None
        self._channels_signature = None
        self._invites_signature = None
        self._channels_loaded_once = False

        self._create_avatar_path = ""
        self._settings_avatar_path = ""
        self._channel_details = {}
        self._settings_permissions = {}
        self._confirm_action = None
        self._voice_transitioning = False
        self._voice_presence_syncing = False
        self._voice_participants_loading = False
        self._last_voice_participants_pull_ts = 0.0
        self._last_voice_presence_push_ts = 0.0
        self._voice_participants = []
        self._voice_participants_signature = ""
        self._voice_muted = False
        self._voice_deafened = False
        self._invites = []

        self.create_name_input.clear()
        self.join_code_input.clear()
        self.channel_msg_input.clear()
        self.settings_name_input.clear()
        self.settings_invite_login_input.clear()
        self.settings_invite_status.clear()
        self.settings_invite_status.setVisible(False)
        self.settings_code_lbl.setText("—")
        self.settings_text_perm_combo.setCurrentIndex(0)
        self.settings_voice_perm_combo.setCurrentIndex(0)
        self._set_channel_send_busy(False)
        self._apply_voice_local_controls()

        self.hide_settings_confirm()
        self._clear_channels_list()
        self._clear_invites_list()
        self._update_invites_indicator(0)
        self._set_invites_dropdown_open(False)
        self._clear_channel_messages()
        self._clear_members_list()
        self._clear_voice_members_list()
        self.main_stack.setCurrentWidget(self.placeholder_page)
        self._show_channels_skeleton(count=6)
        self._reposition_overlays()

    def closeEvent(self, event):
        self._alive = False
        self.stop_auto_update()
        self.stop_voice_session(show_toast=False)
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_overlays()
        self._apply_settings_responsive_layout()
        if hasattr(self,'voice_tab_layout'):
            self.voice_tab_layout.setContentsMargins(16,36,24,66 if self.height()>=800 else 16)
        if hasattr(self,'voice_members_scroll'):
            columns=max(1,min(3,(max(0,self.voice_members_scroll.width()-12)+20)//310))
            if columns!=getattr(self,'_voice_columns',None):
                self._voice_columns=columns
                self._render_voice_participants()

    def _is_poll_allowed(self) -> bool:
        if not self._alive or not self.ctx.login:
            return False
        if not self.isVisible():
            return False

        try:
            win = self.window()
            if win is not None and bool(win.windowState() & Qt.WindowMinimized):
                return False
        except Exception:
            pass

        app = QApplication.instance()
        if app is not None:
            try:
                if app.applicationState() != Qt.ApplicationActive:
                    return False
            except Exception:
                pass
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _reposition_overlays(self):
        if getattr(self, "_toast", None):
            self._toast.reposition()

    def show_toast(self, text: str, msec: int = 2800):
        if not text:
            return
        if getattr(self, "_toast", None):
            self._toast.show(text, msec)

    def _apply_settings_responsive_layout(self, force: bool = False):
        # Fields shrink to the viewport width; vertical overflow uses settings_scroll.
        pass

    def _set_invites_dropdown_open(self, opened: bool):
        with QSignalBlocker(self.invites_toggle_btn):
            self.invites_toggle_btn.setChecked(bool(opened))
        self.invites_dropdown.setVisible(True)
        if opened:
            self.main_stack.setCurrentWidget(self.invites_page)
        elif self.main_stack.currentWidget() == self.invites_page:
            self.main_stack.setCurrentWidget(self.placeholder_page)

    def _toggle_invites_dropdown(self, checked: bool):
        self._set_invites_dropdown_open(bool(checked))

    def _update_invites_indicator(self, count: int):
        count = max(0, int(count or 0))
        if count > 0:
            self.invites_badge.setText("99+" if count > 99 else str(count))
            self.invites_badge.setVisible(True)
        else:
            self.invites_badge.setVisible(False)

        if callable(self.on_invites_count_changed):
            try:
                self.on_invites_count_changed(count)
            except Exception:
                pass

    def _clear_channels_list(self):
        for i in reversed(range(self.channels_layout.count() - 1)):
            item = self.channels_layout.takeAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()


    def _set_channel_list_state(self, state):
        from ui.design.state_surfaces import EmptyState, LoadingState
        stack = self.channel_state_stack
        while stack.count():
            old = stack.widget(0)
            stack.removeWidget(old)
            old.deleteLater()
        if state == 'loading':
            surface = LoadingState()
        else:
            title = {'empty':'Создайте своё пространство', 'error':'Не удалось загрузить каналы', 'list':'Выберите канал'}[state]
            action = {'empty':'Создать канал','error':'Повторить','list':None}[state]
            callback = self.open_create_page if state == 'empty' else lambda: self.load_channels(force_refresh=True)
            surface = EmptyState(title,'Общайтесь в тексте и собирайтесь в голосовом канале.',action,callback)
            surface.set_top_offset(148)
        stack.addWidget(surface)

    def _show_channels_skeleton(self, count: int = 6):
        self._channels_skeleton_visible = True
        self._clear_channels_list()
        self.channels_layout.insertWidget(0,self._make_channels_empty_state('Загрузка…',''))
        self._set_channel_list_state('loading')

    def _make_channels_empty_state(self, title: str, subtitle: str) -> QFrame:
        card = QFrame()
        card.setMinimumWidth(0)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(15, 20, 15, 20)
        text = QLabel(title)
        text.setWordWrap(True)
        text.setObjectName('Muted')
        lay.addWidget(text)
        return card

    def _clear_invites_list(self):
        for i in reversed(range(self.invites_layout.count() - 1)):
            item = self.invites_layout.takeAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def _render_invites(self, force: bool = False):
        digest = self._invites_digest(self._invites)
        if (not force) and digest == self._invites_signature:
            return
        self._invites_signature = digest

        self._clear_invites_list()
        invites = list(self._invites or [])
        self._update_invites_indicator(len(invites))

        if not invites:
            from ui.design.state_surfaces import EmptyState
            empty=EmptyState('Нет новых приглашений','Когда вас пригласят в канал, приглашение появится здесь.')
            empty.set_top_offset(134)
            self.invites_layout.insertWidget(0,empty)
            return

        for inv in invites:
            item = ChannelInviteItem(
                invite=inv,
                on_accept=self.accept_channel_invite,
                on_decline=self.decline_channel_invite,
            )
            self.invites_layout.insertWidget(self.invites_layout.count() - 1, item)

    def _clear_channel_messages(self):
        self.conversation.select(None)

    def conversation_request(self, data, callback):
        # Conversation owns dialog epochs; sends remain attached to their original channel.
        super().start_request(data, callback)

    def _clear_members_list(self):
        for i in reversed(range(self.members_layout.count() - 1)):
            item = self.members_layout.takeAt(i)
            if item and item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def _clear_voice_members_list(self):
        for i in reversed(range(self.voice_members_layout.count())):
            item = self.voice_members_layout.takeAt(i)
            if item and item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def _set_channel_send_busy(self, busy: bool):
        self._message_send_inflight = bool(busy)
        self.channel_send_btn.setEnabled(not busy and bool((self._settings_permissions or {}).get("can_send_text", True)))
        self.channel_send_btn.setToolTip("Отправка…" if busy else "Отправить")

    @staticmethod
    def _messages_digest(messages: list) -> str:
        parts = []
        for m in messages or []:
            parts.append(
                f"{m.get('id','')}|{m.get('from_user','')}|{m.get('created_at','')}|{m.get('text','')}"
            )
        return "\n".join(parts)

    @staticmethod
    def _voice_participants_digest(participants: list) -> str:
        rows = []
        for p in participants or []:
            rows.append(
                f"{p.get('login','')}|{p.get('role','')}|{int(bool(p.get('online', False)))}|{int(bool(p.get('speaking', False)))}"
            )
        rows.sort()
        return "\n".join(rows)

    @staticmethod
    def _channels_digest(channels: list, current_id: int) -> str:
        parts = [f"active:{int(current_id or 0)}"]
        for ch in channels or []:
            parts.append(
                "|".join([
                    str(ch.get("id", "")),
                    str(ch.get("name", "")),
                    str(ch.get("avatar", "") or ""),
                    str(ch.get("code", "") or ""),
                    str(ch.get("my_role", "") or ""),
                    str(ch.get("members_count", "")),
                ])
            )
        return "\n".join(parts)

    @staticmethod
    def _invites_digest(invites: list) -> str:
        rows = []
        for inv in invites or []:
            rows.append(
                "|".join([
                    str(inv.get("invite_id", "")),
                    str(inv.get("channel_id", "")),
                    str(inv.get("channel_name", "")),
                    str(inv.get("from_user", "")),
                    str(inv.get("from_nickname", "")),
                ])
            )
        rows.sort()
        return "\n".join(rows)

    @staticmethod
    def _format_time(ts: str) -> str:
        if not ts:
            return ""
        try:
            # YYYY-mm-dd HH:MM:SS
            return ts[11:16]
        except Exception:
            return ""

    def _active_channel_id(self) -> int:
        try:
            return int((self.active_channel or {}).get("id") or 0)
        except Exception:
            return 0

    def _voice_room_id(self) -> str:
        cid = self._active_channel_id()
        return f"channel:{cid}" if cid > 0 else ""

    def _apply_channel_header(self):
        name = (self.active_channel or {}).get("name", "Канал")
        code = (self.active_channel or {}).get("code", "")
        self.channel_name_lbl.setText(name)
        self.channel_header_avatar.set_avatar((self.active_channel or {}).get('avatar',''), nickname=name)
        count=(self.active_channel or {}).get('participants_count',(self.active_channel or {}).get('members_count'))
        prefix=participants_text(count)+' · ' if count is not None else ''
        self.channel_code_lbl.setText(prefix + (f'Код {code}' if code else ''))

    def _apply_channel_permissions_ui(self):
        perms = self._settings_permissions or {}
        can_send_text = bool(perms.get("can_send_text", True))
        can_join_voice = bool(perms.get("can_join_voice", True))
        voice_req = (perms.get("voice_min_role") or "member").strip().lower()

        self.conversation.permission_text = ("Писать в этом канале могут только владелец и администраторы."
            if perms.get("text_min_role") == "admin" else "Писать в этом канале могут модераторы и администраторы.")
        self.conversation.can_send = can_send_text
        self.conversation.update_controls()
        # text controls
        if can_send_text:
            self.channel_msg_input.setEnabled(True)
            self.channel_msg_input.setPlaceholderText("Сообщение в канал...")
        else:
            self.channel_msg_input.setEnabled(False)
            self.channel_send_btn.setEnabled(False)
            text_req = (perms.get("text_min_role") or "admin").strip().lower()
            if text_req == "admin":
                self.channel_msg_input.setPlaceholderText("Только владельцы и админы могут писать в этот канал")
            elif text_req == "moderator":
                self.channel_msg_input.setPlaceholderText("Недостаточно прав для отправки")
            else:
                self.channel_msg_input.setPlaceholderText("У вас нет прав на отправку сообщений")

        # voice controls
        if self._voice_joined:
            self.voice_join_btn.setEnabled(not self._voice_transitioning)
            self.voice_join_btn.setText("Отключение..." if self._voice_transitioning else "Отключиться")
            self.voice_access_hint_lbl.setText("Вы подключены к голосовому каналу")
        else:
            self.voice_join_btn.setText("Подключение..." if self._voice_transitioning else "Войти в голосовой" if can_join_voice else "Нет доступа")
            self.voice_join_btn.setEnabled(can_join_voice and (not self._voice_transitioning))
            if can_join_voice:
                self.voice_access_hint_lbl.setText("В голосовом канале могут одновременно находиться несколько участников")
            else:
                if voice_req == "admin":
                    self.voice_access_hint_lbl.setText("Голосовой доступен только владельцу и администраторам.")
                elif voice_req == "moderator":
                    self.voice_access_hint_lbl.setText("Голосовой доступен только модераторам и администраторам.")
                else:
                    self.voice_access_hint_lbl.setText("У вас нет доступа к голосовому каналу")

        if self.active_channel and self.channel_inner_stack.currentIndex() == 1 and (not can_join_voice) and (not self._voice_joined):
            self.voice_status_lbl.setText("Вы не в голосовом канале")
            self.voice_quality_lbl.setText("Качество: —")

        self.voice_access_hint_lbl.setVisible(not can_join_voice and not self._voice_joined)
        can_manage = bool(perms.get("manage_channel", False))
        can_invite = bool(perms.get("can_invite", False))
        can_delete = bool(perms.get("delete_channel", False))

        # Показываем/скрываем только тот функционал, который реально доступен по правам.
        self.settings_pick_avatar_btn.setVisible(can_manage)
        self.settings_save_btn.setVisible(can_manage)
        self.settings_regen_code_btn.setVisible(can_manage)
        self.settings_name_input.setVisible(can_manage)

        # Блок политики доступа (текст/голос) доступен только владельцу (manage_channel).
        self.settings_access_card.setVisible(can_manage and getattr(self, "_settings_section", "general") == "access")
        if hasattr(self, "settings_sections"):
            self.settings_sections["access"].setVisible(can_manage)

        # Копирование кода — при наличии права приглашать или редактировать канал.
        self.settings_copy_code_btn.setVisible(can_invite or can_manage)

        # Приглашение по логину показываем только тем, кому можно приглашать.
        self.settings_invite_block.setVisible(can_invite)
        self.settings_invite_login_input.setEnabled(can_invite)
        self.settings_invite_btn.setEnabled(can_invite and (not self._sending_channel_invite))
        if not can_invite:
            self.settings_invite_status.setVisible(False)

        self.delete_channel_btn.setVisible(can_delete)
        self.leave_channel_btn.setVisible(not can_delete)

        self._apply_settings_responsive_layout(force=True)
        self._apply_voice_local_controls()

    # ------------------------------------------------------------------
    # Left list rendering
    # ------------------------------------------------------------------
    def render_channels(self, force: bool = False):
        current_id = self._active_channel_id()
        digest = self._channels_digest(self.channels, current_id)
        if (not force) and digest == self._channels_signature:
            return
        self._channels_signature = digest

        self.channels_scroll.setMaximumHeight(max(180, len(self.channels)*82))
        self.channels_scroll.setUpdatesEnabled(False)
        try:
            self._clear_channels_list()
            self._channels_skeleton_visible = False

            if not self.channels:
                empty = self._make_channels_empty_state(
                    title="Пока нет каналов",
                    subtitle="Создайте новый канал или подключитесь по коду.",
                )
                self.channels_layout.insertWidget(self.channels_layout.count() - 1, empty)
                return

            for ch in self.channels:
                item = ChannelListItem(
                    channel=ch,
                    active=(int(ch.get("id", 0)) == current_id),
                    on_click=lambda c=ch: self.open_channel(c),
                )
                self.channels_layout.insertWidget(self.channels_layout.count() - 1, item)
        finally:
            self.channels_scroll.setUpdatesEnabled(True)

    def load_channel_invites(self, force: bool = False):
        if not self._alive or self._loading_invites or not self.ctx.login:
            return
        if (not force) and (not self._is_poll_allowed()):
            return

        self._loading_invites = True

        def cb(resp: dict):
            self._loading_invites = False
            if not self._alive:
                return
            if (resp or {}).get("status") != "ok":
                return
            self._invites = (resp.get("invites") or []) if isinstance(resp, dict) else []
            self._render_invites()

        self.start_request({"action": "get_my_channel_invites"}, cb)

    def respond_channel_invite(self, invite_id: int, decision: str):
        if not self._alive or self._responding_channel_invite or invite_id <= 0:
            return

        self._responding_channel_invite = True

        def cb(resp: dict):
            self._responding_channel_invite = False
            if not self._alive:
                return
            if (resp or {}).get("status") != "ok":
                self.show_toast((resp or {}).get("message") or "Не удалось обработать приглашение")
                return

            channel = resp.get("channel") if isinstance(resp, dict) else None
            if channel and decision == "accept":
                self.show_toast("Вы подключились к каналу")
                self.load_channels(force_refresh=True, preferred_channel_id=int(channel.get("id") or 0))
            else:
                self.show_toast("Приглашение отклонено")
                self.load_channels()

            self.load_channel_invites()

        self.start_request(
            {
                "action": "respond_channel_invite",
                "invite_id": int(invite_id),
                "decision": (decision or "").strip().lower(),
            },
            cb,
        )

    def accept_channel_invite(self, invite_id: int):
        self.respond_channel_invite(invite_id, "accept")

    def decline_channel_invite(self, invite_id: int):
        self.respond_channel_invite(invite_id, "decline")

    # ------------------------------------------------------------------
    # Main stack pages
    # ------------------------------------------------------------------
    def open_default_view(self):
        self.hide_settings_confirm()
        if self.active_channel:
            self.main_stack.setCurrentWidget(self.channel_page)
            if self.channel_inner_stack.currentIndex() == 0 and not self.messages_timer.isActive():
                self.messages_timer.start()
        else:
            self.main_stack.setCurrentWidget(self.placeholder_page)
            if self.messages_timer.isActive():
                self.messages_timer.stop()
        self._apply_channel_permissions_ui()

    def open_create_page(self):
        self._set_invites_dropdown_open(False)
        self._channel_navigation_revision = getattr(self, "_channel_navigation_revision", 0) + 1
        self.hide_settings_confirm()
        self.create_name_input.clear()
        self._create_avatar_path = ""
        self.create_avatar_preview.set_avatar(path="", login="channel", nickname="Канал")
        self.main_stack.setCurrentWidget(self.create_page)
        if self.messages_timer.isActive():
            self.messages_timer.stop()

    def open_join_page(self):
        self._set_invites_dropdown_open(False)
        self._channel_navigation_revision = getattr(self, "_channel_navigation_revision", 0) + 1
        self.hide_settings_confirm()
        self.join_code_input.clear()
        self.join_feedback.clear()
        self.main_stack.setCurrentWidget(self.join_page)
        if self.messages_timer.isActive():
            self.messages_timer.stop()

    def open_channel(self, channel: dict):
        self._set_invites_dropdown_open(False)
        if not channel:
            return
        self._channel_navigation_revision = getattr(self, "_channel_navigation_revision", 0) + 1

        self.hide_settings_confirm()

        new_id = int(channel.get("id", 0) or 0)
        old_id = self._active_channel_id()

        # Switch voice room if needed
        if self._voice_client is not None and old_id and new_id and old_id != new_id:
            self.stop_voice_session(show_toast=False)

        self._invalidate_channel_requests()
        self.active_channel = dict(channel)
        self._channel_details = {}
        self._settings_permissions = {}
        self._messages_signature = None
        self._voice_participants = []
        self._voice_participants_signature = ""
        self._render_voice_participants()
        self._set_channel_send_busy(False)

        self._apply_channel_header()
        self.main_stack.setCurrentWidget(self.channel_page)
        self.switch_to_text_tab()
        self.render_channels()
        self.load_channel_messages(force=True)
        self.load_channel_details(silent=True)

    # ------------------------------------------------------------------
    # Create / Join actions
    # ------------------------------------------------------------------
    def pick_create_avatar(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите аватар канала",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not file_path:
            return

        try:
            self._create_avatar_path = encode_avatar(file_path)
        except ValueError as error:
            self.show_toast(str(error))
            return
        preview_name = self.create_name_input.text().strip() or "Канал"
        self.create_avatar_preview.set_avatar(path=file_path, login="channel", nickname=preview_name)

    def create_channel(self):
        if not self._alive or self._creating_channel or not self.ctx.login:
            return

        name = self.create_name_input.text().strip()
        if not name:
            self.show_toast("Введите название канала")
            return

        self._creating_channel = True
        payload = {
            "action": "create_channel",
            "name": name,
            "avatar": self._create_avatar_path,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.show_toast(resp.get("message", "Не удалось создать канал"))
                    return

                ch = resp.get("channel") or {}
                if not ch:
                    self.show_toast("Канал создан, но данные не получены")
                    self.load_channels()
                    self.open_default_view()
                    return

                self.show_toast("Канал успешно создан")
                self.load_channels(force_refresh=True, preferred_channel_id=int(ch.get("id", 0) or 0))
                self.open_channel(ch)
            finally:
                self._creating_channel = False

        self.start_request(payload, cb)

    def join_channel(self):
        if not self._alive or self._joining_channel or not self.ctx.login:
            return

        code = self.join_code_input.text().strip().upper()
        if not code:
            self.join_feedback.setText("Введите код канала")
            return

        self.join_feedback.clear()
        self._joining_channel = True
        self.join_confirm_btn.setEnabled(False)
        payload = {"action": "join_channel", "code": code}

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.join_feedback.setText(resp.get("message", "Не удалось подключиться к каналу"))
                    return

                ch = resp.get("channel") or {}
                self.show_toast("Вы подключились к каналу")
                self.load_channels(force_refresh=True, preferred_channel_id=int(ch.get("id", 0) or 0))
                if ch:
                    self.open_channel(ch)
                else:
                    self.open_default_view()
            finally:
                self._joining_channel = False
                self.join_confirm_btn.setEnabled(True)

        self.start_request(payload, cb)

    # ------------------------------------------------------------------
    # Channel list refresh
    # ------------------------------------------------------------------
    def load_channels(self, force_refresh: bool = False, preferred_channel_id: int = 0):
        if not self._alive or not self.ctx.login:
            return
        if (not force_refresh) and (not self._is_poll_allowed()):
            return
        if self._loading_channels and not force_refresh:
            return
        if not self._channels_loaded_once:
            self._show_channels_skeleton(count=6)

        self._channel_list_revision = getattr(self, '_channel_list_revision', 0) + 1
        list_revision = self._channel_list_revision
        navigation_revision = getattr(self, '_channel_navigation_revision', 0)
        self._loading_channels = True
        payload = {"action": "get_my_channels"}

        def cb(resp):
            if list_revision != self._channel_list_revision:
                return
            try:
                self._channels_loaded_once = True
                if resp.get("status") != "ok":
                    self.show_toast(resp.get("message", "Не удалось обновить список каналов"))
                    if not self.channels:
                        self._clear_channels_list()
                        self._channels_skeleton_visible = False
                        self.channels_layout.insertWidget(0,self._make_channels_empty_state('Список недоступен',''))
                        self._set_channel_list_state('error')
                    return

                self.channels = resp.get("channels", []) or []
                self._set_channel_list_state("list" if self.channels else "empty")

                # keep active channel if still exists
                cur_id = self._active_channel_id()
                previous_id = cur_id
                if preferred_channel_id and (
                    navigation_revision == getattr(self, '_channel_navigation_revision', 0)
                    or cur_id == preferred_channel_id
                ):
                    cur_id = preferred_channel_id

                matched = None
                if cur_id:
                    matched = next((c for c in self.channels if int(c.get("id", 0)) == int(cur_id)), None)

                if matched:
                    if previous_id != cur_id:
                        self.open_channel(matched)
                    else:
                        self.active_channel = dict(matched)
                        self._apply_channel_header()
                else:
                    # active channel deleted/unavailable
                    if self._voice_client is not None:
                        self.stop_voice_session(show_toast=False)
                    self.active_channel = None
                    self._channel_details = {}
                    self._settings_permissions = {}
                    self._messages_signature = None
                    self._voice_participants = []
                    self._voice_participants_signature = ""
                    self._clear_voice_members_list()
                    self.hide_settings_confirm()
                    if self.main_stack.currentWidget() not in (self.create_page, self.join_page, self.invites_page):
                        self.main_stack.setCurrentWidget(self.placeholder_page)
                    if self.messages_timer.isActive():
                        self.messages_timer.stop()
                    self._apply_channel_permissions_ui()

                self.render_channels()

                current_page = self.main_stack.currentWidget()
                if self.active_channel and current_page in (self.placeholder_page,):
                    self.open_channel(self.active_channel)

                self._apply_channel_permissions_ui()

            finally:
                self._loading_channels = False

        self.start_request(payload, cb)

    # ------------------------------------------------------------------
    # Text channel
    # ------------------------------------------------------------------
    def show_settings_section(self, key):
        self._settings_section = key
        for name, card in [('general',self.settings_general_card),('access',self.settings_access_card),('members',self.settings_members_card)]:
            card.setVisible(name == key and getattr(self,"_settings_load_state","ready")=="ready")
            with QSignalBlocker(self.settings_sections[name]):
                self.settings_sections[name].setChecked(name == key)
        self.settings_scroll.verticalScrollBar().setValue(0)

    def switch_to_text_tab(self):
        with QSignalBlocker(self.text_tab_btn), QSignalBlocker(self.voice_tab_btn):
            self.text_tab_btn.setChecked(True)
            self.voice_tab_btn.setChecked(False)
        self.channel_inner_stack.setCurrentIndex(0)
        self._apply_channel_permissions_ui()

        if self.active_channel and self.main_stack.currentWidget() == self.channel_page and not self.messages_timer.isActive():
            self.messages_timer.start()

    def switch_to_voice_tab(self):
        with QSignalBlocker(self.text_tab_btn), QSignalBlocker(self.voice_tab_btn):
            self.text_tab_btn.setChecked(False)
            self.voice_tab_btn.setChecked(True)
        self.channel_inner_stack.setCurrentIndex(1)
        self._apply_channel_permissions_ui()
        self._apply_voice_local_controls()

        if self.messages_timer.isActive():
            self.messages_timer.stop()

        if self.active_channel:
            self.load_voice_participants(force=True)

    def load_channel_messages(self, force: bool = False):
        if not self._alive or not self.active_channel:
            return
        if not force and not self._is_poll_allowed():
            return
        if self.main_stack.currentWidget() != self.channel_page or self.channel_inner_stack.currentIndex() != 0:
            return
        channel_id = self._active_channel_id()
        allowed = bool((self._settings_permissions or {}).get('can_send_text', True))
        if self.conversation.identity != channel_id:
            self.conversation.select(channel_id, self.active_channel.get('name',''), allowed)
        else:
            self.conversation.can_send = allowed
            self.conversation.update_controls()
            self.conversation.load('poll')

    def send_channel_message(self):
        self.conversation.can_send = bool((self._settings_permissions or {}).get('can_send_text', True))
        self.conversation.send()

    def _render_voice_participants(self):
        self._clear_voice_members_list()

        participants = sorted(self._voice_participants or [],key=lambda p:(p.get("login")==self.ctx.login,(p.get("nickname") or p.get("login","")).casefold()))
        self.voice_members_layout.setAlignment(Qt.AlignTop | (Qt.AlignLeft if participants else Qt.AlignmentFlag(0)))
        count=len(participants)
        self.voice_members_count.setText('Нет участников' if not count else participants_text(count))
        if not participants:
            from ui.design.state_surfaces import EmptyState
            empty=EmptyState('Пока тихо','Подключитесь к голосовому первым.')
            empty.layout().setContentsMargins(0,0,20,0)
            empty.set_top_offset(0)
            empty.setMinimumHeight(174)
            self.voice_members_layout.addWidget(empty,0,0,1,3)
            return

        columns=max(1,min(3,(max(0,self.voice_members_scroll.width()-12)+20)//310))
        self._voice_columns=columns
        for i,part in enumerate(participants):
            if part.get("login")==self.ctx.login:
                part=dict(part,muted=self._voice_muted,speaking=bool(part.get("speaking")) and not self._voice_muted)
            row = VoiceParticipantItem(participant=part, current_login=self.ctx.login)
            self.voice_members_layout.addWidget(row,i//columns,i%columns)
        for column in range(3):
            self.voice_members_layout.setColumnStretch(column,0)

    def load_voice_participants(self, force: bool = False):
        if not self._alive or not self.active_channel:
            return
        if (not force) and (not self._is_poll_allowed()):
            return
        if self._voice_participants_loading and not force:
            return

        channel_id = self._active_channel_id()
        if channel_id <= 0:
            return

        now = time.monotonic()
        if (not force) and (now - self._last_voice_participants_pull_ts < 1.1):
            return

        self._voice_participants_loading = True
        self._last_voice_participants_pull_ts = now
        payload = {
            "action": "get_channel_voice_participants",
            "channel_id": channel_id,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    # no noisy toast for periodic polling
                    if force and self.channel_inner_stack.currentIndex() == 1:
                        self.show_toast(resp.get("message", "Не удалось загрузить участников"))
                    return

                participants = resp.get("participants") or []
                if not self._voice_joined:
                    participants = [p for p in participants if p.get("login") != self.ctx.login]
                # Local fallback: ensure current user row appears right after join
                if self._voice_joined and self.ctx.login and not any((p.get("login") == self.ctx.login) for p in participants):
                    participants.insert(0, {
                        "login": self.ctx.login,
                        "nickname": self.ctx.login,
                        "avatar": "",
                        "role": (self._channel_details.get("my_role") or "member"),
                        "online": True,
                        "speaking": False,
                    })

                digest = self._voice_participants_digest(participants)
                self._voice_participants = participants
                if digest != self._voice_participants_signature:
                    self._voice_participants_signature = digest
                    self._render_voice_participants()
            finally:
                self._voice_participants_loading = False

        self.start_request(payload, cb)

    def _push_voice_presence(self, speaking: bool, joined: bool = True):
        if not self._alive or not self.active_channel:
            return
        if self._voice_presence_syncing:
            return

        channel_id = self._active_channel_id()
        if channel_id <= 0:
            return

        self._voice_presence_syncing = True
        payload = {
            "action": "set_channel_voice_presence",
            "channel_id": channel_id,
            "speaking": bool(speaking),
            "joined": bool(joined),
            "sequence": voice_sequence.next(),
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    msg = (resp.get("message") or "").lower()
                    if "прав" in msg or "доступ" in msg:
                        self.load_channel_details(silent=True)
                        if self._voice_joined:
                            self.stop_voice_session(show_toast=False)
                            self.show_toast("Нет доступа к голосовому каналу")
            finally:
                self._voice_presence_syncing = False

        self.start_request(payload, cb)

    def _leave_voice_presence(self, channel_id: int = 0):
        cid = int(channel_id or 0)
        if cid <= 0:
            cid = self._active_channel_id()
        if cid <= 0 or not self._alive:
            return

        payload = {
            "action": "leave_channel_voice",
            "channel_id": cid,
            "sequence": voice_sequence.next(),
        }
        def after_leave(response):
            if response.get("status") == "ok" and self._active_channel_id() == cid and not self._voice_joined:
                self.load_voice_participants(force=True)
        self.start_request(payload, after_leave)

    def sync_voice_presence(self, force_pull: bool = False):
        if not self._alive or not self.active_channel:
            return

        foreground = self._is_poll_allowed()
        now = time.monotonic()

        # Push local speaking state if joined
        if self._voice_joined and self._voice_client is not None:
            push_interval = 0.9 if foreground else 1.8
            if (now - self._last_voice_presence_push_ts) >= push_interval:
                self._last_voice_presence_push_ts = now
                speaking = False
                try:
                    activity = self._voice_client.get_activity()
                    speaking = bool(activity.get("me_speaking", False)) and not self._voice_muted
                except Exception:
                    speaking = False
                self._push_voice_presence(speaking=speaking, joined=True)

        # Refresh participant list only while voice tab is visible in foreground.
        if (force_pull or self.channel_inner_stack.currentIndex() == 1) and foreground:
            self.load_voice_participants(force=force_pull)

    # ------------------------------------------------------------------
    # Settings page (stage 2)
    # ------------------------------------------------------------------
    def _show_settings_load_state(self, state):
        self._settings_load_state=state
        self.settings_loading_surface.setVisible(state=='loading')
        self.settings_error_surface.setVisible(state=='error')
        self.show_settings_section(getattr(self,'_settings_section','general'))

    def open_channel_settings(self):
        if not self.active_channel:
            self.show_toast("Сначала выберите канал")
            return

        if self.messages_timer.isActive():
            self.messages_timer.stop()

        self.hide_settings_confirm()
        self.settings_invite_status.clear()
        self.settings_invite_status.setVisible(False)
        self.main_stack.setCurrentWidget(self.settings_page)
        self.settings_feedback.clear()
        self._show_settings_load_state("loading")
        self._apply_settings_responsive_layout(force=True)
        self.load_channel_details(silent=False)

    def close_channel_settings(self):
        self.hide_settings_confirm()
        if self.active_channel:
            self.main_stack.setCurrentWidget(self.channel_page)
            if self.channel_inner_stack.currentIndex() == 0 and not self.messages_timer.isActive():
                self.messages_timer.start()
        else:
            self.main_stack.setCurrentWidget(self.placeholder_page)
        self._apply_channel_permissions_ui()

    def load_channel_details(self, silent: bool = True):
        if not self._alive or self._loading_channel_details or not self.active_channel:
            return

        channel_id = self._active_channel_id()
        if channel_id <= 0:
            return

        revision = self._settings_revision
        self._loading_channel_details = True
        if not silent:
            self._show_settings_load_state("loading")
        payload = {
            "action": "get_channel_details",
            "channel_id": channel_id,
        }

        def cb(resp):
            try:
                if revision != self._settings_revision:
                    return
                if resp.get("status") != "ok":
                    if self.main_stack.currentWidget()==self.settings_page and (not silent or self._settings_load_state=='loading'):
                        self._show_settings_load_state('error')
                    return

                self._show_settings_load_state('ready')
                details = {
                    "channel": resp.get("channel") or {},
                    "my_role": resp.get("my_role") or "member",
                    "permissions": resp.get("permissions") or {},
                    "members": resp.get("members") or [],
                }
                self._channel_details = details
                self._settings_permissions = details.get("permissions", {}) or {}

                ch = details.get("channel") or {}
                if ch:
                    # sync active channel data
                    self.active_channel = dict({**(self.active_channel or {}), **ch})
                    self.channels=[dict(row,**ch) if row.get("id")==channel_id else row for row in self.channels]
                    self._apply_channel_header()
                    self.render_channels()

                self._settings_avatar_path = ch.get("avatar", "") if ch else ""

                name = ch.get("name", "") if ch else ""
                code = ch.get("code", "") if ch else ""
                self.settings_title_lbl.setText(f"Настройки · {name or 'Канал'}")
                self.settings_name_input.setText(name)
                self.settings_code_lbl.setText(code or "—")
                self.settings_avatar_preview.set_avatar(
                    path=ch.get("avatar", "") if ch else "",
                    login=f"channel_{ch.get('id', '')}" if ch else "channel",
                    nickname=name or "Канал",
                )
                self.settings_avatar_preview.set_online(None)

                can_manage = bool(self._settings_permissions.get("manage_channel", False))
                can_invite = bool(self._settings_permissions.get("can_invite", True))
                can_delete = bool(self._settings_permissions.get("delete_channel", False))

                text_min_role = (ch.get("text_min_role") or self._settings_permissions.get("text_min_role") or "member").strip().lower()
                voice_min_role = (ch.get("voice_min_role") or self._settings_permissions.get("voice_min_role") or "member").strip().lower()

                t_idx = self.settings_text_perm_combo.findData(text_min_role)
                v_idx = self.settings_voice_perm_combo.findData(voice_min_role)
                self.settings_text_perm_combo.setCurrentIndex(t_idx if t_idx >= 0 else 0)
                self.settings_voice_perm_combo.setCurrentIndex(v_idx if v_idx >= 0 else 0)

                self.settings_name_input.setReadOnly(not can_manage)
                self.settings_pick_avatar_btn.setEnabled(can_manage)
                self.settings_save_btn.setEnabled(can_manage)
                self.settings_copy_code_btn.setEnabled(can_invite or can_manage)
                self.settings_text_perm_combo.setEnabled(can_manage)
                self.settings_access_save.setEnabled(can_manage)
                for radio in self.settings_text_radios:
                    radio.setEnabled(can_manage)
                self.settings_voice_perm_combo.setEnabled(can_manage)
                self.settings_invite_login_input.setEnabled(can_invite)
                self.settings_invite_btn.setEnabled(can_invite and (not self._sending_channel_invite))
                if not can_invite:
                    self.settings_invite_status.setVisible(False)

                self.delete_channel_btn.setVisible(can_delete)
                self.leave_channel_btn.setVisible(not can_delete)

                self.render_channel_members(details.get("members") or [])
                self._apply_channel_permissions_ui()
                if self._voice_joined or self.channel_inner_stack.currentIndex() == 1:
                    self.sync_voice_presence(force_pull=True)
            finally:
                self._loading_channel_details = False

        self.start_request(payload, cb)

    def render_channel_members(self, members: list):
        self._clear_members_list()

        if not members:
            empty = QLabel("В канале пока нет участников")
            empty.setObjectName("ChannelsEmptyList")
            self.members_layout.insertWidget(self.members_layout.count() - 1, empty)
            return

        for member in members:
            row = ChannelMemberItem(
                member=member,
                current_login=self.ctx.login,
                permissions=self._settings_permissions,
                on_toggle_role=self.set_member_role,
                on_remove=self.ask_remove_member,
            )
            self.members_layout.insertWidget(self.members_layout.count() - 1, row)

    def pick_settings_avatar(self):
        if not bool(self._settings_permissions.get("manage_channel", False)):
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите аватар канала",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not file_path:
            return

        try:
            self._settings_avatar_path = encode_avatar(file_path)
            self._mark_settings_edited()
        except ValueError as error:
            self.show_toast(str(error))
            return
        preview_name = self.settings_name_input.text().strip() or "Канал"
        self.settings_avatar_preview.set_avatar(path=file_path, login="channel", nickname=preview_name)

    def copy_channel_code(self):
        code = self.settings_code_lbl.text().strip()
        if not code or code == "—":
            self.show_toast("Код канала недоступен")
            return

        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(code)
            self.show_toast("Код скопирован")

    def send_channel_invite(self):
        if not self._alive or self._sending_channel_invite or not self.active_channel:
            return
        if not bool(self._settings_permissions.get("can_invite", False)):
            return

        login = self.settings_invite_login_input.text().strip()
        if not login:
            self.show_toast("Введите логин пользователя")
            return

        self._sending_channel_invite = True
        self.settings_invite_btn.setEnabled(False)

        payload = {
            "action": "send_channel_invite",
            "channel_id": self._active_channel_id(),
            "to_user": login,
        }

        def cb(resp):
            self._sending_channel_invite = False
            can_invite = bool(self._settings_permissions.get("can_invite", False))
            self.settings_invite_btn.setEnabled(can_invite)

            data = resp or {}
            ok = data.get("status") == "ok"
            msg = "Приглашение отправлено" if ok else (data.get("message") or "Не удалось отправить приглашение")

            self.settings_invite_status.setText(msg)
            self.settings_invite_status.setVisible(True)
            self.show_toast(msg)

            if ok:
                self.settings_invite_login_input.clear()

        self.start_request(payload, cb)

    def save_channel_settings(self):
        if not self._alive or self._saving_channel_settings or not self.active_channel:
            return
        if not bool(self._settings_permissions.get("manage_channel", False)):
            return

        name = self.settings_name_input.text().strip()
        if not name:
            self.show_toast("Введите название канала")
            return

        revision = self._settings_revision
        self._saving_channel_settings = True
        self.settings_feedback.clear()
        self.settings_save_btn.setEnabled(False)
        self.settings_access_save.setEnabled(False)
        payload = {
            "action": "update_channel_settings",
            "channel_id": self._active_channel_id(),
            "name": name,
            "avatar": self._settings_avatar_path,
            "text_min_role": self.settings_text_perm_combo.currentData() or "member",
            "voice_min_role": self.settings_voice_perm_combo.currentData() or "member",
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.settings_feedback.set_tone("error")
                    self.settings_feedback.setText(resp.get("message", "Не удалось сохранить настройки"))
                    return

                ch = resp.get("channel") or {}
                if ch:
                    self.active_channel = dict({**(self.active_channel or {}), **ch})
                    self._apply_channel_header()

                self.settings_feedback.set_tone("success")
                self.settings_feedback.setText("Настройки канала сохранены")
                self.load_channels(force_refresh=True, preferred_channel_id=self._active_channel_id())
                if revision == self._settings_revision:
                    self.load_channel_details(silent=True)
            finally:
                self._saving_channel_settings = False
                allowed=bool(self._settings_permissions.get("manage_channel",False))
                self.settings_save_btn.setEnabled(allowed)
                self.settings_access_save.setEnabled(allowed)

        self.start_request(payload, cb)

    def ask_regenerate_channel_code(self):
        if not self._settings_permissions.get("manage_channel", False):
            return
        from ui.design.dialogs import confirm
        confirm(self, "Обновить код приглашения?",
                "Прежний код перестанет работать.\nОтправьте новый код тем, кого хотите пригласить.",
                "Обновить", self.regenerate_channel_code)

    def regenerate_channel_code(self):
        if not self._alive or not self.active_channel:
            return
        if not bool(self._settings_permissions.get("manage_channel", False)):
            return

        payload = {
            "action": "regenerate_channel_code",
            "channel_id": self._active_channel_id(),
        }

        def cb(resp):
            if resp.get("status") != "ok":
                self.show_toast(resp.get("message", "Не удалось обновить код"))
                return
            ch = resp.get("channel") or {}
            if ch:
                self.active_channel = dict({**(self.active_channel or {}), **ch})
                self._apply_channel_header()
                code = ch.get("code", "")
                self.settings_code_lbl.setText(code or "—")
                self.settings_title_lbl.setText(f"Настройки · {ch.get('name', 'Канал')}")
            self.show_toast("Код приглашения обновлён")
            self.load_channels(force_refresh=True, preferred_channel_id=self._active_channel_id())

        self.start_request(payload, cb)

    def set_member_role(self, target_login: str, new_role: str):
        if not self._alive or self._changing_member_role or not self.active_channel:
            return

        self._changing_member_role = True
        payload = {
            "action": "set_channel_member_role",
            "channel_id": self._active_channel_id(),
            "target_login": target_login,
            "role": new_role,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.show_toast(resp.get("message", "Не удалось изменить роль"))
                    return
                self.show_toast("Роль участника обновлена")
                self.load_channel_details(silent=True)
                self.load_channels(force_refresh=True, preferred_channel_id=self._active_channel_id())
            finally:
                self._changing_member_role = False

        self.start_request(payload, cb)

    def ask_remove_member(self, target_login: str):
        self.show_settings_confirm(
            text=f"Удалить пользователя {target_login} из канала?",
            action_type="remove_member",
            payload={"target_login": target_login},
        )

    def ask_leave_channel(self):
        self.show_settings_confirm(
            text="Чтобы вернуться, потребуется код или приглашение.",
            action_type="leave_channel",
            payload={},
        )

    def ask_delete_channel(self):
        self.show_settings_confirm(
            text="Участники потеряют доступ к каналу.\nЭто действие нельзя отменить.",
            action_type="delete_channel",
            payload={},
        )

    def show_settings_confirm(self, text: str, action_type: str, payload: dict):
        self._confirm_action = {
            "type": action_type,
            "payload": payload or {},
        }
        self.settings_confirm_text.setText(text or "Подтвердите действие")
        from ui.design.dialogs import confirm
        titles = {"delete_channel": "Удалить канал?", "leave_channel": "Выйти из канала?", "remove_member": "Удалить участника?"}
        if action_type == "delete_channel" and self.active_channel:
            name = self.active_channel.get("name", "")
            if name:
                titles[action_type] = f"Удалить канал «{name}»?"
        labels = {"delete_channel": "Удалить", "leave_channel": "Выйти", "remove_member": "Удалить"}
        confirm(self, titles.get(action_type, "Подтвердите действие"), text,
                labels.get(action_type, "Подтвердить"), self.apply_settings_confirm, danger=True)

    def hide_settings_confirm(self):
        self._confirm_action = None
        self.settings_confirm.setVisible(False)
        dialog = getattr(self, "_confirmation", None)
        if dialog is not None:
            try:
                dialog.reject()
            except RuntimeError:
                pass

    def apply_settings_confirm(self):
        action = self._confirm_action or {}
        action_type = action.get("type")
        payload = action.get("payload") or {}
        self.hide_settings_confirm()

        if action_type == "remove_member":
            self.remove_member(payload.get("target_login", ""))
        elif action_type == "leave_channel":
            self.leave_channel()
        elif action_type == "delete_channel":
            self.delete_channel()

    def remove_member(self, target_login: str):
        if not target_login or not self.active_channel or self._removing_member:
            return

        self._removing_member = True
        payload = {
            "action": "remove_channel_member",
            "channel_id": self._active_channel_id(),
            "target_login": target_login,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.show_toast(resp.get("message", "Не удалось удалить участника"))
                    return
                self.show_toast("Участник удалён из канала")
                self.load_channel_details(silent=True)
                self.load_channels(force_refresh=True, preferred_channel_id=self._active_channel_id())
            finally:
                self._removing_member = False

        self.start_request(payload, cb)

    def leave_channel(self):
        if not self.active_channel or self._leaving_channel:
            return

        self._leaving_channel = True
        cid = self._active_channel_id()
        payload = {
            "action": "leave_channel",
            "channel_id": cid,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.show_toast(resp.get("message", "Не удалось выйти из канала"))
                    return

                if self._voice_joined:
                    self.stop_voice_session(show_toast=False)

                self.active_channel = None
                self._channel_details = {}
                self._settings_permissions = {}
                self._messages_signature = None
                self._voice_participants = []
                self._voice_participants_signature = ""
                self._clear_channel_messages()
                self._clear_members_list()
                self._clear_voice_members_list()
                self.main_stack.setCurrentWidget(self.placeholder_page)
                self._apply_channel_permissions_ui()
                if self.messages_timer.isActive():
                    self.messages_timer.stop()

                self.load_channels(force_refresh=True)
                self.show_toast("Вы вышли из канала")
            finally:
                self._leaving_channel = False

        self.start_request(payload, cb)

    def delete_channel(self):
        if not self.active_channel or self._deleting_channel:
            return

        self._deleting_channel = True
        cid = self._active_channel_id()
        payload = {
            "action": "delete_channel",
            "channel_id": cid,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.show_toast(resp.get("message", "Не удалось удалить канал"))
                    return

                if self._voice_joined:
                    self.stop_voice_session(show_toast=False)

                self.active_channel = None
                self._channel_details = {}
                self._settings_permissions = {}
                self._messages_signature = None
                self._voice_participants = []
                self._voice_participants_signature = ""
                self._clear_channel_messages()
                self._clear_members_list()
                self._clear_voice_members_list()
                self.main_stack.setCurrentWidget(self.placeholder_page)
                self._apply_channel_permissions_ui()
                if self.messages_timer.isActive():
                    self.messages_timer.stop()

                self.load_channels(force_refresh=True)
                self.show_toast("Канал удалён")
            finally:
                self._deleting_channel = False

        self.start_request(payload, cb)

    # ------------------------------------------------------------------
    # Voice channel
    # ------------------------------------------------------------------
    def _apply_voice_local_controls(self):
        joined = bool(self._voice_joined)
        if not joined:
            self.voice_status_lbl.setStyleSheet("font-size:16px;font-weight:600;color:#EDF2FA;")

        self.voice_mute_btn.setVisible(joined)
        self.voice_deafen_btn.setVisible(joined)
        self.voice_quality_lbl.setVisible(False)
        self.voice_join_btn.setFixedWidth(200 if joined else 220)
        self.voice_before_join.changeSize(0,0,QSizePolicy.Expanding if joined else QSizePolicy.Fixed,QSizePolicy.Minimum)
        self.voice_after_join.changeSize(0,0,QSizePolicy.Fixed if joined else QSizePolicy.Expanding,QSizePolicy.Minimum)
        self.voice_controls.layout().invalidate()
        self.voice_join_btn.primary=not joined
        self.voice_join_btn.setProperty("danger",joined)
        self.voice_join_btn.update()
        self.voice_mute_btn.setEnabled(joined)
        self.voice_deafen_btn.setEnabled(joined)

        self.voice_mute_btn.setText("Микрофон выкл." if self._voice_muted else "Микрофон вкл.")
        self.voice_deafen_btn.setText("Звук выкл." if self._voice_deafened else "Звук вкл.")

        if self._voice_client is not None:
            try:
                self._voice_client.set_mic_enabled(not self._voice_muted)
            except Exception:
                pass
            try:
                self._voice_client.set_sound_enabled(not self._voice_deafened)
            except Exception:
                pass

    def toggle_voice_mute(self):
        if not self._voice_joined:
            return
        self._voice_muted = not self._voice_muted
        self._apply_voice_local_controls()
        self._render_voice_participants()
        self.update_voice_status()
        self._last_voice_presence_push_ts=0
        self.sync_voice_presence()

    def toggle_voice_deafen(self):
        if not self._voice_joined:
            return
        self._voice_deafened = not self._voice_deafened
        self._apply_voice_local_controls()

    def toggle_voice_join(self):
        if self._voice_transitioning:
            return

        if self._voice_joined:
            self._voice_transitioning = True
            self._apply_channel_permissions_ui()
            try:
                self.stop_voice_session(show_toast=True)
            finally:
                self._voice_transitioning = False
                self._apply_channel_permissions_ui()
            return

        if not self.active_channel or not self.ctx.login:
            self.show_toast("Сначала выберите канал")
            return

        if not bool((self._settings_permissions or {}).get("can_join_voice", True)):
            self.show_toast("У вас нет прав для входа в голосовой канал")
            return

        settings=getattr(self._main_window,'settings_page',None)
        if settings is not None and not settings.stop_microphone_check():
            channel_id=self._active_channel_id()
            epoch=getattr(self,"_voice_epoch",0)
            QTimer.singleShot(50,lambda:self.toggle_voice_join() if self._alive and self._active_channel_id()==channel_id and getattr(self,"_voice_epoch",0)==epoch and not self._voice_joined else None)
            return

        # Avoid audio device conflicts with private peer-to-peer calls
        main_win = self._main_window
        try:
            if getattr(main_win, "current_call_user", None):
                self.show_toast("Сначала завершите личный звонок")
                return
            vc_existing = getattr(main_win, "voice_client", None)
            if vc_existing is not None and getattr(vc_existing, "running", False):
                self.show_toast("Сначала завершите личный звонок")
                return
        except Exception:
            pass

        room_id = self._voice_room_id()
        if not room_id:
            self.show_toast("Некорректный канал")
            return

        self._voice_transitioning = True
        self._apply_channel_permissions_ui()

        try:
            host, port = get_voice_endpoint()
        except (ValueError, TypeError) as error:
            self._voice_transitioning = False
            self._apply_channel_permissions_ui()
            self.show_toast(f"Ошибка настроек голосового сервера: {error}")
            return
        voice = VoiceSession(self.ctx.login, token=self.ctx.session_token or "", host=host, port=port)
        self._voice_client = voice

        def ready():
            if self._voice_client is not voice:
                return
            self._voice_transitioning = False
            self._voice_joined = True
            self._voice_started_at=time.monotonic()
            self._last_voice_presence_push_ts = 0.0
            self._apply_voice_local_controls()
            self.update_voice_status()
            self.voice_stats_timer.start()
            self.voice_presence_timer.start()
            self._apply_channel_permissions_ui()
            self.sync_voice_presence(force_pull=True)
            self.show_toast("Подключено к голосовому каналу")

        def failed(message):
            if self._voice_client is not voice:
                return
            voice.stop()
            self._voice_client = None
            self._voice_transitioning = False
            self._voice_joined = False
            self.voice_status_lbl.setText("Не удалось подключиться к голосовому каналу")
            self.voice_quality_lbl.setText("Качество: —")
            self._apply_channel_permissions_ui()
            self.show_toast(f"Ошибка голосового канала: {message}")

        voice.ready.connect(ready)
        voice.failed.connect(failed)
        voice.start(room_id=room_id)

    def stop_voice_session(self, show_toast: bool = False):
        self._voice_transitioning = False
        self._voice_epoch = getattr(self, "_voice_epoch", 0) + 1
        self._voice_participants_loading = False
        channel_id = self._active_channel_id()

        if self._voice_client is not None:
            try:
                self._voice_client.stop()
            except Exception:
                pass
        self._voice_client = None

        was_joined = bool(self._voice_joined)
        self._voice_joined = False
        self._last_voice_presence_push_ts = 0.0
        self._voice_muted = False
        self._voice_deafened = False
        self._voice_participants_signature = ""
        self._voice_participants = []
        self._render_voice_participants()
        self.voice_join_btn.setText("Подключиться")
        self.voice_status_lbl.setText("Вы не в голосовом канале")
        self.voice_quality_lbl.setText("Качество: —")

        if self.voice_stats_timer.isActive():
            self.voice_stats_timer.stop()
        if self.voice_presence_timer.isActive():
            self.voice_presence_timer.stop()

        if was_joined and channel_id > 0:
            self._leave_voice_presence(channel_id=channel_id)

        self._apply_channel_permissions_ui()
        self._apply_voice_local_controls()

        if show_toast:
            self.show_toast("Вы вышли из голосового канала")

    def update_voice_status(self):
        if not self._voice_joined or self._voice_client is None:
            return

        try:
            activity = self._voice_client.get_activity()
            quality = activity.get("quality", "—")
            latency = activity.get("latency_ms", 0)
            jitter = activity.get("jitter_ms", 0)
            buffer_frames = int(activity.get("buffer_frames", 0) or 0)
            me = bool(activity.get("me_speaking", False)) and not self._voice_muted
            peer = bool(activity.get("peer_speaking", False))

            reconnecting=quality == "Переподключение"
            elapsed=max(0,int(time.monotonic()-getattr(self,'_voice_started_at',time.monotonic())))
            state="Восстанавливаем соединение…" if reconnecting else f"Вы подключены · {elapsed//60:02}:{elapsed%60:02}"
            self.voice_status_lbl.setText(state)
            self.voice_status_lbl.setStyleSheet('font-size:16px;font-weight:600;color:'+('#EAC184' if reconnecting else '#67D5AD')+';')
            self.voice_quality_lbl.setVisible(latency > 150 or jitter > 60)
            self.voice_quality_lbl.setText(
                f"Связь нестабильна · задержка {latency} мс · возможны перерывы звука"
            )
            # keep local speaking indicator fresh between server syncs
            if self._voice_participants:
                changed = False
                for p in self._voice_participants:
                    if p.get("login") == self.ctx.login:
                        old = bool(p.get("speaking", False))
                        if old != me:
                            p["speaking"] = me
                            changed = True
                        break
                if changed:
                    self._voice_participants_signature = self._voice_participants_digest(self._voice_participants)
                    self._render_voice_participants()
        except Exception:
            self.voice_quality_lbl.setText("Качество: —")
