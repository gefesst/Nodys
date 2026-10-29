"""Approved channel-settings geometry; domain actions remain in ChannelsPage."""

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QRadioButton,
)


def build(page):
    from PySide6.QtWidgets import QScrollArea, QPushButton, QLineEdit
    from .widgets import ScrollSafeComboBox
    from ui.avatar_widget import AvatarLabel

    page._settings_revision = 0
    page.settings_page = QWidget()
    outer = QVBoxLayout(page.settings_page)
    outer.setContentsMargins(0, 0, 0, 0)
    page.settings_scroll = QScrollArea()
    page.settings_scroll.setWidgetResizable(True)
    page.settings_scroll.setFrameShape(QFrame.NoFrame)
    outer.addWidget(page.settings_scroll)
    page.settings_title_lbl = QLabel("Настройки канала")
    page.settings_title_lbl.setWordWrap(True)
    page.settings_avatar_preview = AvatarLabel(size=72)
    page.settings_avatar_preview.set_online(None)
    page.settings_name_input = QLineEdit()
    page.settings_name_input.setObjectName("ChannelInput")
    page.settings_name_input.textEdited.connect(page._mark_settings_edited)
    page.settings_code_lbl = QLabel("—")
    page.settings_invite_login_input = QLineEdit()
    page.settings_invite_login_input.setObjectName("ChannelInput")
    page.settings_invite_login_input.setPlaceholderText("Логин пользователя")
    page.settings_invite_login_input.returnPressed.connect(page.send_channel_invite)
    page.settings_invite_status = QLabel()
    page.settings_invite_status.setObjectName("ChannelFormHint")
    page.settings_invite_status.setWordWrap(True)
    for attr, text, handler, style in [
        (
            "settings_back_btn",
            "← Вернуться в канал",
            page.close_channel_settings,
            "ChannelSecondaryButton",
        ),
        (
            "settings_pick_avatar_btn",
            "Сменить аватар",
            page.pick_settings_avatar,
            "ChannelSecondaryButton",
        ),
        (
            "settings_copy_code_btn",
            "Копировать",
            page.copy_channel_code,
            "ChannelSecondaryButton",
        ),
        (
            "settings_regen_code_btn",
            "Обновить код",
            page.ask_regenerate_channel_code,
            "ChannelSecondaryButton",
        ),
        (
            "settings_invite_btn",
            "Пригласить",
            page.send_channel_invite,
            "ChannelPrimaryButton",
        ),
        (
            "settings_save_btn",
            "Сохранить",
            page.save_channel_settings,
            "ChannelPrimaryButton",
        ),
        (
            "leave_channel_btn",
            "Выйти из канала",
            page.ask_leave_channel,
            "ChannelTinyDangerButton",
        ),
        (
            "delete_channel_btn",
            "Удалить канал",
            page.ask_delete_channel,
            "ChannelTinyDangerButton",
        ),
    ]:
        button = QPushButton(text)
        button.setObjectName(style)
        button.clicked.connect(handler)
        setattr(page, attr, button)
    for attr in ("settings_text_perm_combo", "settings_voice_perm_combo"):
        combo = ScrollSafeComboBox()
        combo.setObjectName("ChannelAccessCombo")
        for label, role in [
            ("Все участники", "member"),
            ("Модераторы и выше", "moderator"),
            ("Только администраторы", "admin"),
        ]:
            combo.addItem(label, role)
        combo.activated.connect(page._mark_settings_edited)
        setattr(page, attr, combo)
    page.settings_sections = {}
    for key in ("general", "members", "access"):
        button = QPushButton()
        button.setObjectName("ChannelSettingsTab")
        button.setCheckable(True)
        button.toggled.connect(
            lambda checked, key=key: (
                page.show_settings_section(key) if checked else None
            )
        )
        page.settings_sections[key] = button
    page.members_scroll = QScrollArea()
    page.members_scroll.setWidgetResizable(True)
    page.members_scroll.setFrameShape(QFrame.NoFrame)
    page.members_container = QWidget()
    page.members_layout = QVBoxLayout(page.members_container)
    page.members_layout.setContentsMargins(0, 0, 0, 0)
    page.members_layout.addStretch()
    page.members_scroll.setWidget(page.members_container)
    page.settings_confirm = QFrame()
    page.settings_confirm_text = QLabel(page.settings_confirm)
    content = QWidget()
    root = QVBoxLayout(content)
    root.setContentsMargins(16, 8, 16, 30)
    root.setSpacing(0)

    def take(widget, layout, width=None, height=None):
        widget.setParent(content)
        widget.show()
        if width:
            widget.setMaximumWidth(width)
        if height:
            widget.setFixedHeight(height)
        if isinstance(layout, QHBoxLayout) and width:
            layout.addWidget(widget, width)
        else:
            layout.addWidget(widget)
        return widget

    take(page.settings_title_lbl, root, height=34)
    page.settings_title_lbl.setObjectName("FriendsTitle")
    root.addSpacing(8)
    take(page.settings_back_btn, root, height=17)
    page.settings_back_btn.setText("← Вернуться в канал")
    page.settings_back_btn.setStyleSheet(
        "text-align:left;border:0;padding:0;color:#A9B8CD;background:transparent;font-size:14px;"
    )
    root.addSpacing(15)
    divider = QFrame()
    divider.setObjectName("Divider")
    divider.setFixedHeight(1)
    root.addWidget(divider)
    root.addSpacing(19)
    tabs = QHBoxLayout()
    tabs.setSpacing(12)
    for key, text in [
        ("general", "Информация"),
        ("members", "Участники"),
        ("access", "Роли и доступ"),
    ]:
        button = page.settings_sections[key]
        take(button, tabs, 198, 40)
        button.setText(text)
    tabs.addStretch()
    root.addLayout(tabs)
    root.addSpacing(34)
    from .state_surfaces import LoadingState, EmptyState, InlineNote
    page.settings_loading_surface=LoadingState()
    page.settings_error_surface=EmptyState('Настройки недоступны',
        'Не удалось загрузить данные канала.','Повторить',
        lambda:page.load_channel_details(silent=False))
    page.settings_error_surface.layout().setContentsMargins(0,58,20,0)
    for surface in (page.settings_loading_surface,page.settings_error_surface):
        root.addWidget(surface);surface.hide()
    page._settings_load_state='ready'

    def card(attr):
        widget = QFrame()
        widget.setObjectName("FlatForm")
        setattr(page, attr, widget)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(22, 0, 22, 0)
        layout.setSpacing(0)
        root.addWidget(widget)
        return layout

    def caption(layout, text):
        label = QLabel(text)
        label.setObjectName("FieldTitle")
        label.setFixedHeight(17)
        layout.addWidget(label)
        layout.addSpacing(13)

    def field(widget, layout, width):
        take(widget, layout, width, 46)
        widget.setStyleSheet("min-height:22px;max-height:22px;padding:11px 14px;")

    general = card("settings_general_card")
    avatar = QHBoxLayout()
    avatar.setSpacing(24)
    take(page.settings_avatar_preview, avatar, height=72)
    page.settings_avatar_preview.size_px = 72
    page.settings_avatar_preview.setFixedSize(72, 72)
    take(page.settings_pick_avatar_btn, avatar, 200, 40)
    avatar.addStretch()
    general.addLayout(avatar)
    general.addSpacing(38)
    caption(general, "Название канала")
    field(page.settings_name_input, general, 640)
    general.addSpacing(24)
    caption(general, "Код приглашения")
    code = QHBoxLayout()
    code.setSpacing(16)
    take(page.settings_code_lbl, code, 300, 46)
    page.settings_code_lbl.setMinimumWidth(120)
    page.settings_code_lbl.setStyleSheet(
        "background:#17212D;border:1px solid #354458;border-radius:8px;padding:0 14px;font-size:15px;"
    )
    take(page.settings_copy_code_btn, code, 150, 40)
    page.settings_copy_code_btn.setText("Копировать")
    take(page.settings_regen_code_btn, code, 162, 40)
    code.addStretch()
    general.addLayout(code)
    general.addSpacing(24)
    page.settings_invite_block = QWidget()
    invite_block = QVBoxLayout(page.settings_invite_block)
    invite_block.setContentsMargins(0, 0, 0, 0)
    invite_block.setSpacing(0)
    general.addWidget(page.settings_invite_block)
    caption(invite_block, "Пригласить по логину")
    invite = QHBoxLayout()
    invite.setSpacing(16)
    field(page.settings_invite_login_input, invite, 470)
    take(page.settings_invite_btn, invite, 170, 40)
    page.settings_invite_btn.setObjectName("ChannelPrimaryButton")
    invite.addStretch()
    invite_block.addLayout(invite)
    take(page.settings_invite_status, general)
    page.settings_invite_status.hide()
    general.addSpacing(48)
    actions = QHBoxLayout()
    actions.setSpacing(16)
    take(page.settings_save_btn, actions, 170, 40)
    actions.addStretch()
    take(page.leave_channel_btn, actions, 220, 40)
    take(page.delete_channel_btn, actions, 270, 40)
    general.addLayout(actions)

    access = card("settings_access_card")
    label = QLabel("Кто может писать в текстовый канал")
    label.setObjectName("FieldHeading")
    label.setFixedHeight(26)
    access.addWidget(label)
    access.addSpacing(6)
    # Retain the existing combo as the single model for the protocol and permissions.
    page.settings_text_perm_combo.setParent(content)
    page.settings_text_perm_combo.hide()
    page.settings_text_radios = []
    for index, text in enumerate(
        ("Все участники", "Модераторы и выше", "Только администраторы")
    ):
        radio = QRadioButton(text)
        radio.setFixedHeight(52)
        radio.setStyleSheet(
            "QRadioButton {font-size:15px;spacing:14px;} QRadioButton::indicator {width:16px;height:16px;border:1px solid #354458;border-radius:8px;background:#17212D;} QRadioButton::indicator:checked {border:4px solid #91ADFF;background:#17212D;}"
        )
        radio.setChecked(index == page.settings_text_perm_combo.currentIndex())

        def choose_role(checked, i=index):
            if checked:
                page.settings_text_perm_combo.setCurrentIndex(i)
                page._mark_settings_edited()

        radio.toggled.connect(choose_role)
        access.addWidget(radio)
        page.settings_text_radios.append(radio)

    def synchronize_role(index):
        if 0 <= index < len(page.settings_text_radios):
            with QSignalBlocker(page.settings_text_radios[index]):
                page.settings_text_radios[index].setChecked(True)

    page.settings_text_perm_combo.currentIndexChanged.connect(synchronize_role)
    access.addSpacing(42)
    caption(access, "Кто может входить в голосовой")
    field(page.settings_voice_perm_combo, access, 640)
    page.settings_voice_perm_combo.setStyleSheet(
        "QComboBox {min-height:22px;max-height:22px;padding:11px 14px;background:#17212D;border:1px solid #354458;border-radius:10px;font-size:15px;} QComboBox::drop-down {border:0;width:28px;}"
    )
    access.addSpacing(38)
    note = QLabel("Владелец сохраняет полный доступ к своему каналу.")
    note.setObjectName("ChannelAccessHint")
    note.setWordWrap(True)
    note.setMinimumHeight(46)
    note.setStyleSheet(
        "background:#253142;border:1px solid #354458;border-radius:10px;color:#91ADFF;padding:0 16px;font-size:13px;"
    )
    access.addWidget(note)
    access.addSpacing(38)
    from .widgets import Button

    page.settings_access_save = Button("Сохранить", primary=True)
    page.settings_access_save.setFixedSize(170, 40)
    page.settings_access_save.clicked.connect(page.save_channel_settings)
    access.addWidget(page.settings_access_save, 0, Qt.AlignLeft)

    members = card("settings_members_card")
    take(page.members_scroll, members)
    page.members_scroll.setMinimumHeight(440)
    page.members_layout.setSpacing(18)
    take(page.settings_confirm, root)
    page.settings_confirm.hide()
    page.settings_feedback=InlineNote()
    root.addSpacing(29)
    root.addWidget(page.settings_feedback)
    root.addStretch()
    page.settings_scroll.setWidget(content)
    page.show_settings_section("general")
    page.main_stack.addWidget(page.settings_page)
    page._approved_settings_layout = True
