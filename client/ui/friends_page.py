from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QLineEdit,
    QMenu, QApplication, QDialog, QSizePolicy
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont

from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel
from ui.micro_interactions import install_opacity_feedback
from ui.toast import InlineToast


class FriendItem(QFrame):
    def __init__(
        self,
        login,
        nickname,
        avatar_path="",
        online=False,
        request_from=None,
        on_accept=None,
        on_decline=None,
        on_call=None,
        on_manage=None,
    ):
        super().__init__()
        self.setObjectName("FriendItem")
        self.setProperty("request", request_from is not None)
        self.setFixedHeight(88)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(18)

        avatar = AvatarLabel(size=44)
        avatar.set_avatar(path=avatar_path, login=login, nickname=nickname)
        avatar.set_online(online if request_from is None else None, ring_color="#2b2d31")
        layout.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(5)
        text_col.setAlignment(Qt.AlignVCenter)

        name = QLabel(nickname)
        name.setObjectName("FriendItemName")
        name.setFixedHeight(20)
        text_col.addWidget(name)

        sub = QLabel(f"@{login} · {'В сети' if online else 'Не в сети'}" if request_from is None else f"Запрос от: {login}")
        sub.setObjectName("FriendItemSub")
        sub.setFixedHeight(20)
        text_col.addWidget(sub)

        layout.addLayout(text_col)
        layout.addStretch()

        if request_from is None:
            # Монохромный символ лучше читается на зелёной кнопке.
            from ui.design.widgets import Button
            self.call_btn = Button('Позвонить','phone')
            self.call_btn.setObjectName("FriendCallButton")
            btn_size = 34
            self.call_btn.setFixedSize(156, 40)
            self.call_btn.setToolTip("Позвонить")
            if on_call:
                self.call_btn.clicked.connect(lambda: on_call(login))
            layout.addWidget(self.call_btn)
            install_opacity_feedback(self.call_btn, hover_opacity=0.99, pressed_opacity=0.93, duration_ms=80)

            self.more_btn = Button('', 'more')
            self.more_btn.setObjectName("FriendMoreButton")
            self.more_btn.setProperty("flat", True)
            self.more_btn.setFixedSize(42, 42)
            self.more_btn.setCursor(self.call_btn.cursor())
            f = self.more_btn.font()
            f.setBold(True)
            f.setWeight(QFont.Weight.Black)
            self.more_btn.setFont(f)
            if on_manage:
                self.more_btn.clicked.connect(lambda: on_manage(login, self.more_btn))
            layout.addSpacing(16)
            layout.addWidget(self.more_btn)
            install_opacity_feedback(self.more_btn, hover_opacity=0.99, pressed_opacity=0.93, duration_ms=80)

        if request_from is not None:
            btn_accept = QPushButton("Принять")
            btn_accept.setObjectName("AcceptButton")
            btn_accept.setFixedHeight(34)
            if on_accept:
                btn_accept.clicked.connect(lambda: on_accept(request_from))
            layout.addWidget(btn_accept)
            install_opacity_feedback(btn_accept, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

            btn_decline = QPushButton("Отклонить")
            btn_decline.setObjectName("DeclineButton")
            btn_decline.setFixedHeight(34)
            if on_decline:
                btn_decline.clicked.connect(lambda: on_decline(request_from))
            layout.addWidget(btn_decline)
            install_opacity_feedback(btn_decline, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)


class FriendsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = UserContext()

        # ThreadSafeMixin state
        self._threads = []
        self._alive = True

        # state flags
        self._loading_friends = False
        self._loading_requests = False
        self._finding_user = False
        self._sending_request = False
        self._found_user = None

        # cached server state for smooth updates
        self._friends_data = []
        self._requests_data = []
        self._render_key = None
        self._has_loaded_friends_once = False
        self._has_loaded_requests_once = False
        self._polling_enabled = True
        self._skeleton_visible = False

        self.setObjectName("FriendsPage")

        self.view_mode = 'all'
        from ui.design.tokens import LIST_WIDTH
        outer = QHBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName('SectionSidebar');sidebar.setFixedWidth(LIST_WIDTH)
        side=QVBoxLayout(sidebar);side.setContentsMargins(14,32,14,20);side.setSpacing(10)
        eyebrow=QLabel('ЛИЧНЫЕ');eyebrow.setObjectName('Eyebrow');eyebrow.setFixedHeight(12);eyebrow.setContentsMargins(8,0,0,0);side.addWidget(eyebrow)
        heading=QLabel('Друзья');heading.setObjectName('PageTitle');heading.setFixedHeight(31);heading.setContentsMargins(8,0,0,0);side.addWidget(heading);side.addSpacing(17)
        self.view_buttons={}
        for mode,text in [('all','Все друзья'),('online','В сети'),('requests','Заявки'),('add','Добавить друга')]:
            button=QPushButton(text);button.setObjectName("SectionTab");button.setCheckable(True);button.setChecked(mode=='all');button.clicked.connect(lambda checked=False,m=mode:self.set_view(m));side.addWidget(button);self.view_buttons[mode]=button
        side.addStretch();outer.addWidget(sidebar)
        work=QWidget();outer.addWidget(work,1)
        root = QVBoxLayout(work)
        root.setContentsMargins(40, 32, 48, 20)
        root.setSpacing(0)
        root.setAlignment(Qt.AlignTop)

        # ---------- Top bar card ----------
        topbar = QFrame()
        topbar.setObjectName("FriendsTopBar")
        topbar.setFixedHeight(62)
        head = QHBoxLayout(topbar)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)

        title = QLabel("Друзья")
        title.setObjectName("FriendsTitle")
        title_col = QVBoxLayout()
        title_col.setSpacing(6)
        title_col.addWidget(title)
        subtitle = QLabel("Люди, с которыми хочется быть на связи")
        self.subtitle=subtitle
        subtitle.setObjectName("FriendsSubtitle")
        title_col.addWidget(subtitle)
        head.addLayout(title_col)
        self.heading = title
        head.addStretch()


        self.add_btn = QPushButton("Добавить друга")
        self.add_btn.setObjectName("AddFriendButton")
        self.add_btn.clicked.connect(self.toggle_add_friend_panel)
        self.add_btn.hide()
        self.filter_input=QLineEdit();self.filter_input.setPlaceholderText('Найти друга');self.filter_input.setMaximumWidth(260)
        self.filter_input.textChanged.connect(lambda:self._render_if_needed(force=True));head.addWidget(self.filter_input)
        install_opacity_feedback(self.add_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        root.addWidget(topbar)
        root.addSpacing(10)
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        root.addWidget(divider)
        root.addSpacing(43)

        # ---------- Inline add panel ----------
        self.add_panel = QFrame()
        self.add_panel.setObjectName("FlatForm")
        self.add_panel.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Maximum)
        self.add_panel.setVisible(False)

        panel_lay = QVBoxLayout(self.add_panel)
        panel_lay.setContentsMargins(12, 12, 12, 12)
        panel_lay.setSpacing(8)

        panel_title = QLabel("Добавить друга по логину")
        panel_title.setObjectName("AddPanelTitle")
        panel_lay.addWidget(panel_title)

        row = QHBoxLayout()
        self.login_input = QLineEdit()
        self.login_input.setPlaceholderText("Введите логин пользователя")
        row.addWidget(self.login_input)

        self.find_btn = QPushButton("Найти")
        self.find_btn.setObjectName("FindUserButton")
        self.find_btn.clicked.connect(self.find_user_inline)
        row.addWidget(self.find_btn)
        install_opacity_feedback(self.find_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)
        panel_lay.addLayout(row)

        self.find_result = QLabel("")
        self.find_result.setObjectName("AddPanelHint")
        self.find_result.setWordWrap(True)
        panel_lay.addWidget(self.find_result)

        panel_actions = QHBoxLayout()
        panel_actions.addStretch()

        self.send_request_btn = QPushButton("Отправить запрос")
        self.send_request_btn.setObjectName("SendRequestButton")
        self.send_request_btn.setEnabled(False)
        self.send_request_btn.clicked.connect(self.send_request_inline)
        panel_actions.addWidget(self.send_request_btn)
        install_opacity_feedback(self.send_request_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.close_add_panel_btn = QPushButton("Скрыть")
        self.close_add_panel_btn.setObjectName("HideAddPanelButton")
        self.close_add_panel_btn.clicked.connect(self.hide_add_friend_panel)
        panel_actions.addWidget(self.close_add_panel_btn)
        install_opacity_feedback(self.close_add_panel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        panel_lay.addLayout(panel_actions)
        root.addWidget(self.add_panel)

        # ---------- Main content card ----------
        body_card = QFrame()
        self.body_card = body_card
        body_card.setObjectName("FriendsContentCard")
        body_lay = QVBoxLayout(body_card)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(8)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("FriendsScrollArea")

        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(16)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.container)
        body_lay.addWidget(self.scroll)
        root.addWidget(body_card, 1)

        # lightweight toast (внутри страницы, единый компонент)
        self._toast = InlineToast(
            self,
            object_name="InlineToast",
            min_width=220,
            max_width=460,
            horizontal_margin=12,
            bottom_margin=16,
        )

        # inline confirm card (внутри страницы, без отдельного окна)
        self._pending_remove_login = None
        self.inline_confirm = QFrame(self)
        self.inline_confirm.setObjectName("InlineConfirmCard")
        self.inline_confirm.setVisible(False)

        confirm_lay = QVBoxLayout(self.inline_confirm)
        confirm_lay.setContentsMargins(14, 12, 14, 12)
        confirm_lay.setSpacing(10)

        self.inline_confirm_text = QLabel("", self.inline_confirm)
        self.inline_confirm_text.setObjectName("InlineConfirmText")
        self.inline_confirm_text.setWordWrap(True)
        confirm_lay.addWidget(self.inline_confirm_text)

        confirm_btns = QHBoxLayout()
        confirm_btns.addStretch()

        self.inline_confirm_cancel_btn = QPushButton("Отмена", self.inline_confirm)
        self.inline_confirm_cancel_btn.setObjectName("InlineConfirmCancelButton")
        self.inline_confirm_cancel_btn.clicked.connect(self.hide_inline_delete_confirm)
        confirm_btns.addWidget(self.inline_confirm_cancel_btn)
        install_opacity_feedback(self.inline_confirm_cancel_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.inline_confirm_delete_btn = QPushButton("Удалить", self.inline_confirm)
        self.inline_confirm_delete_btn.setObjectName("InlineConfirmDeleteButton")
        self.inline_confirm_delete_btn.clicked.connect(self.confirm_remove_inline)
        confirm_btns.addWidget(self.inline_confirm_delete_btn)
        install_opacity_feedback(self.inline_confirm_delete_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        confirm_lay.addLayout(confirm_btns)

        # timer: чаще, но без перерисовки "в ноль" при каждом тике
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2500)

        self._show_skeleton(count=6)
        self.refresh()

    # ==================================================
    # lifecycle
    # ==================================================
    def reset_for_user(self):
        self._alive = True
        self._polling_enabled = True
        self._loading_friends = False
        self._loading_requests = False
        self._finding_user = False
        self._sending_request = False
        self._found_user = None

        self._friends_data = []
        self._requests_data = []
        self._render_key = None
        self._has_loaded_friends_once = False
        self._has_loaded_requests_once = False

        self.clear_list()
        self.hide_add_friend_panel()
        self.hide_inline_delete_confirm()
        self._show_skeleton(count=6)

    def closeEvent(self, event):
        self._alive = False
        if self.timer.isActive():
            self.timer.stop()
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)

    def _is_poll_allowed(self) -> bool:
        if not self._alive or not self._polling_enabled or not self.ctx.login:
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

    def set_polling_enabled(self, enabled: bool):
        self._polling_enabled = bool(enabled)
        if not self._polling_enabled:
            if self.timer.isActive():
                self.timer.stop()
            return
        # При возврате на вкладку делаем мгновенный refresh
        self.refresh()
        if not self.timer.isActive():
            self.timer.start(2500)

    # ==================================================
    # UI helpers
    # ==================================================
    def set_view(self, mode):
        self.view_mode=mode
        self.subtitle.setText({"all":"Люди, с которыми хочется быть на связи","online":"Друзья, которые сейчас в сети","requests":"Новые знакомства начинаются здесь","add":"Найдите человека по его логину"}[mode])
        for key,button in self.view_buttons.items():button.setChecked(key==mode)
        self.heading.setText({'all':'Друзья','online':'Друзья в сети','requests':'Заявки','add':'Добавить друга'}[mode])
        self.add_panel.setVisible(mode=='add');self.body_card.setVisible(mode!='add')
        self.filter_input.setVisible(mode!='add')
        self._render_if_needed(force=True)
        if mode=='add':self.login_input.setFocus()

    def toggle_add_friend_panel(self):self.set_view('add')

    def hide_add_friend_panel(self):
        self.set_view('all')
        self._reset_add_panel_state()

    def _reset_add_panel_state(self):
        self.login_input.clear()
        self.find_result.setText("")
        self.send_request_btn.setEnabled(False)
        self._found_user = None

    def clear_list(self):
        for i in reversed(range(self.list_layout.count() - 1)):
            item = self.list_layout.takeAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def _add_section_header(self, text: str):
        header = QLabel(text)
        header.setObjectName("SectionHeader")
        self.list_layout.insertWidget(self.list_layout.count() - 1, header)


    def _make_empty_state(self, title: str, subtitle: str) -> QFrame:
        card = QFrame()
        card.setObjectName("FriendsEmptyStateCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(5)

        from PySide6.QtSvgWidgets import QSvgWidget
        from ui.design.widgets import ASSETS
        icon = QSvgWidget(str(ASSETS / "illustration-friends.svg"))
        icon.setFixedSize(220,160)
        icon.setObjectName("FriendsEmptyStateIcon")
        lay.addWidget(icon,0,Qt.AlignHCenter)

        t = QLabel(title)
        t.setObjectName("FriendsEmptyStateTitle")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)

        s = QLabel(subtitle)
        s.setObjectName("FriendsEmptyStateSub")
        s.setWordWrap(True)
        s.setAlignment(Qt.AlignCenter)
        lay.addWidget(s)
        return card

    def _show_skeleton(self, count: int = 6):
        self._skeleton_visible = True
        self.clear_list()
        for _ in range(max(2, int(count))):
            sk = QFrame()
            sk.setObjectName("FriendsSkeletonCard")
            self.list_layout.insertWidget(self.list_layout.count() - 1, sk)

    def _state_key(self):
        req_key = tuple(sorted(self._requests_data))
        fr_key = tuple(sorted(
            (
                f.get("login", ""),
                f.get("nickname", ""),
                f.get("avatar", "") or "",
                bool(f.get("online", False)),
            )
            for f in self._friends_data
        ))
        return req_key, fr_key

    def _render_if_needed(self, force: bool = False):
        if not self._has_loaded_friends_once or not self._has_loaded_requests_once:
            return
        key=(self._state_key(),self.view_mode,self.filter_input.text())
        if not force and key==self._render_key:return
        self._render_key=key;self._skeleton_visible=False
        self.scroll.setUpdatesEnabled(False)
        self.clear_list()
        query=self.filter_input.text().casefold()
        count=0
        if self.view_mode=='requests':
            for login in self._requests_data:
                if query not in login.casefold():continue
                item=FriendItem(login,login,request_from=login,on_accept=self.accept_request,on_decline=self.decline_request)
                self.list_layout.insertWidget(self.list_layout.count()-1,item);count+=1
        else:
            for friend in sorted(self._friends_data,key=lambda f:(not f.get('online'),f.get('nickname','').casefold())):
                if self.view_mode=='online' and not friend.get('online'):continue
                if query not in (friend.get('nickname','')+' '+friend['login']).casefold():continue
                item=FriendItem(friend['login'],friend.get('nickname',friend['login']),friend.get('avatar',''),friend.get('online',False),on_call=self.call_friend,on_manage=self.show_friend_actions_menu)
                self.list_layout.insertWidget(self.list_layout.count()-1,item);count+=1
        if not count:
            empty=self._make_empty_state('Ничего не найдено' if query else ('Нет заявок' if self.view_mode=='requests' else 'Пока здесь никого нет'),'Попробуйте другой поиск или добавьте друга по логину.')
            self.list_layout.insertWidget(self.list_layout.count()-1,empty)
        self.view_buttons['requests'].setText('Заявки'+(f' · {len(self._requests_data)}' if self._requests_data else ''))
        self.scroll.setUpdatesEnabled(True)

    # ==================================================
    # refresh
    # ==================================================
    def refresh(self):
        if not self._is_poll_allowed():
            return
        # Не очищаем UI заранее — только обновляем кэш и перерисовываем при изменениях
        if not self._has_loaded_friends_once or not self._has_loaded_requests_once:
            self._show_skeleton(count=6)
        self.load_requests()
        self.load_friends()

    # ==================================================
    # requests
    # ==================================================
    def load_requests(self):
        if not self._alive or self._loading_requests or not self.ctx.login:
            return

        self._loading_requests = True
        data = {"action": "get_friend_requests", "login": self.ctx.login}

        def cb(resp):
            try:
                self.handle_requests(resp)
            finally:
                self._loading_requests = False

        self.start_request(data, cb)

    def handle_requests(self, resp):
        if resp.get("status") == "ok":
            self._requests_data = list(resp.get("requests", []) or [])
        else:
            self._requests_data = []
        # даже при ошибке считаем попытку завершённой, чтобы UI мог рендериться
        self._has_loaded_requests_once = True
        self._render_if_needed()

    def accept_request(self, from_user):
        data = {"action": "accept_friend_request", "login": self.ctx.login, "from_user": from_user}

        def cb(resp):
            if resp.get("status") == "ok":
                # Мгновенно убираем заявку из UI, затем фоново сверяем с сервером.
                self._requests_data = [u for u in self._requests_data if u != from_user]
                self._render_if_needed(force=True)
                self.load_friends()
            self.load_requests()

        self.start_request(data, cb)

    def decline_request(self, from_user):
        data = {"action": "decline_friend_request", "login": self.ctx.login, "from_user": from_user}

        def cb(resp):
            if resp.get("status") == "ok":
                self._requests_data = [u for u in self._requests_data if u != from_user]
                self._render_if_needed(force=True)
            self.load_requests()

        self.start_request(data, cb)

    # ==================================================
    # friends
    # ==================================================
    def load_friends(self):
        if not self._alive or self._loading_friends or not self.ctx.login:
            return

        self._loading_friends = True
        data = {"action": "get_friends", "login": self.ctx.login}

        def cb(resp):
            try:
                self.handle_friends(resp)
            finally:
                self._loading_friends = False

        self.start_request(data, cb)

    def handle_friends(self, resp):
        if resp.get("status") == "ok":
            self._friends_data = list(resp.get("friends", []) or [])
        else:
            self._friends_data = []
        self._has_loaded_friends_once = True
        self._render_if_needed()

    # ==================================================
    # add friend inline
    # ==================================================
    def find_user_inline(self):
        if self._finding_user or not self._alive:
            return

        login = self.login_input.text().strip()
        if not login:
            self.find_result.setText("Введи логин для поиска.")
            self.send_request_btn.setEnabled(False)
            self._found_user = None
            return

        if login == self.ctx.login:
            self.find_result.setText("Нельзя добавить самого себя.")
            self.send_request_btn.setEnabled(False)
            self._found_user = None
            return

        self._finding_user = True
        self.find_result.setText("Ищу пользователя...")
        self.send_request_btn.setEnabled(False)
        self._found_user = None

        data = {"action": "find_user", "login": login}

        def cb(resp):
            try:
                if resp.get("status") == "ok":
                    self._found_user = {
                        "login": resp.get("login", ""),
                        "nickname": resp.get("nickname", resp.get("login", "")),
                        "avatar": resp.get("avatar", "")
                    }
                    self.find_result.setText(
                        f"Найден: {self._found_user['nickname']} ({self._found_user['login']})"
                    )
                    self.send_request_btn.setEnabled(True)
                else:
                    self._found_user = None
                    self.find_result.setText(resp.get("message", "Пользователь не найден"))
                    self.send_request_btn.setEnabled(False)
            finally:
                self._finding_user = False

        self.start_request(data, cb)

    def send_request_inline(self):
        if self._sending_request or not self._alive:
            return

        if not self._found_user:
            self.find_result.setText("Сначала найди пользователя.")
            return

        to_user = self._found_user["login"]
        self._sending_request = True
        self.send_request_btn.setEnabled(False)
        self.find_result.setText("Отправляю запрос...")

        data = {
            "action": "send_friend_request",
            "from_user": self.ctx.login,
            "to_user": to_user
        }

        def cb(resp):
            try:
                if resp.get("status") == "ok":
                    self.find_result.setText("✅ Запрос дружбы отправлен")
                    self.refresh()
                else:
                    self.find_result.setText(resp.get("message", "Ошибка отправки запроса"))
                    self.send_request_btn.setEnabled(True)
            finally:
                self._sending_request = False

        self.start_request(data, cb)

    def show_friend_actions_menu(self, friend_login, anchor_btn):
        menu=QMenu(self);menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.addAction('Мини-профиль',lambda:self.show_mini_profile(friend_login))
        menu.addAction('Написать сообщение',lambda:self.open_friend_chat(friend_login))
        menu.addAction('Позвонить',lambda:self.call_friend(friend_login))
        menu.addSeparator();menu.addAction('Удалить друга',lambda:self.confirm_and_remove_friend(friend_login))
        menu.popup(anchor_btn.mapToGlobal(anchor_btn.rect().bottomLeft()));self._actions_menu=menu

    def open_friend_chat(self, login):
        host=self.parentWidget()
        while host is not None and not hasattr(host,'chats_page'):host=host.parentWidget()
        friend=next((f for f in self._friends_data if f['login']==login),None)
        if host and friend:host.show_chats();host.chats_page.open_chat(friend)

    def show_mini_profile(self, login):
        friend=next((f for f in self._friends_data if f['login']==login),None)
        if not friend:return
        from ui.design.widgets import Button
        dialog=QDialog(self);dialog.setWindowTitle('Профиль');dialog.setMinimumWidth(340);dialog.setAttribute(Qt.WA_DeleteOnClose)
        layout=QVBoxLayout(dialog);layout.setContentsMargins(28,28,28,28);layout.setSpacing(16)
        avatar=AvatarLabel(size=72);avatar.set_avatar(friend.get('avatar',''),login,friend.get('nickname',''));layout.addWidget(avatar,0,Qt.AlignHCenter)
        name=QLabel(friend.get('nickname',login));name.setObjectName('PageTitle');layout.addWidget(name)
        layout.addWidget(QLabel('@'+login+' · '+('В сети' if friend.get('online') else 'Не в сети')))
        for text,icon,action in [('Написать','chat',lambda:self.open_friend_chat(login)),('Позвонить','phone',lambda:self.call_friend(login))]:
            button=Button(text,icon);button.clicked.connect(lambda checked=False,action=action:(dialog.close(),action()));layout.addWidget(button)
        dialog.show();self._mini_profile=dialog

    def confirm_and_remove_friend(self, friend_login: str):
        if not friend_login:
            return
        self._pending_remove_login = friend_login
        self.inline_confirm_text.setText(f"Удалить пользователя {friend_login} из друзей?")
        self.inline_confirm.adjustSize()
        self._reposition_inline_confirm()
        self.inline_confirm.setVisible(True)
        self.inline_confirm.raise_()

    def hide_inline_delete_confirm(self):
        self._pending_remove_login = None
        if getattr(self, "inline_confirm", None):
            self.inline_confirm.setVisible(False)

    def confirm_remove_inline(self):
        friend_login = self._pending_remove_login
        if not friend_login:
            self.hide_inline_delete_confirm()
            return
        self.hide_inline_delete_confirm()
        self.remove_friend(friend_login)

    def remove_friend(self, friend_login: str):
        data = {"action": "remove_friend", "friend_login": friend_login}

        def cb(resp):
            if resp.get("status") == "ok":
                # Мгновенно обновим UI, затем сверим с сервером.
                self._friends_data = [f for f in self._friends_data if f.get("login") != friend_login]
                self._render_if_needed(force=True)
                self._show_toast("Друг удалён")
                self.load_friends()
            else:
                self._show_toast(resp.get("message", "Не удалось удалить друга"), timeout_ms=2200)

        self.start_request(data, cb)

    def _reposition_inline_confirm(self):
        if not getattr(self, "inline_confirm", None):
            return
        self.inline_confirm.adjustSize()
        x = max(12, (self.width() - self.inline_confirm.width()) // 2)
        y = max(12, self.height() - self.inline_confirm.height() - 16)
        self.inline_confirm.move(x, y)

    def _show_toast(self, text: str, timeout_ms: int = 1800):
        if not text:
            return
        if getattr(self, "_toast", None):
            self._toast.show(text, timeout_ms)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_toast", None):
            self._toast.reposition()
        if getattr(self, "inline_confirm", None) and self.inline_confirm.isVisible():
            self._reposition_inline_confirm()

    def call_friend(self, friend_login: str):
        # Показываем call-уведомления как часть главного окна (без отдельных QMessageBox).
        host = self.parentWidget()
        while host is not None and not hasattr(host, "start_outgoing_call"):
            host = host.parentWidget()

        if host is not None and hasattr(host, "start_outgoing_call"):
            host.start_outgoing_call(friend_login)
            return

        # Fallback: если страница используется вне MainWindow
        data = {"action": "call_user", "from_user": self.ctx.login, "to_user": friend_login}

        def cb(resp):
            if resp.get("status") == "ok":
                self._show_toast(f"Вызов отправлен пользователю {friend_login}")
            else:
                self._show_toast(resp.get("message", "Не удалось начать вызов"), timeout_ms=2400)

        self.start_request(data, cb)
