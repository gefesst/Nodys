from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QLineEdit, QPushButton, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, QTimer

from user_context import UserContext
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel
from ui.micro_interactions import install_opacity_feedback


class ChatFriendItem(QFrame):
    def __init__(
        self,
        login,
        nickname,
        avatar_path="",
        on_click=None,
        is_active=False,
        online=False,
        unread_count=0,
        compact=False,
    ):
        super().__init__()

        self.setFixedHeight(54 if compact else 64)
        self.setObjectName("ChatFriendItem")
        self.setProperty("active", is_active)
        self.setProperty("compact", "true" if compact else "false")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Контент карточки. Активная подсветка слева рисуется через border-left у ChatFriendItem,
        # чтобы полоска была частью подложки карточки, а не отдельным прямоугольником.
        content = QFrame()
        content.setObjectName("ChatFriendContent")

        row = QHBoxLayout(content)
        row.setContentsMargins(9 if compact else 12, 7 if compact else 8, 9 if compact else 12, 7 if compact else 8)
        row.setSpacing(7 if compact else 10)

        # Круглый аватар + online dot
        avatar = AvatarLabel(size=36 if compact else 44)
        avatar.set_avatar(path=avatar_path, login=login, nickname=nickname)
        avatar.set_online(online, ring_color="#2f3136")
        row.addWidget(avatar)

        # Текст
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        name = QLabel(nickname)
        name.setObjectName("ChatFriendName")
        text_col.addWidget(name)

        sub = QLabel("в сети" if online else "не в сети")
        sub.setObjectName("ChatFriendSub")
        text_col.addWidget(sub)

        row.addLayout(text_col, 1)
        row.addStretch()

        # badge непрочитанных
        if unread_count > 0:
            badge = QLabel(str(unread_count))
            badge.setObjectName("UnreadBadge")
            badge.setAlignment(Qt.AlignCenter)
            row.addWidget(badge, alignment=Qt.AlignVCenter)

        root.addWidget(content, 1)

        if on_click:
            self.mousePressEvent = lambda event: on_click()
            content.mousePressEvent = lambda event: on_click()


class MessageBubble(QFrame):
    def __init__(self, text, is_outgoing=False, time_text="", status_text=""):
        super().__init__()

        self.setObjectName("ChatMessageRow")
        self.setProperty("outgoing", "true" if is_outgoing else "false")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)

        bubble = QFrame()
        bubble.setObjectName("ChatBubbleCard")
        bubble.setProperty("outgoing", "true" if is_outgoing else "false")

        bubble_lay = QVBoxLayout(bubble)
        bubble_lay.setContentsMargins(12, 8, 12, 7)
        bubble_lay.setSpacing(5)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setObjectName("ChatBubbleText")
        bubble_lay.addWidget(label)

        meta_layout = QHBoxLayout()
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(7)

        time_label = QLabel(time_text or "")
        time_label.setObjectName("ChatBubbleMeta")

        status_label = QLabel(status_text or "")
        status_label.setObjectName("ChatBubbleMeta")
        status_label.setProperty("accent", "true")

        if is_outgoing:
            meta_layout.addStretch(1)
            if time_text:
                meta_layout.addWidget(time_label)
            if status_text:
                meta_layout.addWidget(status_label)
        else:
            if time_text:
                meta_layout.addWidget(time_label)
            meta_layout.addStretch(1)

        bubble_lay.addLayout(meta_layout)
        bubble.setMaximumWidth(660)

        if is_outgoing:
            lay.addStretch(1)
            lay.addWidget(bubble, 0, Qt.AlignRight)
        else:
            lay.addWidget(bubble, 0, Qt.AlignLeft)
            lay.addStretch(1)


class ChatsPage(QWidget, ThreadSafeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = UserContext()

        # Для ThreadSafeMixin
        self._threads = []
        self._alive = True

        # Состояние
        self.active_friend = None
        self._loading_friends = False
        self._loading_messages = False
        self._sending = False
        self._loading_unread = False

        self.unread_counts = {}
        self.unread_total = 0
        self.on_unread_total_changed = None

        # Render/cache signatures for large lists
        self._friends_signature = ""
        self._messages_signature = None
        self._compact_mode = False
        self._friends_loaded_once = False
        self._friends_skeleton_visible = False

        # UI
        self.setObjectName("ChatsPage")
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(15)

        # Левая панель друзей
        friends_card = QFrame()
        friends_card.setObjectName("ChatsFriendsCard")
        friends_card_l = QVBoxLayout(friends_card)
        friends_card_l.setContentsMargins(8,8,8,8)

        friends_head = QHBoxLayout()
        friends_head.setContentsMargins(2, 2, 2, 2)
        friends_head.setSpacing(8)
        self.friends_head_title = QLabel("Диалоги")
        self.friends_head_title.setObjectName("ChatsListTitle")
        friends_head.addWidget(self.friends_head_title)
        friends_head.addStretch(1)

        self.compact_toggle_btn = QPushButton("Компактно")
        self.compact_toggle_btn.setObjectName("ChatsCompactToggle")
        self.compact_toggle_btn.setCheckable(True)
        self.compact_toggle_btn.toggled.connect(self.set_compact_mode)
        friends_head.addWidget(self.compact_toggle_btn)
        install_opacity_feedback(self.compact_toggle_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        friends_card_l.addLayout(friends_head)

        self.friends_container = QWidget()
        self.friends_layout = QVBoxLayout(self.friends_container)
        self.friends_layout.setSpacing(6)
        self.friends_layout.addStretch()

        self.friends_scroll = QScrollArea()
        self.friends_scroll.setWidgetResizable(True)
        self.friends_scroll.setWidget(self.friends_container)
        friends_card_l.addWidget(self.friends_scroll)
        root.addWidget(friends_card, 1)

        # Правая панель чата
        chat_card = QFrame()
        chat_card.setObjectName("ChatsDialogCard")
        chat_card_l = QVBoxLayout(chat_card)
        chat_card_l.setContentsMargins(10,10,10,10)
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(5)

        self.chat_header_card = QFrame()
        self.chat_header_card.setObjectName("ChatHeaderCard")
        header_l = QHBoxLayout(self.chat_header_card)
        header_l.setContentsMargins(12, 8, 12, 8)
        header_l.setSpacing(8)

        header_l.addStretch(1)
        self.chat_header = QLabel("Выберите друга")
        self.chat_header.setObjectName("ChatHeader")
        self.chat_header.setAlignment(Qt.AlignCenter)
        self.chat_header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        header_l.addWidget(self.chat_header, 1)
        header_l.addStretch(1)

        self.chat_layout.addWidget(self.chat_header_card)

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.addStretch()

        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setWidget(self.messages_container)
        self.chat_layout.addWidget(self.messages_scroll)

        input_lay = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setObjectName("ChatInput")
        self.input_edit.setPlaceholderText("Введите сообщение...")
        self.input_edit.returnPressed.connect(self.send_message)
        input_lay.addWidget(self.input_edit)

        self.send_btn = QPushButton("Отправить")
        self.send_btn.setObjectName("ChatSendButton")
        self.send_btn.clicked.connect(self.send_message)
        input_lay.addWidget(self.send_btn)
        install_opacity_feedback(self.send_btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)

        self.chat_layout.addLayout(input_lay)
        chat_card_l.addWidget(self.chat_container)
        root.addWidget(chat_card, 3)

        self._show_friends_skeleton(count=6)
        self._show_messages_placeholder("Выберите диалог, чтобы увидеть сообщения")

        # Таймеры
        self.msg_timer = QTimer(self)
        self.msg_timer.setInterval(2000)
        self.msg_timer.timeout.connect(self.load_messages)

        self.friends_timer = QTimer(self)
        self.friends_timer.setInterval(3000)
        self.friends_timer.timeout.connect(self._friends_tick)

    # ==================================================
    # ================= Lifecycle ======================
    # ==================================================

    def start_auto_update(self, force_refresh: bool = False):
        if not self._alive:
            return

        if not self._is_poll_allowed():
            self.stop_auto_update()
            return

        started_now = False

        if not self.friends_timer.isActive():
            self.friends_timer.start()
            started_now = True

        if self.active_friend and not self.msg_timer.isActive():
            self.msg_timer.start()
            started_now = True

        # Загружаем и unread, и друзей — список чатов не должен зависеть
        # только от успешности unread-запроса.
        if started_now or force_refresh:
            self.load_unread_counts(force=True)
            self.load_friends(force=True)

    def stop_auto_update(self):
        if self.msg_timer.isActive():
            self.msg_timer.stop()
        if self.friends_timer.isActive():
            self.friends_timer.stop()

    def reset_for_user(self):
        """
        Полный сброс состояния при перелогине/смене пользователя.
        """
        self._alive = True
        self.stop_auto_update()

        self.active_friend = None
        self._loading_friends = False
        self._loading_messages = False
        self._sending = False
        self._loading_unread = False

        self.unread_counts = {}
        self.unread_total = 0
        self._friends_signature = ""
        self._messages_signature = None
        self._friends_loaded_once = False

        self.chat_header.setText("Выберите друга")
        self.input_edit.clear()

        self._clear_friends()
        self._clear_messages()
        self.compact_toggle_btn.setChecked(False)
        self._show_friends_skeleton(count=6)
        self._show_messages_placeholder("Выберите диалог, чтобы увидеть сообщения")

    def closeEvent(self, event):
        self._alive = False
        self.stop_auto_update()
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)

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

    # ==================================================
    # ================= Helpers ========================
    # ==================================================

    def _friends_tick(self):
        if not self._is_poll_allowed():
            return
        self.load_unread_counts()

    def _clear_friends(self):
        for i in reversed(range(self.friends_layout.count() - 1)):
            item = self.friends_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_section_header(self, text: str):
        header = QLabel(text)
        header.setObjectName("ChatsSectionHeader")
        self.friends_layout.insertWidget(self.friends_layout.count() - 1, header)

    def set_compact_mode(self, enabled: bool):
        self._compact_mode = bool(enabled)
        self.compact_toggle_btn.setText("Компактно ✓" if self._compact_mode else "Компактно")
        self.friends_layout.setSpacing(4 if self._compact_mode else 6)
        self._friends_signature = ""
        self.load_friends(force=True)

    def _show_friends_skeleton(self, count: int = 6):
        self._friends_skeleton_visible = True
        self._clear_friends()
        for _ in range(max(2, int(count))):
            sk = QFrame()
            sk.setObjectName("ChatsSkeletonCard")
            self.friends_layout.insertWidget(self.friends_layout.count() - 1, sk)

    def _make_friends_empty_state(self, title: str, subtitle: str) -> QFrame:
        card = QFrame()
        card.setObjectName("ChatsEmptyStateCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(4)

        icon = QLabel("💬")
        icon.setObjectName("ChatsEmptyStateIcon")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)

        t = QLabel(title)
        t.setObjectName("ChatsEmptyStateTitle")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)

        s = QLabel(subtitle)
        s.setObjectName("ChatsEmptyStateSub")
        s.setAlignment(Qt.AlignCenter)
        s.setWordWrap(True)
        lay.addWidget(s)
        return card

    def _show_messages_placeholder(self, text: str):
        self._clear_messages()
        hint = QLabel(text)
        hint.setObjectName("ChatsMessagesEmptyHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, hint)

    def _clear_messages(self):
        for i in reversed(range(self.messages_layout.count() - 1)):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    @staticmethod
    def _format_time(dt_str: str) -> str:
        if not dt_str:
            return ""
        try:
            return dt_str[11:16]
        except Exception:
            return ""

    # ==================================================
    # ================= Unread =========================
    # ==================================================

    def load_unread_counts(self, force: bool = False):
        if not self._alive or self._loading_unread or not self.ctx.login:
            return
        if (not force) and (not self._is_poll_allowed()):
            return

        self._loading_unread = True
        data = {"action": "get_unread_counts", "login": self.ctx.login}

        def cb(resp):
            try:
                if resp.get("status") == "ok":
                    self.unread_counts = resp.get("counts", {}) or {}
                    self.unread_total = int(resp.get("total", 0) or 0)

                    if callable(self.on_unread_total_changed):
                        self.on_unread_total_changed(self.unread_total)

                # Даже если unread не удалось получить — список друзей всё равно обновляем.
                self.load_friends(force=force)
            finally:
                self._loading_unread = False

        self.start_request(data, cb)

    def mark_chat_read(self, friend_login: str):
        if not self.ctx.login:
            return

        data = {
            "action": "mark_chat_read",
            "login": self.ctx.login,
            "friend_login": friend_login
        }

        def cb(_resp):
            self.load_unread_counts(force=True)

        self.start_request(data, cb)

    # ==================================================
    # ================= Friends list ===================
    # ==================================================

    def load_friends(self, force: bool = False):
        if not self._alive or self._loading_friends or not self.ctx.login:
            return
        if not self._friends_loaded_once:
            self._show_friends_skeleton(count=6)
        if (not force) and (not self._is_poll_allowed()):
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
        self._friends_loaded_once = True
        if resp.get("status") != "ok":
            friends = []
        else:
            friends = list(resp.get("friends", []) or [])
        current_login = self.active_friend["login"] if self.active_friend else None

        # Если активный собеседник ещё существует, обновим его данные
        if current_login:
            found = next((f for f in friends if f.get("login") == current_login), None)
            if found:
                self.active_friend = found
                self.chat_header.setText(found.get("nickname", current_login))
            else:
                # Собеседник исчез из списка (например, удалили дружбу)
                self.active_friend = None
                current_login = None
                self.chat_header.setText("Выберите друга")
                self._messages_signature = None
                self._clear_messages()
                self._show_messages_placeholder("Выберите диалог, чтобы увидеть сообщения")
                if self.msg_timer.isActive():
                    self.msg_timer.stop()

        def sort_key(f):
            return (0 if f.get("online", False) else 1, f.get("nickname", "").lower())

        friends_sorted = sorted(friends, key=sort_key)

        # Сигнатура левого списка (включает unread + online + активный чат)
        sig_parts = [f"active:{current_login or ''}", f"compact:{int(self._compact_mode)}"]
        for fr in friends_sorted:
            fl = fr.get("login", "")
            sig_parts.append(
                "|".join([
                    fl,
                    fr.get("nickname", ""),
                    fr.get("avatar", "") or "",
                    "1" if bool(fr.get("online", False)) else "0",
                    str(int(self.unread_counts.get(fl, 0))),
                ])
            )
        signature = "\n".join(sig_parts)
        if signature == self._friends_signature:
            return
        self._friends_signature = signature

        self.friends_scroll.setUpdatesEnabled(False)
        self._clear_friends()
        self._friends_skeleton_visible = False

        online_friends = [f for f in friends_sorted if f.get("online", False)]
        offline_friends = [f for f in friends_sorted if not f.get("online", False)]

        if online_friends:
            self._add_section_header(f"В сети — {len(online_friends)}")
            for friend in online_friends:
                count = int(self.unread_counts.get(friend.get("login", ""), 0))
                item = ChatFriendItem(
                    login=friend.get("login", ""),
                    nickname=friend.get("nickname", friend.get("login", "")),
                    avatar_path=friend.get("avatar", ""),
                    online=True,
                    is_active=(friend.get("login") == current_login),
                    unread_count=count,
                    on_click=lambda f=friend: self.open_chat(f),
                    compact=self._compact_mode,
                )
                self.friends_layout.insertWidget(self.friends_layout.count() - 1, item)

        if offline_friends:
            self._add_section_header(f"Не в сети — {len(offline_friends)}")
            for friend in offline_friends:
                count = int(self.unread_counts.get(friend.get("login", ""), 0))
                item = ChatFriendItem(
                    login=friend.get("login", ""),
                    nickname=friend.get("nickname", friend.get("login", "")),
                    avatar_path=friend.get("avatar", ""),
                    online=False,
                    is_active=(friend.get("login") == current_login),
                    unread_count=count,
                    on_click=lambda f=friend: self.open_chat(f),
                    compact=self._compact_mode,
                )
                self.friends_layout.insertWidget(self.friends_layout.count() - 1, item)

        if not friends_sorted:
            empty = self._make_friends_empty_state(
                title="Нет диалогов",
                subtitle="Добавьте друзей на вкладке «Друзья», чтобы начать чат.",
            )
            self.friends_layout.insertWidget(self.friends_layout.count() - 1, empty)

        self.friends_scroll.setUpdatesEnabled(True)

    # ==================================================
    # ================= Chat logic =====================
    # ==================================================

    def open_chat(self, friend):
        if not friend or not friend.get("login"):
            return

        self.active_friend = friend
        self.chat_header.setText(friend.get("nickname", friend["login"]))
        self._messages_signature = None

        self.mark_chat_read(friend["login"])
        self.load_friends(force=True)   # чтобы сразу убрать badge у активного
        self.load_messages(force=True)

        if self._is_poll_allowed() and (not self.msg_timer.isActive()):
            self.msg_timer.start()

    def load_messages(self, force: bool = False):
        if (
            not self._alive
            or not self.ctx.login
            or not self.active_friend
            or self._loading_messages
        ):
            return
        if (not force) and (not self._is_poll_allowed()):
            return

        self._loading_messages = True
        data = {
            "action": "get_messages",
            "from_user": self.ctx.login,
            "to_user": self.active_friend["login"]
        }

        def cb(resp):
            try:
                self.handle_messages(resp)
            finally:
                self._loading_messages = False

        self.start_request(data, cb)

    def handle_messages(self, resp):
        if resp.get("status") != "ok":
            return

        messages = list(resp.get("messages", []) or [])

        sig_parts = []
        for m in messages:
            sig_parts.append(
                "|".join([
                    str(m.get("id", "")),
                    str(m.get("from_user", "")),
                    str(m.get("to_user", "")),
                    str(m.get("created_at", "")),
                    str(m.get("text", m.get("message", ""))),
                    "1" if bool(m.get("is_read", False)) else "0",
                ])
            )
        signature = "\n".join(sig_parts)
        if signature == self._messages_signature:
            return
        self._messages_signature = signature

        sb = self.messages_scroll.verticalScrollBar()
        prev_value = sb.value()
        near_bottom = (sb.maximum() - sb.value()) <= 80

        self.messages_scroll.setUpdatesEnabled(False)
        self._clear_messages()

        if not messages:
            self._show_messages_placeholder("Сообщений пока нет. Напишите первым 👋")
            self.messages_scroll.setUpdatesEnabled(True)
            return

        for msg in messages:
            text = msg.get("text", msg.get("message", ""))
            is_outgoing = (msg.get("from_user") == self.ctx.login)
            time_text = self._format_time(msg.get("created_at", ""))

            status_text = ""
            if is_outgoing:
                status_text = "✓✓" if bool(msg.get("is_read", False)) else "✓"

            bubble = MessageBubble(
                text=text,
                is_outgoing=is_outgoing,
                time_text=time_text,
                status_text=status_text
            )
            self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)

        if near_bottom:
            sb.setValue(sb.maximum())
        else:
            sb.setValue(min(prev_value, sb.maximum()))
        self.messages_scroll.setUpdatesEnabled(True)

    def send_message(self):
        if (
            not self._alive
            or not self.ctx.login
            or not self.active_friend
            or self._sending
        ):
            return

        text = self.input_edit.text().strip()
        if not text:
            return

        self._sending = True
        data = {
            "action": "send_message",
            "from_user": self.ctx.login,
            "to_user": self.active_friend["login"],
            "text": text
        }

        def cb(_resp):
            try:
                self._messages_signature = None
                self.load_messages(force=True)
                self.load_unread_counts(force=True)
            finally:
                self._sending = False

        self.start_request(data, cb)
        self.input_edit.clear()
