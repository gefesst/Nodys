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
    QSizePolicy,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer

from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel
from ui.micro_interactions import install_opacity_feedback
from ui.toast import InlineToast
from voice_client import VoiceClient
from settings import get_voice_endpoint


class ChannelListItem(QFrame):
    def __init__(self, channel: dict, active: bool = False, on_click=None, compact: bool = False):
        super().__init__()
        self.channel = channel or {}
        self._on_click = on_click

        self.setObjectName("ChannelListItem")
        self.setProperty("active", bool(active))
        self.setProperty("compact", "true" if compact else "false")
        self.setFixedHeight(54 if compact else 64)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8 if compact else 10, 7 if compact else 8, 8 if compact else 10, 7 if compact else 8)
        lay.setSpacing(7 if compact else 10)

        avatar = AvatarLabel(size=34 if compact else 42)
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
        parts = [role_text]
        if (not compact) and participants_count > 0:
            parts.append(f"Участников: {participants_count}")

        sub = QLabel(" · ".join(parts))
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

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        login = self.member.get("login", "")
        nickname = self.member.get("nickname", login or "Пользователь")
        role = (self.member.get("role") or "member").strip().lower()
        online = bool(self.member.get("online", False))

        avatar = AvatarLabel(size=38)
        avatar.set_avatar(path=self.member.get("avatar", ""), login=login, nickname=nickname)
        avatar.set_online(online, ring_color="#2b2d31")
        lay.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        name_lbl = QLabel(nickname)
        name_lbl.setObjectName("ChannelMemberName")
        text_col.addWidget(name_lbl)

        state = "в сети" if online else "не в сети"
        sub_lbl = QLabel(f"{login} · {state}")
        sub_lbl.setObjectName("ChannelMemberSub")
        text_col.addWidget(sub_lbl)

        lay.addLayout(text_col, 1)

        if role == "owner":
            role_text = "ВЛАДЕЛЕЦ"
        elif role == "admin":
            role_text = "АДМИН"
        elif role == "moderator":
            role_text = "МОДЕРАТОР"
        else:
            role_text = "УЧАСТНИК"

        role_lbl = QLabel(role_text)
        role_lbl.setObjectName("ChannelMemberRoleBadge")
        role_lbl.setProperty("role", role)
        lay.addWidget(role_lbl)

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

            for txt, new_role in role_actions:
                btn = QPushButton(txt)
                btn.setObjectName("ChannelTinyActionButton")
                btn.clicked.connect(partial(on_toggle_role, login, new_role))
                lay.addWidget(btn)

        if can_manage and role != "owner" and login and login != current_login:
            remove_btn = QPushButton("Удалить")
            remove_btn.setObjectName("ChannelTinyDangerButton")
            remove_btn.clicked.connect(partial(on_remove, login))
            lay.addWidget(remove_btn)


class VoiceParticipantItem(QFrame):
    def __init__(self, participant: dict, current_login: str):
        super().__init__()
        self.participant = participant or {}

        speaking = bool(self.participant.get("speaking", False))
        role = (self.participant.get("role") or "member").strip().lower()
        login = self.participant.get("login", "")
        nickname = self.participant.get("nickname", login or "Участник")
        online = bool(self.participant.get("online", True))

        self.setObjectName("ChannelVoiceMemberItem")
        self.setProperty("speaking", "true" if speaking else "false")
        self.style().unpolish(self)
        self.style().polish(self)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        avatar = AvatarLabel(size=34)
        avatar.set_avatar(path=self.participant.get("avatar", ""), login=login, nickname=nickname)
        avatar.set_online(online, ring_color="#2f343d")
        lay.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        display_name = f"{nickname} (вы)" if login and login == current_login else nickname
        name_lbl = QLabel(display_name)
        name_lbl.setObjectName("ChannelVoiceMemberName")
        text_col.addWidget(name_lbl)

        role_ru = (
            "владелец"
            if role == "owner"
            else ("админ" if role == "admin" else ("модератор" if role == "moderator" else "участник"))
        )
        state = "в сети" if online else "не в сети"
        meta_lbl = QLabel(f"{login} · {role_ru} · {state}")
        meta_lbl.setObjectName("ChannelVoiceMemberMeta")
        text_col.addWidget(meta_lbl)

        lay.addLayout(text_col, 1)

        badge = QLabel("ГОВОРИТ" if speaking else "ТИШИНА")
        badge.setObjectName("ChannelVoiceSpeakingBadge")
        badge.setProperty("off", "false" if speaking else "true")
        badge.style().unpolish(badge)
        badge.style().polish(badge)
        lay.addWidget(badge)


class ChannelInviteItem(QFrame):
    def __init__(self, invite: dict, on_accept, on_decline, parent=None):
        super().__init__(parent)
        self.invite = invite or {}
        self.setObjectName("ChannelInviteItem")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        channel_name = self.invite.get("channel_name") or "Приглашение в канал"
        title = QLabel(channel_name)
        title.setObjectName("ChannelInviteTitle")
        title.setWordWrap(True)
        lay.addWidget(title)

        from_user = self.invite.get("from_nickname") or self.invite.get("from_user") or "пользователь"
        sub = QLabel(f"Пригласил: {from_user}")
        sub.setObjectName("ChannelInviteSub")
        lay.addWidget(sub)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)

        btn_accept = QPushButton("Принять")
        btn_accept.setObjectName("ChannelTinyActionButton")
        btn_accept.clicked.connect(lambda: on_accept(int(self.invite.get("invite_id") or 0)))
        install_opacity_feedback(btn_accept, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        btn_decline = QPushButton("Отклонить")
        btn_decline.setObjectName("ChannelTinyDangerButton")
        btn_decline.clicked.connect(lambda: on_decline(int(self.invite.get("invite_id") or 0)))
        install_opacity_feedback(btn_decline, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        actions.addWidget(btn_accept)
        actions.addWidget(btn_decline)
        actions.addStretch(1)
        lay.addLayout(actions)




class ChannelsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
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
        self._messages_signature = ""
        self._channels_signature = None
        self._invites_signature = None
        self._compact_mode = False
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
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)

        # ===== Left: channels sidebar =====
        sidebar = QFrame()
        sidebar.setObjectName("ChannelsSidebarCard")
        sidebar.setMinimumWidth(250)
        sidebar.setMaximumWidth(300)
        sb_l = QVBoxLayout(sidebar)
        sb_l.setContentsMargins(10, 10, 10, 10)
        sb_l.setSpacing(10)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.create_channel_btn = QPushButton("Создать\nканал")
        self.create_channel_btn.setObjectName("ChannelCircleButton")
        self.create_channel_btn.setProperty("variant", "create")
        self.create_channel_btn.setFixedSize(96, 96)
        self.create_channel_btn.clicked.connect(self.open_create_page)
        actions_row.addWidget(self.create_channel_btn)
        install_opacity_feedback(self.create_channel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.join_channel_btn = QPushButton("Подключ\nиться")
        self.join_channel_btn.setObjectName("ChannelCircleButton")
        self.join_channel_btn.setProperty("variant", "join")
        self.join_channel_btn.setFixedSize(96, 96)
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
        invites_header_l.setContentsMargins(0, 0, 0, 0)
        invites_header_l.setSpacing(6)

        self.invites_toggle_btn = QPushButton("ПРИГЛАШЕНИЯ ▸")
        self.invites_toggle_btn.setObjectName("ChannelsInvitesToggle")
        self.invites_toggle_btn.setCheckable(True)
        self.invites_toggle_btn.setChecked(False)
        self.invites_toggle_btn.clicked.connect(self._toggle_invites_dropdown)
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
        list_head.setContentsMargins(0, 0, 0, 0)
        list_head.setSpacing(6)

        list_title = QLabel("МОИ КАНАЛЫ")
        list_title.setObjectName("ChannelsListHeader")
        list_head.addWidget(list_title)
        list_head.addStretch(1)

        self.compact_toggle_btn = QPushButton("Компактно")
        self.compact_toggle_btn.setObjectName("ChannelsCompactToggle")
        self.compact_toggle_btn.setCheckable(True)
        self.compact_toggle_btn.toggled.connect(self.set_compact_mode)
        list_head.addWidget(self.compact_toggle_btn)
        install_opacity_feedback(self.compact_toggle_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        sb_l.addLayout(list_head)

        self.channels_scroll = QScrollArea()
        self.channels_scroll.setObjectName("ChannelsListScroll")
        self.channels_scroll.setWidgetResizable(True)

        self.channels_container = QWidget()
        self.channels_layout = QVBoxLayout(self.channels_container)
        self.channels_layout.setContentsMargins(0, 0, 0, 0)
        self.channels_layout.setSpacing(8)
        self.channels_layout.addStretch()

        self.channels_scroll.setWidget(self.channels_container)
        sb_l.addWidget(self.channels_scroll, 1)

        root.addWidget(sidebar, 1)

        # ===== Right: main panel =====
        right = QFrame()
        right.setObjectName("ChannelsMainCard")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(12, 12, 12, 12)
        right_l.setSpacing(10)

        self.main_stack = QStackedWidget()
        right_l.addWidget(self.main_stack, 1)

        # Placeholder page
        self.placeholder_page = QWidget()
        ph_l = QVBoxLayout(self.placeholder_page)
        ph_l.setContentsMargins(0, 0, 0, 0)
        ph_l.addStretch()
        empty_lbl = QLabel("Подключитесь или создайте свой первый канал")
        empty_lbl.setObjectName("ChannelEmptyHint")
        empty_lbl.setAlignment(Qt.AlignCenter)
        ph_l.addWidget(empty_lbl)
        ph_l.addStretch()
        self.main_stack.addWidget(self.placeholder_page)

        # Create channel page
        self.create_page = QWidget()
        cp_root = QVBoxLayout(self.create_page)
        cp_root.setContentsMargins(0, 0, 0, 0)
        cp_root.addStretch()

        create_card = QFrame()
        create_card.setObjectName("ChannelFormCard")
        create_l = QVBoxLayout(create_card)
        create_l.setContentsMargins(16, 16, 16, 16)
        create_l.setSpacing(10)

        create_title = QLabel("Создание канала")
        create_title.setObjectName("ChannelFormTitle")
        create_l.addWidget(create_title)

        avatar_row = QHBoxLayout()
        self.create_avatar_preview = AvatarLabel(size=72)
        self.create_avatar_preview.set_avatar(path="", login="channel", nickname="Канал")
        self.create_avatar_preview.set_online(None)
        avatar_row.addWidget(self.create_avatar_preview)

        self.select_avatar_btn = QPushButton("Установить аватар")
        self.select_avatar_btn.setObjectName("ChannelSecondaryButton")
        self.select_avatar_btn.clicked.connect(self.pick_create_avatar)
        install_opacity_feedback(self.select_avatar_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)
        avatar_row.addWidget(self.select_avatar_btn)
        avatar_row.addStretch()
        create_l.addLayout(avatar_row)

        self.create_name_input = QLineEdit()
        self.create_name_input.setObjectName("ChannelInput")
        self.create_name_input.setPlaceholderText("Название канала")
        create_l.addWidget(self.create_name_input)

        create_actions = QHBoxLayout()
        create_actions.addStretch()

        self.create_cancel_btn = QPushButton("Отменить")
        self.create_cancel_btn.setObjectName("ChannelSecondaryButton")
        self.create_cancel_btn.clicked.connect(self.open_default_view)
        create_actions.addWidget(self.create_cancel_btn)
        install_opacity_feedback(self.create_cancel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.create_confirm_btn = QPushButton("Создать")
        self.create_confirm_btn.setObjectName("ChannelPrimaryButton")
        self.create_confirm_btn.clicked.connect(self.create_channel)
        create_actions.addWidget(self.create_confirm_btn)
        install_opacity_feedback(self.create_confirm_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        create_l.addLayout(create_actions)

        cp_root.addWidget(create_card, alignment=Qt.AlignCenter)
        cp_root.addStretch()
        self.main_stack.addWidget(self.create_page)

        # Join page
        self.join_page = QWidget()
        jp_root = QVBoxLayout(self.join_page)
        jp_root.setContentsMargins(0, 0, 0, 0)
        jp_root.addStretch()

        join_card = QFrame()
        join_card.setObjectName("ChannelFormCard")
        join_l = QVBoxLayout(join_card)
        join_l.setContentsMargins(16, 16, 16, 16)
        join_l.setSpacing(10)

        join_title = QLabel("Подключение к каналу")
        join_title.setObjectName("ChannelFormTitle")
        join_l.addWidget(join_title)

        join_hint = QLabel("Введите код канала, чтобы подключиться")
        join_hint.setObjectName("ChannelFormHint")
        join_l.addWidget(join_hint)

        self.join_code_input = QLineEdit()
        self.join_code_input.setObjectName("ChannelInput")
        self.join_code_input.setPlaceholderText("Например: A1B2C3D4")
        self.join_code_input.returnPressed.connect(self.join_channel)
        join_l.addWidget(self.join_code_input)

        join_actions = QHBoxLayout()
        join_actions.addStretch()

        self.join_cancel_btn = QPushButton("Отменить")
        self.join_cancel_btn.setObjectName("ChannelSecondaryButton")
        self.join_cancel_btn.clicked.connect(self.open_default_view)
        join_actions.addWidget(self.join_cancel_btn)
        install_opacity_feedback(self.join_cancel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.join_confirm_btn = QPushButton("Подключиться")
        self.join_confirm_btn.setObjectName("ChannelPrimaryButton")
        self.join_confirm_btn.clicked.connect(self.join_channel)
        join_actions.addWidget(self.join_confirm_btn)
        install_opacity_feedback(self.join_confirm_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        join_l.addLayout(join_actions)

        jp_root.addWidget(join_card, alignment=Qt.AlignCenter)
        jp_root.addStretch()
        self.main_stack.addWidget(self.join_page)

        # Opened channel page
        self.channel_page = QWidget()
        ch_root = QVBoxLayout(self.channel_page)
        ch_root.setContentsMargins(0, 0, 0, 0)
        ch_root.setSpacing(10)

        top = QFrame()
        top.setObjectName("ChannelTopBar")
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(12, 8, 12, 8)
        top_l.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(1)

        self.channel_name_lbl = QLabel("Канал")
        self.channel_name_lbl.setObjectName("ChannelOpenTitle")
        title_col.addWidget(self.channel_name_lbl)

        self.channel_code_lbl = QLabel("")
        self.channel_code_lbl.setObjectName("ChannelOpenCode")
        title_col.addWidget(self.channel_code_lbl)

        top_l.addLayout(title_col)
        top_l.addStretch()

        self.channel_settings_btn = QPushButton("Настройки")
        self.channel_settings_btn.setObjectName("ChannelSecondaryButton")
        self.channel_settings_btn.clicked.connect(self.open_channel_settings)
        top_l.addWidget(self.channel_settings_btn)
        install_opacity_feedback(self.channel_settings_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        ch_root.addWidget(top)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(10)

        nav = QFrame()
        nav.setObjectName("ChannelInnerNav")
        nav_l = QVBoxLayout(nav)
        nav_l.setContentsMargins(8, 8, 8, 8)
        nav_l.setSpacing(6)

        self.voice_tab_btn = QPushButton("🔊 Голосовой")
        self.voice_tab_btn.setObjectName("ChannelInnerNavButton")
        self.voice_tab_btn.setCheckable(True)
        self.voice_tab_btn.clicked.connect(self.switch_to_voice_tab)
        nav_l.addWidget(self.voice_tab_btn)

        self.text_tab_btn = QPushButton("# Текстовый")
        self.text_tab_btn.setObjectName("ChannelInnerNavButton")
        self.text_tab_btn.setCheckable(True)
        self.text_tab_btn.clicked.connect(self.switch_to_text_tab)
        nav_l.addWidget(self.text_tab_btn)

        nav_l.addStretch()
        middle.addWidget(nav, 0)

        self.channel_inner_stack = QStackedWidget()

        # text tab
        text_tab = QWidget()
        t_l = QVBoxLayout(text_tab)
        t_l.setContentsMargins(0, 0, 0, 0)
        t_l.setSpacing(8)

        self.channel_messages_scroll = QScrollArea()
        self.channel_messages_scroll.setWidgetResizable(True)
        self.channel_messages_scroll.setObjectName("ChannelMessagesScroll")

        self.channel_messages_container = QWidget()
        self.channel_messages_layout = QVBoxLayout(self.channel_messages_container)
        self.channel_messages_layout.setContentsMargins(8, 10, 8, 10)
        self.channel_messages_layout.setSpacing(10)
        self.channel_messages_layout.addStretch()

        self.channel_messages_scroll.setWidget(self.channel_messages_container)
        t_l.addWidget(self.channel_messages_scroll, 1)

        msg_row = QHBoxLayout()
        self.channel_msg_input = QLineEdit()
        self.channel_msg_input.setObjectName("ChannelInput")
        self.channel_msg_input.setPlaceholderText("Сообщение в канал...")
        self.channel_msg_input.returnPressed.connect(self.send_channel_message)
        msg_row.addWidget(self.channel_msg_input, 1)

        self.channel_send_btn = QPushButton("Отправить")
        self.channel_send_btn.setObjectName("ChannelPrimaryButton")
        self.channel_send_btn.clicked.connect(self.send_channel_message)
        install_opacity_feedback(self.channel_send_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)
        msg_row.addWidget(self.channel_send_btn)

        t_l.addLayout(msg_row)

        self.channel_inner_stack.addWidget(text_tab)

        # voice tab
        voice_tab = QWidget()
        v_l = QVBoxLayout(voice_tab)
        v_l.setContentsMargins(6, 6, 6, 6)
        v_l.setSpacing(10)

        self.voice_status_lbl = QLabel("Вы не в голосовом канале")
        self.voice_status_lbl.setObjectName("ChannelVoiceStatus")
        self.voice_status_lbl.setAlignment(Qt.AlignCenter)
        v_l.addWidget(self.voice_status_lbl)

        self.voice_quality_lbl = QLabel("Качество: —")
        self.voice_quality_lbl.setObjectName("ChannelVoiceQuality")
        self.voice_quality_lbl.setAlignment(Qt.AlignCenter)
        v_l.addWidget(self.voice_quality_lbl)

        self.voice_join_btn = QPushButton("Войти в голосовой")
        self.voice_join_btn.setObjectName("ChannelPrimaryButton")
        self.voice_join_btn.clicked.connect(self.toggle_voice_join)
        v_l.addWidget(self.voice_join_btn, alignment=Qt.AlignCenter)
        install_opacity_feedback(self.voice_join_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        voice_ctrl_row = QHBoxLayout()
        voice_ctrl_row.setContentsMargins(0, 0, 0, 0)
        voice_ctrl_row.setSpacing(8)

        self.voice_mute_btn = QPushButton("Микрофон: ВКЛ")
        self.voice_mute_btn.setObjectName("ChannelSecondaryButton")
        self.voice_mute_btn.clicked.connect(self.toggle_voice_mute)
        voice_ctrl_row.addWidget(self.voice_mute_btn)
        install_opacity_feedback(self.voice_mute_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.voice_deafen_btn = QPushButton("Наушники: ВКЛ")
        self.voice_deafen_btn.setObjectName("ChannelSecondaryButton")
        self.voice_deafen_btn.clicked.connect(self.toggle_voice_deafen)
        voice_ctrl_row.addWidget(self.voice_deafen_btn)
        install_opacity_feedback(self.voice_deafen_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        v_l.addLayout(voice_ctrl_row)

        self.voice_access_hint_lbl = QLabel("В голосовом канале могут одновременно находиться несколько участников")
        self.voice_access_hint_lbl.setObjectName("ChannelAccessHint")
        self.voice_access_hint_lbl.setWordWrap(True)
        self.voice_access_hint_lbl.setAlignment(Qt.AlignCenter)
        v_l.addWidget(self.voice_access_hint_lbl)

        voice_members_card = QFrame()
        voice_members_card.setObjectName("ChannelVoiceMembersCard")
        vm_l = QVBoxLayout(voice_members_card)
        vm_l.setContentsMargins(10, 10, 10, 10)
        vm_l.setSpacing(8)

        vm_title = QLabel("Участники голосового")
        vm_title.setObjectName("ChannelVoiceMembersTitle")
        vm_l.addWidget(vm_title)

        self.voice_members_scroll = QScrollArea()
        self.voice_members_scroll.setObjectName("ChannelVoiceMembersScroll")
        self.voice_members_scroll.setWidgetResizable(True)

        self.voice_members_container = QWidget()
        self.voice_members_layout = QVBoxLayout(self.voice_members_container)
        self.voice_members_layout.setContentsMargins(0, 0, 0, 0)
        self.voice_members_layout.setSpacing(6)
        self.voice_members_layout.addStretch()

        self.voice_members_scroll.setWidget(self.voice_members_container)
        vm_l.addWidget(self.voice_members_scroll, 1)

        v_l.addWidget(voice_members_card, 1)

        self.channel_inner_stack.addWidget(voice_tab)

        middle.addWidget(self.channel_inner_stack, 1)
        ch_root.addLayout(middle, 1)

        self.main_stack.addWidget(self.channel_page)

        # Settings page (stage 2)
        self.settings_page = QWidget()
        sp_root = QVBoxLayout(self.settings_page)
        sp_root.setContentsMargins(0, 0, 0, 0)
        sp_root.setSpacing(10)

        sp_top = QFrame()
        sp_top.setObjectName("ChannelSettingsTopBar")
        sp_top_l = QHBoxLayout(sp_top)
        sp_top_l.setContentsMargins(12, 8, 12, 8)
        sp_top_l.setSpacing(8)

        self.settings_back_btn = QPushButton("← Назад")
        self.settings_back_btn.setObjectName("ChannelSecondaryButton")
        self.settings_back_btn.clicked.connect(self.close_channel_settings)
        sp_top_l.addWidget(self.settings_back_btn, 0, Qt.AlignLeft)

        self.settings_title_lbl = QLabel("Настройки канала")
        self.settings_title_lbl.setObjectName("ChannelOpenTitle")
        self.settings_title_lbl.setAlignment(Qt.AlignCenter)
        sp_top_l.addWidget(self.settings_title_lbl, 1)

        sp_top_l.addSpacing(10)
        sp_root.addWidget(sp_top)

        # general settings
        general = QFrame()
        general.setObjectName("ChannelSettingsCard")
        self.settings_general_card = general
        g_l = QVBoxLayout(general)
        g_l.setContentsMargins(12, 12, 12, 12)
        g_l.setSpacing(8)

        g_title = QLabel("Основное")
        g_title.setObjectName("ChannelSettingsSectionTitle")
        g_l.addWidget(g_title)

        self.settings_avatar_row = QHBoxLayout()
        self.settings_avatar_row.setSpacing(10)

        self.settings_avatar_preview = AvatarLabel(size=66)
        self.settings_avatar_preview.set_avatar(path="", login="channel", nickname="Канал")
        self.settings_avatar_preview.set_online(None)
        self.settings_avatar_row.addWidget(self.settings_avatar_preview, 0, Qt.AlignTop)

        self.settings_controls_col = QVBoxLayout()
        self.settings_controls_col.setSpacing(8)

        self.settings_buttons_grid = QGridLayout()
        self.settings_buttons_grid.setContentsMargins(0, 0, 0, 0)
        self.settings_buttons_grid.setHorizontalSpacing(8)
        self.settings_buttons_grid.setVerticalSpacing(8)

        self.settings_pick_avatar_btn = QPushButton("Сменить аватар")
        self.settings_pick_avatar_btn.setObjectName("ChannelSecondaryButton")
        self.settings_pick_avatar_btn.clicked.connect(self.pick_settings_avatar)
        self.settings_buttons_grid.addWidget(self.settings_pick_avatar_btn, 0, 0)

        self.settings_copy_code_btn = QPushButton("Скопировать код")
        self.settings_copy_code_btn.setObjectName("ChannelSecondaryButton")
        self.settings_copy_code_btn.clicked.connect(self.copy_channel_code)
        self.settings_buttons_grid.addWidget(self.settings_copy_code_btn, 0, 1)

        self.settings_regen_code_btn = QPushButton("Обновить код")
        self.settings_regen_code_btn.setObjectName("ChannelSecondaryButton")
        self.settings_regen_code_btn.clicked.connect(self.regenerate_channel_code)
        self.settings_buttons_grid.addWidget(self.settings_regen_code_btn, 0, 2)
        self.settings_buttons_grid.setColumnStretch(3, 1)

        self.settings_controls_col.addLayout(self.settings_buttons_grid)

        self.settings_name_input = QLineEdit()
        self.settings_name_input.setObjectName("ChannelInput")
        self.settings_name_input.setPlaceholderText("Название канала")
        self.settings_name_input.setMinimumHeight(36)
        self.settings_controls_col.addWidget(self.settings_name_input)

        self.settings_avatar_row.addLayout(self.settings_controls_col, 1)
        g_l.addLayout(self.settings_avatar_row)

        code_row = QHBoxLayout()
        code_caption = QLabel("Код приглашения:")
        code_caption.setObjectName("ChannelFormHint")
        code_row.addWidget(code_caption)

        self.settings_code_lbl = QLabel("—")
        self.settings_code_lbl.setObjectName("ChannelSettingsCode")
        code_row.addWidget(self.settings_code_lbl)
        code_row.addStretch()
        g_l.addLayout(code_row)

        self.settings_invite_block = QWidget()
        self.settings_invite_block.setObjectName("ChannelInviteBlock")
        self.settings_invite_row = QHBoxLayout(self.settings_invite_block)
        self.settings_invite_row.setContentsMargins(0, 2, 0, 0)
        self.settings_invite_row.setSpacing(8)

        self.settings_invite_caption = QLabel("Пригласить по логину:")
        self.settings_invite_caption.setObjectName("ChannelFormHint")
        self.settings_invite_row.addWidget(self.settings_invite_caption)

        self.settings_invite_login_input = QLineEdit()
        self.settings_invite_login_input.setObjectName("ChannelInput")
        self.settings_invite_login_input.setPlaceholderText("Логин пользователя")
        self.settings_invite_login_input.returnPressed.connect(self.send_channel_invite)
        self.settings_invite_row.addWidget(self.settings_invite_login_input, 1)

        self.settings_invite_btn = QPushButton("Пригласить")
        self.settings_invite_btn.setObjectName("ChannelSecondaryButton")
        self.settings_invite_btn.setMinimumWidth(112)
        self.settings_invite_btn.clicked.connect(self.send_channel_invite)
        self.settings_invite_row.addWidget(self.settings_invite_btn)

        g_l.addWidget(self.settings_invite_block)

        self.settings_invite_status = QLabel("")
        self.settings_invite_status.setObjectName("ChannelFormHint")
        self.settings_invite_status.setVisible(False)
        g_l.addWidget(self.settings_invite_status)

        g_actions = QHBoxLayout()
        g_actions.setContentsMargins(0, 2, 0, 0)
        g_actions.addStretch()
        self.settings_save_btn = QPushButton("Сохранить")
        self.settings_save_btn.setObjectName("ChannelPrimaryButton")
        self.settings_save_btn.clicked.connect(self.save_channel_settings)
        g_actions.addWidget(self.settings_save_btn)
        install_opacity_feedback(self.settings_save_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)
        g_l.addLayout(g_actions)

        sp_root.addWidget(general)

        access_card = QFrame()
        access_card.setObjectName("ChannelAccessCard")
        self.settings_access_card = access_card
        a_l = QVBoxLayout(access_card)
        a_l.setContentsMargins(12, 12, 12, 12)
        a_l.setSpacing(8)

        a_title = QLabel("Права доступа")
        a_title.setObjectName("ChannelSettingsSectionTitle")
        a_l.addWidget(a_title)

        self.settings_text_perm_row = QHBoxLayout()
        t_lbl = QLabel("Кто может писать в текстовый канал:")
        t_lbl.setObjectName("ChannelAccessLabel")
        t_lbl.setWordWrap(True)
        self.settings_text_perm_row.addWidget(t_lbl, 1)

        self.settings_text_perm_combo = QComboBox()
        self.settings_text_perm_combo.setObjectName("ChannelAccessCombo")
        self.settings_text_perm_combo.addItem("Все участники", "member")
        self.settings_text_perm_combo.addItem("Только модераторы и выше", "moderator")
        self.settings_text_perm_combo.addItem("Только админы", "admin")
        self.settings_text_perm_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.settings_text_perm_row.addWidget(self.settings_text_perm_combo)
        a_l.addLayout(self.settings_text_perm_row)

        self.settings_voice_perm_row = QHBoxLayout()
        v_lbl = QLabel("Кто может входить в голосовой:")
        v_lbl.setObjectName("ChannelAccessLabel")
        v_lbl.setWordWrap(True)
        self.settings_voice_perm_row.addWidget(v_lbl, 1)

        self.settings_voice_perm_combo = QComboBox()
        self.settings_voice_perm_combo.setObjectName("ChannelAccessCombo")
        self.settings_voice_perm_combo.addItem("Все участники", "member")
        self.settings_voice_perm_combo.addItem("Только модераторы и выше", "moderator")
        self.settings_voice_perm_combo.addItem("Только админы", "admin")
        self.settings_voice_perm_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.settings_voice_perm_row.addWidget(self.settings_voice_perm_combo)
        a_l.addLayout(self.settings_voice_perm_row)

        a_hint = QLabel("Владелец канала имеет полный доступ независимо от настроек")
        a_hint.setObjectName("ChannelAccessHint")
        a_hint.setWordWrap(True)
        a_l.addWidget(a_hint)

        sp_root.addWidget(access_card)

        members_card = QFrame()
        members_card.setObjectName("ChannelSettingsCard")
        self.settings_members_card = members_card
        m_l = QVBoxLayout(members_card)
        m_l.setContentsMargins(12, 12, 12, 12)
        m_l.setSpacing(8)

        m_title = QLabel("Участники")
        m_title.setObjectName("ChannelSettingsSectionTitle")
        m_l.addWidget(m_title)

        self.members_scroll = QScrollArea()
        self.members_scroll.setObjectName("ChannelMembersScroll")
        self.members_scroll.setWidgetResizable(True)

        self.members_container = QWidget()
        self.members_layout = QVBoxLayout(self.members_container)
        self.members_layout.setContentsMargins(0, 0, 0, 0)
        self.members_layout.setSpacing(6)
        self.members_layout.addStretch()

        self.members_scroll.setWidget(self.members_container)
        m_l.addWidget(self.members_scroll, 1)

        danger_row = QHBoxLayout()
        danger_row.addStretch()

        self.leave_channel_btn = QPushButton("Выйти из канала")
        self.leave_channel_btn.setObjectName("ChannelTinyDangerButton")
        self.leave_channel_btn.clicked.connect(self.ask_leave_channel)
        danger_row.addWidget(self.leave_channel_btn)
        install_opacity_feedback(self.leave_channel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.delete_channel_btn = QPushButton("Удалить канал")
        self.delete_channel_btn.setObjectName("ChannelTinyDangerButton")
        self.delete_channel_btn.clicked.connect(self.ask_delete_channel)
        danger_row.addWidget(self.delete_channel_btn)
        install_opacity_feedback(self.delete_channel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        m_l.addLayout(danger_row)

        sp_root.addWidget(members_card, 1)

        self.settings_confirm = QFrame()
        self.settings_confirm.setObjectName("ChannelInlineConfirm")
        self.settings_confirm.setVisible(False)
        c_l = QHBoxLayout(self.settings_confirm)
        c_l.setContentsMargins(12, 8, 12, 8)
        c_l.setSpacing(8)

        self.settings_confirm_text = QLabel("")
        self.settings_confirm_text.setObjectName("ChannelInlineConfirmText")
        self.settings_confirm_text.setWordWrap(True)
        c_l.addWidget(self.settings_confirm_text, 1)

        self.settings_confirm_cancel = QPushButton("Отмена")
        self.settings_confirm_cancel.setObjectName("ChannelSecondaryButton")
        self.settings_confirm_cancel.clicked.connect(self.hide_settings_confirm)
        c_l.addWidget(self.settings_confirm_cancel)
        install_opacity_feedback(self.settings_confirm_cancel, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.settings_confirm_apply = QPushButton("Подтвердить")
        self.settings_confirm_apply.setObjectName("ChannelTinyDangerButton")
        self.settings_confirm_apply.clicked.connect(self.apply_settings_confirm)
        c_l.addWidget(self.settings_confirm_apply)
        install_opacity_feedback(self.settings_confirm_apply, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        sp_root.addWidget(self.settings_confirm)

        self.main_stack.addWidget(self.settings_page)

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
        self._messages_signature = ""
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
        self.compact_toggle_btn.setChecked(False)
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

    def _rebuild_settings_buttons_grid(self, stacked: bool):
        if not getattr(self, "settings_buttons_grid", None):
            return

        while self.settings_buttons_grid.count():
            item = self.settings_buttons_grid.takeAt(0)
            # widgets remain owned by parent; no extra handling required
            _ = item

        buttons = [
            self.settings_pick_avatar_btn,
            self.settings_copy_code_btn,
            self.settings_regen_code_btn,
        ]
        for btn in buttons:
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        if stacked:
            self.settings_buttons_grid.addWidget(self.settings_pick_avatar_btn, 0, 0, 1, 2)
            self.settings_buttons_grid.addWidget(self.settings_copy_code_btn, 1, 0)
            self.settings_buttons_grid.addWidget(self.settings_regen_code_btn, 1, 1)
            self.settings_buttons_grid.setColumnStretch(0, 1)
            self.settings_buttons_grid.setColumnStretch(1, 1)
            self.settings_buttons_grid.setColumnStretch(2, 0)
            self.settings_buttons_grid.setColumnStretch(3, 0)
        else:
            self.settings_buttons_grid.addWidget(self.settings_pick_avatar_btn, 0, 0)
            self.settings_buttons_grid.addWidget(self.settings_copy_code_btn, 0, 1)
            self.settings_buttons_grid.addWidget(self.settings_regen_code_btn, 0, 2)
            self.settings_buttons_grid.setColumnStretch(0, 0)
            self.settings_buttons_grid.setColumnStretch(1, 0)
            self.settings_buttons_grid.setColumnStretch(2, 0)
            self.settings_buttons_grid.setColumnStretch(3, 1)

    def _set_box_layout_direction(self, layout, direction):
        if isinstance(layout, QBoxLayout):
            if layout.direction() != direction:
                layout.setDirection(direction)

    def _apply_settings_responsive_layout(self, force: bool = False):
        if not getattr(self, "settings_page", None):
            return

        area_w = self.main_stack.width() if getattr(self, "main_stack", None) else self.width()
        area_w = max(0, int(area_w or self.width() or 0))

        narrow = area_w < 980
        stacked_buttons = area_w < 900
        compact_rows = area_w < 780
        mode = (narrow, stacked_buttons, compact_rows)

        if (not force) and mode == getattr(self, "_settings_layout_mode", None):
            return
        self._settings_layout_mode = mode

        self._set_box_layout_direction(
            self.settings_avatar_row,
            QBoxLayout.TopToBottom if narrow else QBoxLayout.LeftToRight,
        )
        self.settings_avatar_row.setSpacing(8 if narrow else 10)

        self._rebuild_settings_buttons_grid(stacked=stacked_buttons)

        self._set_box_layout_direction(
            self.settings_invite_row,
            QBoxLayout.TopToBottom if compact_rows else QBoxLayout.LeftToRight,
        )
        self.settings_invite_btn.setMinimumWidth(0 if compact_rows else 112)

        self._set_box_layout_direction(
            self.settings_text_perm_row,
            QBoxLayout.TopToBottom if compact_rows else QBoxLayout.LeftToRight,
        )
        self._set_box_layout_direction(
            self.settings_voice_perm_row,
            QBoxLayout.TopToBottom if compact_rows else QBoxLayout.LeftToRight,
        )

        self.settings_text_perm_combo.setMinimumWidth(0 if compact_rows else 210)
        self.settings_voice_perm_combo.setMinimumWidth(0 if compact_rows else 210)

        self.settings_invite_caption.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def _set_invites_dropdown_open(self, opened: bool):
        opened = bool(opened)
        self.invites_toggle_btn.setChecked(opened)
        self.invites_dropdown.setVisible(opened)
        self.invites_toggle_btn.setText("ПРИГЛАШЕНИЯ ▾" if opened else "ПРИГЛАШЕНИЯ ▸")

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
            item = self.channels_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def set_compact_mode(self, enabled: bool):
        self._compact_mode = bool(enabled)
        self.compact_toggle_btn.setText("Компактно ✓" if self._compact_mode else "Компактно")
        self.channels_layout.setSpacing(5 if self._compact_mode else 8)
        self.render_channels(force=True)

    def _show_channels_skeleton(self, count: int = 6):
        self._channels_skeleton_visible = True
        self._clear_channels_list()
        for _ in range(max(2, int(count))):
            sk = QFrame()
            sk.setObjectName("ChannelsSkeletonCard")
            self.channels_layout.insertWidget(self.channels_layout.count() - 1, sk)

    def _make_channels_empty_state(self, title: str, subtitle: str) -> QFrame:
        card = QFrame()
        card.setObjectName("ChannelsEmptyStateCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(5)

        icon = QLabel("🛰️")
        icon.setObjectName("ChannelsEmptyStateIcon")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)

        t = QLabel(title)
        t.setObjectName("ChannelsEmptyStateTitle")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)

        s = QLabel(subtitle)
        s.setObjectName("ChannelsEmptyStateSub")
        s.setAlignment(Qt.AlignCenter)
        s.setWordWrap(True)
        lay.addWidget(s)
        return card

    def _clear_invites_list(self):
        for i in reversed(range(self.invites_layout.count() - 1)):
            item = self.invites_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_invites(self, force: bool = False):
        digest = self._invites_digest(self._invites)
        if (not force) and digest == self._invites_signature:
            return
        self._invites_signature = digest

        self._clear_invites_list()
        invites = list(self._invites or [])
        self._update_invites_indicator(len(invites))

        # Если приглашений нет — держим список свернутым.
        if not invites and self.invites_toggle_btn.isChecked():
            self._set_invites_dropdown_open(False)

        if not invites:
            empty = QLabel("📭 Нет входящих приглашений")
            empty.setObjectName("ChannelsListEmpty")
            empty.setAlignment(Qt.AlignCenter)
            self.invites_layout.insertWidget(0, empty)
            return

        for inv in invites:
            item = ChannelInviteItem(
                invite=inv,
                on_accept=self.accept_channel_invite,
                on_decline=self.decline_channel_invite,
            )
            self.invites_layout.insertWidget(self.invites_layout.count() - 1, item)

    def _clear_channel_messages(self):
        for i in reversed(range(self.channel_messages_layout.count() - 1)):
            item = self.channel_messages_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def _clear_members_list(self):
        for i in reversed(range(self.members_layout.count() - 1)):
            item = self.members_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def _clear_voice_members_list(self):
        for i in reversed(range(self.voice_members_layout.count() - 1)):
            item = self.voice_members_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def _set_channel_send_busy(self, busy: bool):
        self._message_send_inflight = bool(busy)
        self.channel_send_btn.setEnabled(not busy and bool((self._settings_permissions or {}).get("can_send_text", True)))
        self.channel_send_btn.setText("Отправка..." if busy else "Отправить")

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
        self.channel_code_lbl.setText(f"Код приглашения: {code}" if code else "")

    def _apply_channel_permissions_ui(self):
        perms = self._settings_permissions or {}
        can_send_text = bool(perms.get("can_send_text", True))
        can_join_voice = bool(perms.get("can_join_voice", True))
        voice_req = (perms.get("voice_min_role") or "member").strip().lower()

        # text controls
        if can_send_text:
            self.channel_msg_input.setEnabled(True)
            self.channel_send_btn.setEnabled(not self._message_send_inflight)
            self.channel_msg_input.setPlaceholderText("Сообщение в канал...")
        else:
            self.channel_msg_input.setEnabled(False)
            self.channel_send_btn.setEnabled(False)
            text_req = (perms.get("text_min_role") or "admin").strip().lower()
            if text_req == "admin":
                self.channel_msg_input.setPlaceholderText("Только владельцы и админы могут писать в этот канал")
            elif text_req == "moderator":
                self.channel_msg_input.setPlaceholderText("Только модераторы и выше могут писать в этот канал")
            else:
                self.channel_msg_input.setPlaceholderText("У вас нет прав на отправку сообщений")

        # voice controls
        if self._voice_joined:
            self.voice_join_btn.setEnabled(not self._voice_transitioning)
            self.voice_join_btn.setText("Отключение..." if self._voice_transitioning else "Выйти из голосового")
            self.voice_access_hint_lbl.setText("Вы подключены к голосовому каналу")
        else:
            self.voice_join_btn.setText("Подключение..." if self._voice_transitioning else "Войти в голосовой")
            self.voice_join_btn.setEnabled(can_join_voice and (not self._voice_transitioning))
            if can_join_voice:
                self.voice_access_hint_lbl.setText("В голосовом канале могут одновременно находиться несколько участников")
            else:
                if voice_req == "admin":
                    self.voice_access_hint_lbl.setText("Вход в голосовой разрешён только владельцу и админам")
                elif voice_req == "moderator":
                    self.voice_access_hint_lbl.setText("Вход в голосовой разрешён только модераторам и выше")
                else:
                    self.voice_access_hint_lbl.setText("У вас нет доступа к голосовому каналу")

        if self.active_channel and self.channel_inner_stack.currentIndex() == 1 and (not can_join_voice) and (not self._voice_joined):
            self.voice_status_lbl.setText("Нет прав для входа в голосовой канал")
            self.voice_quality_lbl.setText("Качество: —")

        can_manage = bool(perms.get("manage_channel", False))
        can_invite = bool(perms.get("can_invite", False))
        can_delete = bool(perms.get("delete_channel", False))

        # Показываем/скрываем только тот функционал, который реально доступен по правам.
        self.settings_pick_avatar_btn.setVisible(can_manage)
        self.settings_save_btn.setVisible(can_manage)
        self.settings_regen_code_btn.setVisible(can_manage)
        self.settings_name_input.setVisible(can_manage)

        # Блок политики доступа (текст/голос) доступен только владельцу (manage_channel).
        self.settings_access_card.setVisible(can_manage)

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
        digest = f"compact:{int(self._compact_mode)}\n" + self._channels_digest(self.channels, current_id)
        if (not force) and digest == self._channels_signature:
            return
        self._channels_signature = digest

        self.channels_scroll.setUpdatesEnabled(False)
        try:
            self._clear_channels_list()
            self._channels_skeleton_visible = False

            if not self.channels:
                empty = self._make_channels_empty_state(
                    title="Пока нет подключённых каналов",
                    subtitle="Создайте новый канал или подключитесь по коду.",
                )
                self.channels_layout.insertWidget(self.channels_layout.count() - 1, empty)
                return

            for ch in self.channels:
                item = ChannelListItem(
                    channel=ch,
                    active=(int(ch.get("id", 0)) == current_id),
                    on_click=lambda c=ch: self.open_channel(c),
                    compact=self._compact_mode,
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
        self.hide_settings_confirm()
        self.create_name_input.clear()
        self._create_avatar_path = ""
        self.create_avatar_preview.set_avatar(path="", login="channel", nickname="Канал")
        self.main_stack.setCurrentWidget(self.create_page)
        if self.messages_timer.isActive():
            self.messages_timer.stop()

    def open_join_page(self):
        self.hide_settings_confirm()
        self.join_code_input.clear()
        self.main_stack.setCurrentWidget(self.join_page)
        if self.messages_timer.isActive():
            self.messages_timer.stop()

    def open_channel(self, channel: dict):
        if not channel:
            return

        self.hide_settings_confirm()

        new_id = int(channel.get("id", 0) or 0)
        old_id = self._active_channel_id()

        # Switch voice room if needed
        if self._voice_joined and old_id and new_id and old_id != new_id:
            self.stop_voice_session(show_toast=False)

        self.active_channel = dict(channel)
        self._channel_details = {}
        self._settings_permissions = {}
        self._messages_signature = ""
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

        self._create_avatar_path = file_path
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
            self.show_toast("Введите код канала")
            return

        self._joining_channel = True
        payload = {"action": "join_channel", "code": code}

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.show_toast(resp.get("message", "Не удалось подключиться к каналу"))
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

        self._loading_channels = True
        payload = {"action": "get_my_channels"}

        def cb(resp):
            try:
                self._channels_loaded_once = True
                if resp.get("status") != "ok":
                    self.channels = []
                    self.render_channels(force=True)
                    return

                self.channels = resp.get("channels", []) or []

                # keep active channel if still exists
                cur_id = self._active_channel_id()
                if preferred_channel_id:
                    cur_id = preferred_channel_id

                matched = None
                if cur_id:
                    matched = next((c for c in self.channels if int(c.get("id", 0)) == int(cur_id)), None)

                if matched:
                    self.active_channel = dict(matched)
                    self._apply_channel_header()
                else:
                    # active channel deleted/unavailable
                    if self._voice_joined:
                        self.stop_voice_session(show_toast=False)
                    self.active_channel = None
                    self._channel_details = {}
                    self._settings_permissions = {}
                    self._messages_signature = ""
                    self._voice_participants = []
                    self._voice_participants_signature = ""
                    self._clear_voice_members_list()
                    self.hide_settings_confirm()
                    self.main_stack.setCurrentWidget(self.placeholder_page)
                    if self.messages_timer.isActive():
                        self.messages_timer.stop()
                    self._apply_channel_permissions_ui()

                self.render_channels()

                current_page = self.main_stack.currentWidget()
                if self.active_channel and current_page in (self.placeholder_page,):
                    self.open_channel(self.active_channel)
                elif self.active_channel and current_page == self.settings_page and not self._loading_channel_details:
                    # keep settings page in sync with periodic refresh
                    self.load_channel_details(silent=True)

                self._apply_channel_permissions_ui()

            finally:
                self._loading_channels = False

        self.start_request(payload, cb)

    # ------------------------------------------------------------------
    # Text channel
    # ------------------------------------------------------------------
    def switch_to_text_tab(self):
        self.text_tab_btn.setChecked(True)
        self.voice_tab_btn.setChecked(False)
        self.channel_inner_stack.setCurrentIndex(0)
        self._apply_channel_permissions_ui()

        if self.active_channel and self.main_stack.currentWidget() == self.channel_page and not self.messages_timer.isActive():
            self.messages_timer.start()

    def switch_to_voice_tab(self):
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
        if not self._alive or self._loading_messages or not self.active_channel:
            return
        if (not force) and (not self._is_poll_allowed()):
            return
        if self.main_stack.currentWidget() != self.channel_page:
            return
        if self.channel_inner_stack.currentIndex() != 0:
            return

        channel_id = self._active_channel_id()
        if channel_id <= 0:
            return

        self._loading_messages = True
        if not self._messages_signature:
            self._clear_channel_messages()
            for _ in range(4):
                sk = QFrame()
                sk.setObjectName("ChannelMsgSkeleton")
                self.channel_messages_layout.insertWidget(self.channel_messages_layout.count() - 1, sk)

        payload = {
            "action": "get_channel_messages",
            "channel_id": channel_id,
            "limit": 200,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    return

                messages = resp.get("messages", []) or []
                digest = self._messages_digest(messages)
                if digest == self._messages_signature:
                    return

                # Если пользователь не внизу списка, сохраняем позицию скролла.
                sb = self.channel_messages_scroll.verticalScrollBar()
                prev_val = sb.value()
                was_near_bottom = (sb.maximum() - sb.value()) <= 80

                self.channel_messages_scroll.setUpdatesEnabled(False)
                self._clear_channel_messages()

                if not messages:
                    hint = QLabel("Пока нет сообщений. Напишите первым 👋")
                    hint.setObjectName("ChannelTextEmptyHint")
                    hint.setAlignment(Qt.AlignCenter)
                    self.channel_messages_layout.insertWidget(self.channel_messages_layout.count() - 1, hint)
                    self._messages_signature = digest
                    return

                for msg in messages:
                    from_user = msg.get("from_user", "")
                    is_out = from_user == self.ctx.login
                    bubble = ChannelMessageBubble(
                        text=msg.get("text", ""),
                        author=("Вы" if is_out else from_user),
                        is_outgoing=is_out,
                        time_text=self._format_time(msg.get("created_at", "")),
                    )
                    self.channel_messages_layout.insertWidget(self.channel_messages_layout.count() - 1, bubble)

                self._messages_signature = digest

                if was_near_bottom:
                    sb.setValue(sb.maximum())
                else:
                    sb.setValue(min(prev_val, sb.maximum()))
            finally:
                self.channel_messages_scroll.setUpdatesEnabled(True)
                self._loading_messages = False

        self.start_request(payload, cb)

    def send_channel_message(self):
        if not self._alive or self._sending_channel_msg or not self.active_channel:
            return

        if not bool((self._settings_permissions or {}).get("can_send_text", True)):
            self.show_toast("У вас нет прав писать в этот канал")
            return

        text = self.channel_msg_input.text().strip()
        if not text:
            return

        channel_id = self._active_channel_id()
        if channel_id <= 0:
            return

        self._sending_channel_msg = True
        self._set_channel_send_busy(True)
        payload = {
            "action": "send_channel_message",
            "channel_id": channel_id,
            "text": text,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    self.show_toast(resp.get("message", "Не удалось отправить сообщение"))
                    # refresh permissions if server says forbidden
                    msg = (resp.get("message") or "").lower()
                    if "прав" in msg or "доступ" in msg:
                        self.load_channel_details(silent=True)
                    return
                # Форсируем перерисовку сразу после отправки.
                self._messages_signature = ""
                self.load_channel_messages(force=True)
            finally:
                self._sending_channel_msg = False
                self._set_channel_send_busy(False)

        self.start_request(payload, cb)
        self.channel_msg_input.clear()


    def _render_voice_participants(self):
        self._clear_voice_members_list()

        participants = self._voice_participants or []
        if not participants:
            empty = QLabel("Пока никто не подключён к голосовому каналу")
            empty.setObjectName("ChannelsEmptyList")
            empty.setWordWrap(True)
            self.voice_members_layout.insertWidget(self.voice_members_layout.count() - 1, empty)
            return

        for part in participants:
            row = VoiceParticipantItem(participant=part, current_login=self.ctx.login)
            self.voice_members_layout.insertWidget(self.voice_members_layout.count() - 1, row)

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
        }
        self.start_request(payload, lambda _resp: None)

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
                    speaking = bool(activity.get("me_speaking", False))
                except Exception:
                    speaking = False
                self._push_voice_presence(speaking=speaking, joined=True)

        # Refresh participant list only while voice tab is visible in foreground.
        if (force_pull or self.channel_inner_stack.currentIndex() == 1) and foreground:
            self.load_voice_participants(force=force_pull)

    # ------------------------------------------------------------------
    # Settings page (stage 2)
    # ------------------------------------------------------------------
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

        self._loading_channel_details = True
        payload = {
            "action": "get_channel_details",
            "channel_id": channel_id,
        }

        def cb(resp):
            try:
                if resp.get("status") != "ok":
                    if not silent:
                        self.show_toast(resp.get("message", "Не удалось загрузить настройки канала"))
                    return

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

        self._settings_avatar_path = file_path
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

        self._saving_channel_settings = True
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
                    self.show_toast(resp.get("message", "Не удалось сохранить настройки"))
                    return

                ch = resp.get("channel") or {}
                if ch:
                    self.active_channel = dict({**(self.active_channel or {}), **ch})
                    self._apply_channel_header()

                self.show_toast("Настройки канала сохранены")
                self.load_channels(force_refresh=True, preferred_channel_id=self._active_channel_id())
                self.load_channel_details(silent=True)
            finally:
                self._saving_channel_settings = False

        self.start_request(payload, cb)

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
            text="Выйти из этого канала?",
            action_type="leave_channel",
            payload={},
        )

    def ask_delete_channel(self):
        self.show_settings_confirm(
            text="Удалить канал полностью? Это действие нельзя отменить.",
            action_type="delete_channel",
            payload={},
        )

    def show_settings_confirm(self, text: str, action_type: str, payload: dict):
        self._confirm_action = {
            "type": action_type,
            "payload": payload or {},
        }
        self.settings_confirm_text.setText(text or "Подтвердите действие")
        self.settings_confirm.setVisible(True)

    def hide_settings_confirm(self):
        self._confirm_action = None
        self.settings_confirm.setVisible(False)

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
                self._messages_signature = ""
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
                self._messages_signature = ""
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

        self.voice_mute_btn.setEnabled(joined)
        self.voice_deafen_btn.setEnabled(joined)

        self.voice_mute_btn.setText("Микрофон: ВЫКЛ" if self._voice_muted else "Микрофон: ВКЛ")
        self.voice_deafen_btn.setText("Наушники: ВЫКЛ" if self._voice_deafened else "Наушники: ВКЛ")

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

        # Avoid audio device conflicts with private peer-to-peer calls
        main_win = self.window()
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
            self._voice_client = VoiceClient(
                self.ctx.login,
                token=getattr(self.ctx, "session_token", "") or "",
                host=host,
                port=port,
            )
            self._voice_client.start(room_id=room_id)
            self._voice_joined = True
            self._last_voice_presence_push_ts = 0.0
            self._apply_voice_local_controls()
            self.voice_join_btn.setText("Выйти из голосового")
            self.voice_status_lbl.setText("Вы подключены к голосовому каналу")
            if not self.voice_stats_timer.isActive():
                self.voice_stats_timer.start()
            if not self.voice_presence_timer.isActive():
                self.voice_presence_timer.start()
            self._apply_channel_permissions_ui()
            self.sync_voice_presence(force_pull=True)
            self.show_toast("Подключено к голосовому каналу")
        except Exception as e:
            self._voice_joined = False
            if self._voice_client:
                try:
                    self._voice_client.stop()
                except Exception:
                    pass
            self._voice_client = None
            self.voice_join_btn.setText("Войти в голосовой")
            self.voice_status_lbl.setText("Не удалось подключиться к голосовому каналу")
            self.voice_quality_lbl.setText("Качество: —")
            self._apply_channel_permissions_ui()
            self.show_toast(f"Ошибка голосового канала: {e}")
        finally:
            self._voice_transitioning = False
            self._apply_channel_permissions_ui()

    def stop_voice_session(self, show_toast: bool = False):
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
        self.voice_join_btn.setText("Войти в голосовой")
        self.voice_status_lbl.setText("Вы не в голосовом канале")
        self.voice_quality_lbl.setText("Качество: —")

        if self.voice_stats_timer.isActive():
            self.voice_stats_timer.stop()
        if self.voice_presence_timer.isActive():
            self.voice_presence_timer.stop()

        if was_joined and channel_id > 0:
            self._leave_voice_presence(channel_id=channel_id)
            self.load_voice_participants(force=True)

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
            me = bool(activity.get("me_speaking", False))
            peer = bool(activity.get("peer_speaking", False))

            if self._voice_deafened:
                state = "Вы в канале (звук выключен)"
            elif self._voice_muted and peer:
                state = "Вы без микрофона · говорит другой участник"
            elif self._voice_muted:
                state = "Вы без микрофона"
            elif me and peer:
                state = "Вы и другие участники говорите"
            elif me:
                state = "Вы говорите"
            elif peer:
                state = "Говорит другой участник"
            else:
                state = "Голосовой канал подключен"

            self.voice_status_lbl.setText(state)
            self.voice_quality_lbl.setText(
                f"Качество: {quality} · Пинг {latency} ms · Джиттер {jitter} ms · Буфер {buffer_frames}"
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
