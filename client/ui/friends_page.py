from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QLineEdit,
    QMenu, QApplication
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
        self.setFixedHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        avatar = AvatarLabel(size=44)
        avatar.set_avatar(path=avatar_path, login=login, nickname=nickname)
        avatar.set_online(online if request_from is None else None, ring_color="#2b2d31")
        layout.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        name = QLabel(nickname)
        name.setObjectName("FriendItemName")
        text_col.addWidget(name)

        sub = QLabel(login if request_from is None else f"Запрос от: {login}")
        sub.setObjectName("FriendItemSub")
        text_col.addWidget(sub)

        layout.addLayout(text_col)
        layout.addStretch()

        if request_from is None:
            # Монохромный символ лучше читается на зелёной кнопке.
            self.call_btn = QPushButton("☎️")
            self.call_btn.setObjectName("FriendCallButton")
            btn_size = 34
            self.call_btn.setFixedSize(btn_size, btn_size)
            self.call_btn.setToolTip("Позвонить")
            if on_call:
                self.call_btn.clicked.connect(lambda: on_call(login))
            layout.addWidget(self.call_btn)
            install_opacity_feedback(self.call_btn, hover_opacity=0.99, pressed_opacity=0.93, duration_ms=80)

            self.more_btn = QPushButton("...")
            self.more_btn.setObjectName("FriendMoreButton")
            self.more_btn.setFixedSize(btn_size, btn_size)
            self.more_btn.setCursor(self.call_btn.cursor())
            f = self.more_btn.font()
            f.setBold(True)
            f.setWeight(QFont.Weight.Black)
            self.more_btn.setFont(f)
            if on_manage:
                self.more_btn.clicked.connect(lambda: on_manage(login, self.more_btn))
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

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # ---------- Top bar card ----------
        topbar = QFrame()
        topbar.setObjectName("FriendsTopBar")
        head = QHBoxLayout(topbar)
        head.setContentsMargins(12, 10, 12, 10)
        head.setSpacing(10)

        title = QLabel("Друзья")
        title.setObjectName("FriendsTitle")
        head.addWidget(title)
        head.addStretch()


        self.add_btn = QPushButton("Добавить друга")
        self.add_btn.setObjectName("AddFriendButton")
        self.add_btn.clicked.connect(self.toggle_add_friend_panel)
        head.addWidget(self.add_btn)
        install_opacity_feedback(self.add_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        root.addWidget(topbar)

        # ---------- Inline add panel ----------
        self.add_panel = QFrame()
        self.add_panel.setObjectName("AddFriendPanel")
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
        body_card.setObjectName("FriendsContentCard")
        body_lay = QVBoxLayout(body_card)
        body_lay.setContentsMargins(10, 10, 10, 10)
        body_lay.setSpacing(8)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("FriendsScrollArea")

        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setSpacing(8)
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
    def toggle_add_friend_panel(self):
        visible = not self.add_panel.isVisible()
        self.add_panel.setVisible(visible)
        self.add_btn.setText("Скрыть добавление" if visible else "Добавить друга")
        if not visible:
            self._reset_add_panel_state()

    def hide_add_friend_panel(self):
        self.add_panel.setVisible(False)
        self.add_btn.setText("Добавить друга")
        self._reset_add_panel_state()

    def _reset_add_panel_state(self):
        self.login_input.clear()
        self.find_result.setText("")
        self.send_request_btn.setEnabled(False)
        self._found_user = None

    def clear_list(self):
        for i in reversed(range(self.list_layout.count() - 1)):
            item = self.list_layout.itemAt(i)
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

        icon = QLabel("👥")
        icon.setObjectName("FriendsEmptyStateIcon")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)

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
        # Чтобы не мигать "пустым" списком на старте, ждём обе загрузки.
        if not self._has_loaded_friends_once or not self._has_loaded_requests_once:
            if not self._skeleton_visible:
                self._show_skeleton(count=6)
            return

        self._skeleton_visible = False
        key = self._state_key()
        if (not force) and key == self._render_key:
            return
        self._render_key = key

        self.scroll.setUpdatesEnabled(False)
        try:
            self.clear_list()

            # Requests
            if self._requests_data:
                self._add_section_header(f"Заявки в друзья — {len(self._requests_data)}")
                for req_login in self._requests_data:
                    item = FriendItem(
                        login=req_login,
                        nickname=req_login,
                        request_from=req_login,
                        on_accept=self.accept_request,
                        on_decline=self.decline_request,
                    )
                    self.list_layout.insertWidget(self.list_layout.count() - 1, item)

            # Friends
            friends = sorted(
                self._friends_data,
                key=lambda f: (0 if f.get("online", False) else 1, f.get("nickname", "").lower())
            )
            online_friends = [f for f in friends if f.get("online", False)]
            offline_friends = [f for f in friends if not f.get("online", False)]

            if online_friends:
                self._add_section_header(f"В сети — {len(online_friends)}")
                for friend in online_friends:
                    item = FriendItem(
                        login=friend.get("login", ""),
                        nickname=friend.get("nickname", friend.get("login", "")),
                        avatar_path=friend.get("avatar", ""),
                        online=True,
                        on_call=self.call_friend,
                        on_manage=self.show_friend_actions_menu,
                    )
                    self.list_layout.insertWidget(self.list_layout.count() - 1, item)

            if offline_friends:
                self._add_section_header(f"Не в сети — {len(offline_friends)}")
                for friend in offline_friends:
                    item = FriendItem(
                        login=friend.get("login", ""),
                        nickname=friend.get("nickname", friend.get("login", "")),
                        avatar_path=friend.get("avatar", ""),
                        online=False,
                        on_call=self.call_friend,
                        on_manage=self.show_friend_actions_menu,
                    )
                    self.list_layout.insertWidget(self.list_layout.count() - 1, item)

            if not friends and not self._requests_data:
                empty = self._make_empty_state(
                    title="Пока нет друзей",
                    subtitle="Добавьте друзей по логину — и можно будет начать переписку и звонки.",
                )
                self.list_layout.insertWidget(self.list_layout.count() - 1, empty)
        finally:
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

    def show_friend_actions_menu(self, friend_login: str, anchor_btn: QPushButton):
        if not friend_login or not anchor_btn:
            return

        menu = QMenu(self)
        menu.setObjectName("FriendActionsMenu")
        act_remove = menu.addAction("Удалить друга")

        pos = anchor_btn.mapToGlobal(anchor_btn.rect().bottomLeft())
        chosen = menu.exec(pos)
        if chosen == act_remove:
            self.confirm_and_remove_friend(friend_login)

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
