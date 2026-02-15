from PySide6.QtCore import QTimer, Qt, QRect, QEvent
import os
import socket
from types import SimpleNamespace

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QSizePolicy, QStackedWidget, QApplication, QLabel, QFrame
)
from PySide6.QtGui import QIcon

from ui.channels_page import ChannelsPage
from ui.profile_page import ProfilePage
from ui.friends_page import FriendsPage
from ui.chats_page import ChatsPage
from ui.avatar_widget import AvatarLabel
from ui.call_window import ActiveCallWindow

from user_context import UserContext
from network import NetworkThread, send_json_packet, recv_json_packet
from voice_client import VoiceClient
from config import clear_config
from settings import get_voice_endpoint, get_api_endpoint
from ui.micro_interactions import install_opacity_feedback


class MainWindow(QWidget):
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.ctx = self._snapshot_context(UserContext())

        self.is_logging_out = False
        self._is_closing = False

        self.setWindowTitle("Nodys")
        # Чуть шире и немного ниже по высоте для более удобной стартовой компоновки.
        self.setMinimumSize(1080, 580)
        self.setObjectName("MainWindowRoot")

        # Иконка приложения (если есть)
        current_dir = os.path.dirname(os.path.abspath(__file__))   # client/ui
        client_dir = os.path.dirname(current_dir)                  # client
        icon_path = os.path.join(client_dir, "icons", "app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # ---------------- Stack ----------------
        self.stack = QStackedWidget(self)

        self.friends_page = FriendsPage(self)      # index 0
        self.chats_page = ChatsPage(self)          # index 1
        self.channels_page = ChannelsPage(self)    # index 2
        self.profile_page = ProfilePage(self.ctx.login, self.ctx.nickname, self)  # index 3
        self.profile_page.ctx = self.ctx

        # Подписка на обновление общего unread из ChatsPage
        self.chats_page.on_unread_total_changed = self.update_chats_badge
        # Подписка на количество входящих приглашений в каналы
        self.channels_page.on_invites_count_changed = self.update_channels_badge

        self.stack.addWidget(self.friends_page)
        self.stack.addWidget(self.chats_page)
        self.stack.addWidget(self.channels_page)
        self.stack.addWidget(self.profile_page)

        # ---------------- Sidebar ----------------
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        menu_layout = QVBoxLayout(sidebar)
        menu_layout.setContentsMargins(10, 10, 10, 10)
        menu_layout.setSpacing(10)

        # Мини-карточка пользователя
        self.user_card = QFrame()
        self.user_card.setObjectName("UserMiniCard")
        uc_l = QHBoxLayout(self.user_card)
        uc_l.setContentsMargins(8, 8, 8, 8)
        uc_l.setSpacing(8)
        self.user_avatar = AvatarLabel(size=34)
        self.user_avatar.set_avatar(path=getattr(self.ctx, "avatar", ""), login=self.ctx.login, nickname=self.ctx.nickname)
        self.user_avatar.set_online(None if not self.ctx.login else False, ring_color="#2f3136")
        uc_l.addWidget(self.user_avatar)
        txt_col = QVBoxLayout()
        txt_col.setContentsMargins(0,0,0,0)
        txt_col.setSpacing(0)
        self.user_nick_lbl = QLabel(self.ctx.nickname or "Гость")
        self.user_nick_lbl.setObjectName("UserMiniNick")
        self.user_login_lbl = QLabel(self.ctx.login or "")
        self.user_login_lbl.setObjectName("UserMiniLogin")
        txt_col.addWidget(self.user_nick_lbl)
        txt_col.addWidget(self.user_login_lbl)
        uc_l.addLayout(txt_col)
        menu_layout.addWidget(self.user_card)
        install_opacity_feedback(self.user_card, hover_opacity=0.995, pressed_opacity=0.975, duration_ms=90)

        def make_button(text, callback):
            btn = QPushButton(text)
            btn.setFixedHeight(50)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setObjectName("NavButton")
            btn.clicked.connect(callback)
            install_opacity_feedback(btn, hover_opacity=0.99, pressed_opacity=0.94, duration_ms=85)
            return btn

        self.btn_friends = make_button("Друзья", self.show_friends)
        self.btn_chats = make_button("Чаты", self.show_chats)
        self.btn_channels = make_button("Каналы", self.show_channels)
        self.btn_profile = make_button("Мой профиль", self.show_profile)

        menu_layout.addWidget(self.btn_friends)
        menu_layout.addWidget(self.btn_chats)
        menu_layout.addWidget(self.btn_channels)
        menu_layout.addWidget(self.btn_profile)
        menu_layout.addStretch()

        # ---------------- Root layout ----------------
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(sidebar, 1)
        root.addWidget(self.stack, 4)

        # Политика polling (инициализируем до первого переключения вкладок).
        self._poll_state = {
            "friends": False,
            "chats": False,
            "channels": False,
            "window_active": None,
        }

        # Стартовая вкладка
        self.show_friends()

        # И сразу подгрузим unread, чтобы кнопка "Чаты" была актуальной
        self.chats_page.load_unread_counts(force=True)

        # Бейдж приглашений во вкладке "Каналы" (обновляется глобально,
        # чтобы счётчик был актуален даже когда вкладка каналов не открыта).
        self._channel_invites_badge_thread = None
        self._channel_invites_badge_count = 0
        self.channel_invites_badge_timer = QTimer(self)
        self.channel_invites_badge_timer.timeout.connect(self.poll_channel_invites_badge)
        self.channel_invites_badge_timer.start(9000)
        self.poll_channel_invites_badge(force=True)

        # Call signaling poll
        self.current_call_user = None
        self.voice_client = None
        self.call_poll_thread = None
        self.call_window = None
        self._outgoing_call_thread = None
        self.call_events_timer = QTimer(self)
        self.call_events_timer.timeout.connect(self.poll_call_events)
        self.call_events_timer.start(1000)

        # Heartbeat для корректного online/presence на сервере
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._heartbeat)
        self.heartbeat_timer.start(10000)

        # Self-status в мини-карточке слева (зелёная/серая точка на аватаре)
        self._self_status_thread = None
        self._self_status_failures = 0
        self.self_status_timer = QTimer(self)
        self.self_status_timer.timeout.connect(self.refresh_self_status)
        self.self_status_timer.start(5000)
        self.refresh_self_status(force=True)

        # Встроенные (inline) уведомления/карточки звонка внутри главного окна.
        # Это заменяет отдельные QMessageBox / отдельный dialog для входящего вызова.
        self._setup_inline_call_ui()

        # При смене активной вкладки центрируем inline-оверлеи относительно
        # текущего открытого окна (текущей страницы в stack), а не всего приложения.
        try:
            self.stack.currentChanged.connect(self._on_stack_current_changed)
        except Exception:
            pass

        try:
            app = QApplication.instance()
            if app is not None:
                app.applicationStateChanged.connect(self._on_application_state_changed)
        except Exception:
            pass

        self._apply_polling_policy(force=True)

    def _snapshot_context(self, src_ctx):
        """Локальная копия контекста для конкретного окна.

        Нужна, чтобы несколько окон в одном процессе не перетирали друг другу
        login/token через глобальный singleton UserContext.
        """
        return SimpleNamespace(
            login=getattr(src_ctx, "login", "") or "",
            nickname=getattr(src_ctx, "nickname", "") or "",
            avatar=getattr(src_ctx, "avatar", "") or "",
            session_token=getattr(src_ctx, "session_token", "") or "",
            token_expires_at=getattr(src_ctx, "token_expires_at", "") or "",
        )

    def _on_stack_current_changed(self, _idx: int):
        try:
            self._reposition_inline_call_ui()
        except Exception:
            pass
        self._apply_polling_policy()

    def _on_application_state_changed(self, _state):
        self._apply_polling_policy()

    def _window_is_active_for_polling(self) -> bool:
        if not self.isVisible():
            return False
        try:
            if bool(self.windowState() & Qt.WindowMinimized):
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

    @staticmethod
    def _set_timer_interval(timer: QTimer, interval_ms: int):
        try:
            interval_ms = int(interval_ms)
        except Exception:
            return
        if interval_ms <= 0:
            return
        if timer.interval() != interval_ms:
            timer.setInterval(interval_ms)

    def _apply_polling_policy(self, force: bool = False):
        """Centralized polling visibility policy.

        Rules:
        - Page-level polling runs only on active tab and only when app/window visible.
        - Service polling (call events / heartbeat / self-status) is throttled in background.
        """
        window_active = self._window_is_active_for_polling()
        current_idx = self.stack.currentIndex() if window_active else -1

        desired = {
            "friends": (current_idx == 0),
            "chats": (current_idx == 1),
            "channels": (current_idx == 2),
            "window_active": window_active,
        }

        # Service timers: always enabled in session, but slower in background.
        call_interval = 1000 if window_active else 2600
        hb_interval = 10000 if window_active else 18000
        status_interval = 5000 if window_active else 12000
        invites_badge_interval = 9000 if window_active else 18000

        try:
            self._set_timer_interval(self.call_events_timer, call_interval)
            if self.ctx.login:
                if not self.call_events_timer.isActive():
                    self.call_events_timer.start(call_interval)
            elif self.call_events_timer.isActive():
                self.call_events_timer.stop()
        except Exception:
            pass

        try:
            self._set_timer_interval(self.heartbeat_timer, hb_interval)
            if self.ctx.login:
                if not self.heartbeat_timer.isActive():
                    self.heartbeat_timer.start(hb_interval)
            elif self.heartbeat_timer.isActive():
                self.heartbeat_timer.stop()
        except Exception:
            pass

        try:
            self._set_timer_interval(self.self_status_timer, status_interval)
            if self.ctx.login:
                if not self.self_status_timer.isActive():
                    self.self_status_timer.start(status_interval)
            elif self.self_status_timer.isActive():
                self.self_status_timer.stop()
        except Exception:
            pass

        # Lightweight polling только для счётчика приглашений на кнопке "Каналы".
        try:
            self._set_timer_interval(self.channel_invites_badge_timer, invites_badge_interval)
            if self.ctx.login:
                if not self.channel_invites_badge_timer.isActive():
                    self.channel_invites_badge_timer.start(invites_badge_interval)
            elif self.channel_invites_badge_timer.isActive():
                self.channel_invites_badge_timer.stop()
        except Exception:
            pass

        # Friends polling
        prev_friends = bool(self._poll_state.get("friends", False))
        now_friends = bool(desired["friends"])
        if force or (prev_friends != now_friends):
            try:
                if hasattr(self.friends_page, "set_polling_enabled"):
                    self.friends_page.set_polling_enabled(now_friends)
                else:
                    if now_friends:
                        self.friends_page.refresh()
                        if hasattr(self.friends_page, "timer") and not self.friends_page.timer.isActive():
                            self.friends_page.timer.start(2500)
                    else:
                        if hasattr(self.friends_page, "timer") and self.friends_page.timer.isActive():
                            self.friends_page.timer.stop()
            except Exception:
                pass

        # Chats polling
        prev_chats = bool(self._poll_state.get("chats", False))
        now_chats = bool(desired["chats"])
        if force or (prev_chats != now_chats):
            try:
                if now_chats:
                    self.chats_page.start_auto_update(force_refresh=True)
                else:
                    self.chats_page.stop_auto_update()
            except Exception:
                pass

        # Channels polling
        prev_channels = bool(self._poll_state.get("channels", False))
        now_channels = bool(desired["channels"])
        if force or (prev_channels != now_channels):
            try:
                if now_channels:
                    self.channels_page.start_auto_update()
                else:
                    self.channels_page.stop_auto_update()
            except Exception:
                pass

        was_active = self._poll_state.get("window_active", None)
        if window_active and (force or (was_active is False) or (was_active is None)):
            try:
                self.refresh_self_status(force=True)
            except Exception:
                pass

        self._poll_state = desired

    # ==================================================
    # ============ Inline call UI (in-app) ============
    # ==================================================

    def _setup_inline_call_ui(self):
        self._incoming_from_user = None
        self._incoming_action_thread = None

        self._call_notice_timer = QTimer(self)
        self._call_notice_timer.setSingleShot(True)
        self._call_notice_timer.timeout.connect(self._hide_call_notice)

        self.call_notice = QFrame(self)
        self.call_notice.setObjectName("CallInlineNoticeCard")
        self.call_notice.setVisible(False)
        notice_l = QHBoxLayout(self.call_notice)
        notice_l.setContentsMargins(12, 10, 12, 10)
        notice_l.setSpacing(8)

        self.call_notice_lbl = QLabel("", self.call_notice)
        self.call_notice_lbl.setObjectName("CallInlineNoticeText")
        self.call_notice_lbl.setWordWrap(True)
        notice_l.addWidget(self.call_notice_lbl)

        self.incoming_card = QFrame(self)
        self.incoming_card.setObjectName("IncomingCallInlineCard")
        self.incoming_card.setVisible(False)
        incoming_l = QVBoxLayout(self.incoming_card)
        incoming_l.setContentsMargins(14, 12, 14, 12)
        incoming_l.setSpacing(10)

        incoming_title = QLabel("Входящий вызов", self.incoming_card)
        incoming_title.setObjectName("IncomingCallInlineTitle")
        incoming_l.addWidget(incoming_title)

        self.incoming_from_lbl = QLabel("", self.incoming_card)
        self.incoming_from_lbl.setObjectName("IncomingCallInlineFrom")
        self.incoming_from_lbl.setWordWrap(True)
        incoming_l.addWidget(self.incoming_from_lbl)

        row = QHBoxLayout()
        row.addStretch()

        self.incoming_decline_btn = QPushButton("Отклонить", self.incoming_card)
        self.incoming_decline_btn.setObjectName("IncomingCallInlineDeclineBtn")
        self.incoming_decline_btn.clicked.connect(self._decline_incoming_inline)
        row.addWidget(self.incoming_decline_btn)

        self.incoming_accept_btn = QPushButton("Принять", self.incoming_card)
        self.incoming_accept_btn.setObjectName("IncomingCallInlineAcceptBtn")
        self.incoming_accept_btn.clicked.connect(self._accept_incoming_inline)
        row.addWidget(self.incoming_accept_btn)

        incoming_l.addLayout(row)

    def _reposition_inline_call_ui(self):
        """Position inline call overlays at bottom-center of current page.

        Центрируем не по всему приложению, а по текущему открытому окну
        (текущая страница в self.stack).
        """
        side_margin = 12
        bottom_margin = 16
        gap = 10

        # Целевая область: текущий виджет в stack (или сам stack как fallback)
        target_rect = None
        try:
            current = self.stack.currentWidget() if hasattr(self, "stack") else None
            if current is not None:
                tl = current.mapTo(self, current.rect().topLeft())
                target_rect = QRect(tl, current.size())
        except Exception:
            target_rect = None

        if target_rect is None:
            try:
                tl = self.stack.mapTo(self, self.stack.rect().topLeft())
                target_rect = QRect(tl, self.stack.size())
            except Exception:
                target_rect = self.rect()

        ox, oy, ow, oh = target_rect.x(), target_rect.y(), max(1, target_rect.width()), max(1, target_rect.height())

        has_incoming = bool(
            getattr(self, "incoming_card", None)
            and (self.incoming_card.isVisible() or bool(getattr(self, "_incoming_from_user", None)))
        )
        has_notice = bool(
            getattr(self, "call_notice", None)
            and (
                self.call_notice.isVisible()
                or bool(getattr(self, "call_notice_lbl", None) and self.call_notice_lbl.text().strip())
            )
        )

        in_w = in_h = n_w = n_h = 0

        if getattr(self, "incoming_card", None):
            self.incoming_card.adjustSize()
            max_w = max(300, min(430, ow - 40))
            self.incoming_card.setFixedWidth(max_w)
            self.incoming_card.adjustSize()
            in_w = self.incoming_card.width()
            in_h = self.incoming_card.height()

        if getattr(self, "call_notice", None):
            self.call_notice.adjustSize()
            # Compact toast width, but constrained by current page width
            max_w = max(280, min(420, ow - 44))
            self.call_notice.setFixedWidth(max_w)
            self.call_notice.adjustSize()
            n_w = self.call_notice.width()
            n_h = self.call_notice.height()

        def _center_x(item_w: int) -> int:
            left = ox + side_margin
            right = ox + ow - side_margin
            x = ox + (ow - item_w) // 2
            return max(left, min(x, right - item_w))

        page_bottom = oy + oh

        # Внизу: notice у самого низа, incoming — над ним (если оба видимы).
        if has_notice and has_incoming:
            total_h = in_h + gap + n_h
            base_y = max(oy + side_margin, page_bottom - bottom_margin - total_h)

            self.incoming_card.move(_center_x(in_w), base_y)
            self.call_notice.move(_center_x(n_w), base_y + in_h + gap)
        elif has_incoming:
            in_y = max(oy + side_margin, page_bottom - bottom_margin - in_h)
            self.incoming_card.move(_center_x(in_w), in_y)
        elif has_notice:
            n_y = max(oy + side_margin, page_bottom - bottom_margin - n_h)
            self.call_notice.move(_center_x(n_w), n_y)

    def _show_call_notice(self, text: str, timeout_ms: int = 2200):
        if not text:
            return
        self.call_notice_lbl.setText(text)
        self._reposition_inline_call_ui()
        self.call_notice.show()
        self.call_notice.raise_()

        try:
            self._call_notice_timer.stop()
            self._call_notice_timer.start(max(600, int(timeout_ms)))
        except Exception:
            pass

    def _hide_call_notice(self):
        if getattr(self, "call_notice", None):
            self.call_notice.hide()

    def _show_incoming_inline(self, from_user: str):
        if not from_user:
            return
        self._incoming_from_user = from_user
        self.incoming_from_lbl.setText(f"Вам звонит: {from_user}\nПринять вызов?")
        self._set_incoming_buttons_enabled(True)
        self._reposition_inline_call_ui()
        self.incoming_card.show()
        self.incoming_card.raise_()

    def _hide_incoming_inline(self):
        self._incoming_from_user = None
        if getattr(self, "incoming_card", None):
            self.incoming_card.hide()

    def _set_incoming_buttons_enabled(self, enabled: bool):
        try:
            self.incoming_accept_btn.setEnabled(enabled)
            self.incoming_decline_btn.setEnabled(enabled)
        except Exception:
            pass

    def _respond_incoming_inline(self, accept: bool):
        from_user = self._incoming_from_user
        if not from_user or not getattr(self.ctx, "login", ""):
            self._hide_incoming_inline()
            return
        if self._incoming_action_thread and self._incoming_action_thread.isRunning():
            return

        self._set_incoming_buttons_enabled(False)
        action = "accept_call" if accept else "decline_call"
        self._incoming_action_thread = NetworkThread(None, None, {
            "action": action,
            "login": self.ctx.login,
            "from_user": from_user,
            "token": self.ctx.session_token,
        })

        def _done(resp):
            ok = isinstance(resp, dict) and resp.get("status") == "ok"
            if ok:
                if accept:
                    self._show_call_notice(f"Подключаем звонок с {from_user}...", timeout_ms=1800)
                else:
                    self._show_call_notice(f"Вызов от {from_user} отклонён", timeout_ms=1800)
                self._hide_incoming_inline()
            else:
                msg = "Не удалось обработать вызов"
                if isinstance(resp, dict):
                    msg = resp.get("message", msg)
                self._show_call_notice(msg, timeout_ms=2500)
                # Если принять уже нельзя, скрываем карточку.
                if accept:
                    self._hide_incoming_inline()
                else:
                    self._set_incoming_buttons_enabled(True)

            self._incoming_action_thread = None

        self._incoming_action_thread.finished.connect(_done)
        self._incoming_action_thread.start()

    def _accept_incoming_inline(self):
        self._respond_incoming_inline(True)

    def _decline_incoming_inline(self):
        self._respond_incoming_inline(False)

    def start_outgoing_call(self, friend_login: str):
        """Отправка вызова с inline-уведомлением внутри main-окна."""
        if not friend_login or not getattr(self.ctx, "login", ""):
            return
        if self._outgoing_call_thread and self._outgoing_call_thread.isRunning():
            self._show_call_notice("Подождите, предыдущий вызов ещё отправляется", timeout_ms=1800)
            return

        data = {
            "action": "call_user",
            "from_user": self.ctx.login,
            "to_user": friend_login,
            "token": self.ctx.session_token,
        }

        self._outgoing_call_thread = NetworkThread(None, None, data)

        def _done(resp):
            try:
                if isinstance(resp, dict) and resp.get("status") == "ok":
                    self._show_call_notice(f"Вызов отправлен пользователю {friend_login}")
                else:
                    msg = "Не удалось начать вызов"
                    if isinstance(resp, dict):
                        msg = resp.get("message", msg)
                    self._show_call_notice(msg, timeout_ms=2600)
            finally:
                self._outgoing_call_thread = None

        self._outgoing_call_thread.finished.connect(_done)
        self._outgoing_call_thread.start()

    # ==================================================
    # ================== Бейдж "Чаты" ==================
    # ==================================================

    def update_chats_badge(self, total: int):
        if total > 0:
            self.btn_chats.setText(f"Чаты ({total})")
        else:
            self.btn_chats.setText("Чаты")

    def update_channels_badge(self, total: int):
        try:
            total = int(total)
        except Exception:
            total = 0

        self._channel_invites_badge_count = max(0, total)
        if self._channel_invites_badge_count > 0:
            self.btn_channels.setText(f"Каналы ({self._channel_invites_badge_count})")
        else:
            self.btn_channels.setText("Каналы")

    def poll_channel_invites_badge(self, force: bool = False):
        if not getattr(self.ctx, "login", "") or not getattr(self.ctx, "session_token", ""):
            self.update_channels_badge(0)
            return

        if self._channel_invites_badge_thread and self._channel_invites_badge_thread.isRunning():
            return

        # Если сейчас вкладка каналов активна, счётчик и так обновится в ChannelsPage.
        if (not force) and self.stack.currentWidget() is self.channels_page:
            return

        self._channel_invites_badge_thread = NetworkThread(None, None, {
            "action": "get_my_channel_invites",
            "login": self.ctx.login,
            "token": self.ctx.session_token,
        })

        def _done(resp):
            try:
                if isinstance(resp, dict) and resp.get("status") == "ok":
                    invites = resp.get("invites") or []
                    self.update_channels_badge(len(invites))
            finally:
                self._channel_invites_badge_thread = None

        self._channel_invites_badge_thread.finished.connect(_done)
        self._channel_invites_badge_thread.start()

    def _heartbeat(self):
        """Keep session alive on server."""
        if not getattr(self.ctx, "session_token", ""):
            return
        try:
            t = NetworkThread(None, None, {
                "action": "heartbeat",
                "login": self.ctx.login,
                "token": self.ctx.session_token,
            })
            t.start()
        except Exception:
            pass

    def refresh_self_status(self, force: bool = False):
        """Обновить онлайн-статус текущего пользователя для мини-карточки слева."""
        login = getattr(self.ctx, "login", "")
        token = getattr(self.ctx, "session_token", "")

        if not login:
            try:
                self.user_avatar.set_online(None, ring_color="#2f3136")
            except Exception:
                pass
            self._self_status_failures = 0
            return

        if not token:
            try:
                self.user_avatar.set_online(False, ring_color="#2f3136")
            except Exception:
                pass
            self._self_status_failures = 0
            return

        if (not force) and self._self_status_thread and self._self_status_thread.isRunning():
            return

        self._self_status_thread = NetworkThread(None, None, {
            "action": "status",
            "login": login,
            "token": token,
        })

        def _done(resp):
            try:
                if isinstance(resp, dict) and resp.get("status") == "ok":
                    self._self_status_failures = 0
                    online = bool(resp.get("online", False))
                    try:
                        self.user_avatar.set_online(online, ring_color="#2f3136")
                    except Exception:
                        pass
                    try:
                        self.profile_page.update_status(online)
                    except Exception:
                        pass
                else:
                    self._self_status_failures += 1
                    if self._self_status_failures >= 2:
                        try:
                            self.user_avatar.set_online(False, ring_color="#2f3136")
                        except Exception:
                            pass
                        try:
                            self.profile_page.update_status(False)
                        except Exception:
                            pass
            finally:
                self._self_status_thread = None

        self._self_status_thread.finished.connect(_done)
        self._self_status_thread.start()

    # ==================================================
    # ================== Навигация ======================
    # ==================================================

    def set_active_nav(self, active_btn):
        for b in (self.btn_friends, self.btn_chats, self.btn_channels, self.btn_profile):
            b.setProperty("active", b is active_btn)
            b.style().unpolish(b); b.style().polish(b)


    def show_friends(self):
        self.set_active_nav(self.btn_friends)
        self.stack.setCurrentWidget(self.friends_page)

        try:
            if self._current_call_peer():
                self._sync_release_call_state(timeout_sec=0.5)
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
            self._close_call_window()
        except Exception:
            pass
        self._apply_polling_policy(force=True)


    def show_chats(self):
        self.set_active_nav(self.btn_chats)
        self.stack.setCurrentWidget(self.chats_page)
        self._apply_polling_policy(force=True)

    def show_channels(self):
        self.set_active_nav(self.btn_channels)
        self.stack.setCurrentIndex(2)
        self._apply_polling_policy(force=True)


    def show_profile(self):
        self.set_active_nav(self.btn_profile)
        self.stack.setCurrentIndex(3)
        self._apply_polling_policy(force=True)

        # Обновляем онлайн-статус профиля и мини-карточки
        self.refresh_self_status(force=True)

    # ==================================================
    # ============== Переход к авторизации =============
    # ==================================================

    def show_login(self):
        """Переход на экран авторизации (через единый пайплайн логаута)."""
        self.perform_logout()

    def perform_logout(self):
        """Единый логаут: best-effort сообщает серверу и сразу переводит на auth."""
        if self.is_logging_out:
            return
        self.is_logging_out = True

        # Не блокируем UI: делаем короткий синхронный best-effort запрос,
        # после чего в любом случае завершаем локальный переход на auth.
        try:
            self._sync_logout_session(timeout_sec=0.8)
        except Exception:
            pass
        self._do_logout_transition()

    def _sync_logout_session(self, timeout_sec: float = 0.8):
        """Best-effort synchronous logout on server.

        Нужен, чтобы:
        1) кнопка "Выйти" срабатывала предсказуемо даже при сбоях callback/thread,
        2) presence у друзей снимался максимально быстро.
        """
        token = getattr(self.ctx, "session_token", "")
        login = getattr(self.ctx, "login", "")
        if not token or not login:
            return

        payload = {
            "action": "logout",
            "login": login,
            "token": token,
        }

        try:
            host, port = get_api_endpoint()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(max(0.2, float(timeout_sec)))
                s.connect((host, int(port)))
                send_json_packet(s, payload)
                _ = recv_json_packet(s)
        except Exception:
            pass

    def _sync_set_presence_offline(self, timeout_sec: float = 0.7):
        """Best-effort: пометить текущую сессию offline, сохранив токен.

        Используется при закрытии приложения (не logout), чтобы не держать
        пользователя "онлайн" слишком долго до истечения ONLINE_WINDOW на сервере.
        """
        token = getattr(self.ctx, "session_token", "")
        login = getattr(self.ctx, "login", "")
        if not token or not login:
            return

        payload = {
            "action": "presence_offline",
            "login": login,
            "token": token,
        }
        try:
            host, port = get_api_endpoint()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(max(0.2, float(timeout_sec)))
                s.connect((host, int(port)))
                send_json_packet(s, payload)
                _ = recv_json_packet(s)
        except Exception:
            pass

    def _do_logout_transition(self):
        # Остановить автообновления
        try:
            if hasattr(self, "call_events_timer") and self.call_events_timer.isActive():
                self.call_events_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "heartbeat_timer") and self.heartbeat_timer.isActive():
                self.heartbeat_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "self_status_timer") and self.self_status_timer.isActive():
                self.self_status_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "channel_invites_badge_timer") and self.channel_invites_badge_timer.isActive():
                self.channel_invites_badge_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_self_status_thread", None) and self._self_status_thread.isRunning():
                self._self_status_thread.abort()
        except Exception:
            pass
        try:
            if getattr(self, "_channel_invites_badge_thread", None) and self._channel_invites_badge_thread.isRunning():
                self._channel_invites_badge_thread.abort()
        except Exception:
            pass
        try:
            if getattr(self, "_outgoing_call_thread", None) and self._outgoing_call_thread.isRunning():
                self._outgoing_call_thread.abort()
        except Exception:
            pass

        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass
        try:
            self.channels_page.stop_auto_update()
        except Exception:
            pass

        try:
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
            self._close_call_window()
            self._hide_incoming_inline()
            self._hide_call_notice()
            if hasattr(self, "_call_notice_timer") and self._call_notice_timer.isActive():
                self._call_notice_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self.channels_page, "stop_voice_session"):
                self.channels_page.stop_voice_session(show_toast=False)
        except Exception:
            pass
        try:
            if hasattr(self.friends_page, "timer"):
                self.friends_page.timer.stop()
        except Exception:
            pass

        # Корректно остановить запросы страниц
        for page in (self.friends_page, self.chats_page, self.channels_page, self.profile_page):
            try:
                page._alive = False
                if hasattr(page, "shutdown_requests"):
                    page.shutdown_requests(wait_ms=1000)
            except Exception:
                pass

        try:
            clear_config()
        except Exception:
            pass
        # Чистим глобальный singleton + локальную копию контекста
        try:
            UserContext().clear()
        except Exception:
            pass
        self.ctx = self._snapshot_context(UserContext())
        self.update_chats_badge(0)
        self.update_channels_badge(0)

        try:
            if self.controller is not None:
                self.controller.logout_to_auth()
        finally:
            # Иначе при повторном логине кнопка "Выйти" перестаёт работать.
            self.is_logging_out = False

    # ==================================================
    # ================== Закрытие окна =================
    # ==================================================


    def poll_call_events(self):
        if not getattr(self.ctx, "login", None) or not getattr(self.ctx, "session_token", ""):
            return
        if self.call_poll_thread and self.call_poll_thread.isRunning():
            return
        self.call_poll_thread = NetworkThread(None, None, {
            "action": "poll_events",
            "login": self.ctx.login,
            "token": self.ctx.session_token,
        })
        self.call_poll_thread.finished.connect(self.handle_call_events)
        self.call_poll_thread.start()

    def handle_call_events(self, resp):
        if resp.get("status") != "ok":
            return
        for ev in resp.get("events", []):
            et = ev.get("type")
            if et == "incoming_call":
                from_user = ev.get("from_user")
                self._show_incoming_inline(from_user)

            elif et == "call_accepted":
                by_user = ev.get("by_user")
                self.current_call_user = by_user
                self._hide_incoming_inline()
                self._start_voice_for_peer(by_user)
                self._open_call_window(by_user)
                self._show_call_notice(f"{by_user} принял вызов", timeout_ms=1600)

            elif et == "call_started":
                with_user = ev.get("with_user")
                self.current_call_user = with_user
                self._hide_incoming_inline()
                self._start_voice_for_peer(with_user)
                self._open_call_window(with_user)
                self._show_call_notice(f"Звонок с {with_user} начат", timeout_ms=1600)

            elif et == "call_declined":
                by_user = ev.get("by_user")
                self.current_call_user = None
                self._close_call_window()
                try:
                    if self.voice_client:
                        self.voice_client.stop()
                        self.voice_client = None
                except Exception:
                    pass
                self._show_call_notice(f"{by_user} отклонил вызов", timeout_ms=2200)

            elif et == "call_ended":
                with_user = ev.get("with_user") or ev.get("by_user") or "пользователем"
                self.current_call_user = None
                self._close_call_window()
                try:
                    if self.voice_client:
                        self.voice_client.stop()
                        self.voice_client = None
                except Exception:
                    pass
                self._show_call_notice(f"Звонок с {with_user} завершён", timeout_ms=2300)

    def _start_voice_for_peer(self, peer_login: str):
        try:
            if hasattr(self.channels_page, "stop_voice_session"):
                self.channels_page.stop_voice_session(show_toast=False)
        except Exception:
            pass

        try:
            if self.voice_client:
                self.voice_client.stop()
            v_host, v_port = get_voice_endpoint()
            self.voice_client = VoiceClient(
                login=self.ctx.login,
                token=getattr(self.ctx, "session_token", ""),
                host=v_host,
                port=v_port,
            )
            self.voice_client.start(peer_login=peer_login)
        except Exception as e:
            self._show_call_notice(f"Не удалось запустить аудио: {e}", timeout_ms=2800)

    def _open_call_window(self, peer_login: str):
        def on_end_call():
            try:
                t = NetworkThread(None, None, {
                    "action": "end_call",
                    "login": self.ctx.login,
                    "with_user": peer_login,
                    "token": self.ctx.session_token,
                })
                t.start()
            except Exception:
                pass

        def on_mic_toggle(enabled: bool):
            if self.voice_client:
                self.voice_client.set_mic_enabled(enabled)

        def on_sound_toggle(enabled: bool):
            if self.voice_client:
                self.voice_client.set_sound_enabled(enabled)

        if self.call_window and self.call_window.isVisible():
            self.call_window._ending = True
            self.call_window.close()

        self.call_window = ActiveCallWindow(
            my_login=self.ctx.login,
            peer_login=peer_login,
            peer_nickname=peer_login,
            peer_avatar="",
            on_end=on_end_call,
            on_mic_toggle=on_mic_toggle,
            on_sound_toggle=on_sound_toggle,
            activity_provider=(lambda: self.voice_client.get_activity() if self.voice_client else {}),
            parent=self,
        )
        self.call_window.show()

        # обновим имя/аватар из сервера
        info_t = NetworkThread(None, None, {
            "action": "find_user",
            "login": peer_login,
            "token": self.ctx.session_token,
        })
        def _apply_info(resp):
            if resp.get("status") == "ok" and self.call_window:
                nick = resp.get("nickname") or peer_login
                avatar = resp.get("avatar") or ""
                self.call_window.name_lbl.setText(nick)
                self.call_window.login_lbl.setText(peer_login)
                self.call_window.avatar.set_avatar(path=avatar, login=peer_login, nickname=nick)
        info_t.finished.connect(_apply_info)
        info_t.start()

    def _close_call_window(self):
        try:
            if self.call_window:
                self.call_window._ending = True
                self.call_window.close()
        except Exception:
            pass
        self.call_window = None

    def _current_call_peer(self):
        peer = self.current_call_user
        if peer:
            return peer
        try:
            if self.call_window and getattr(self.call_window, "peer_login", None):
                return self.call_window.peer_login
        except Exception:
            pass
        return None

    def _sync_release_call_state(self, timeout_sec: float = 0.8):
        """Best-effort synchronous call-state release.

        Needed during app shutdown: async threads may not finish before process exits,
        which could leave stale 'busy' state on the server.
        """
        token = getattr(self.ctx, "session_token", "")
        login = getattr(self.ctx, "login", "")
        if not token or not login:
            return

        payload = {
            "action": "release_call_state",
            "login": login,
            "token": token,
        }

        try:
            host, port = get_api_endpoint()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(max(0.2, float(timeout_sec)))
                s.connect((host, int(port)))
                send_json_packet(s, payload)
                _ = recv_json_packet(s)
        except Exception:
            pass
        finally:
            self.current_call_user = None

    def resizeEvent(self, event):
        try:
            self._reposition_inline_call_ui()
        except Exception:
            pass
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_polling_policy()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._apply_polling_policy()

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            et = event.type()
        except Exception:
            et = None
        if et in (QEvent.WindowStateChange, QEvent.ActivationChange):
            self._apply_polling_policy()

    def closeEvent(self, event):
        if self._is_closing:
            event.accept()
            return
        self._is_closing = True

        # Если это logout-переход на auth — не выходим из приложения
        if self.is_logging_out:
            event.accept()
            return

        # Это закрытие приложения на крестик
        try:
            self._hide_incoming_inline()
            self._hide_call_notice()
            if hasattr(self, "_call_notice_timer") and self._call_notice_timer.isActive():
                self._call_notice_timer.stop()
        except Exception:
            pass

        try:
            # Важно: на закрытии приложения очищаем call-state синхронно,
            # иначе сервер может оставить пару как "занят".
            self._sync_release_call_state(timeout_sec=0.9)
        except Exception:
            pass

        try:
            # Сохраняем токен для auto-login, но явно снимаем online presence.
            self._sync_set_presence_offline(timeout_sec=0.7)
        except Exception:
            pass

        try:
            if hasattr(self, "call_events_timer") and self.call_events_timer.isActive():
                self.call_events_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "heartbeat_timer") and self.heartbeat_timer.isActive():
                self.heartbeat_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_channel_invites_badge_thread", None) and self._channel_invites_badge_thread.isRunning():
                self._channel_invites_badge_thread.abort()
        except Exception:
            pass
        try:
            if hasattr(self, "self_status_timer") and self.self_status_timer.isActive():
                self.self_status_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_self_status_thread", None) and self._self_status_thread.isRunning():
                self._self_status_thread.abort()
        except Exception:
            pass

        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass
        try:
            self.channels_page.stop_auto_update()
        except Exception:
            pass

        try:
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
            self._hide_incoming_inline()
            self._hide_call_notice()
            if hasattr(self, "_call_notice_timer") and self._call_notice_timer.isActive():
                self._call_notice_timer.stop()
        except Exception:
            pass

        try:
            if hasattr(self.friends_page, "timer"):
                self.friends_page.timer.stop()
        except Exception:
            pass

        # Остановить фоновые запросы страниц
        for page in (self.friends_page, self.chats_page, self.channels_page, self.profile_page):
            try:
                page._alive = False
                if hasattr(page, "shutdown_requests"):
                    page.shutdown_requests(wait_ms=1000)
            except Exception:
                pass

        # Не делаем явный logout при закрытии приложения: токен остаётся
        # в конфиге и сессия может быть восстановлена при следующем запуске.

        app = QApplication.instance()
        if app is not None:
            app.quit()

        event.accept()

    def reload_from_context(self, full_reset=False):
        """
        Подтягивает актуального пользователя из UserContext
        и перезапускает страницы после логина/перелогина.
        """
        from user_context import UserContext
        self.ctx = self._snapshot_context(UserContext())
        self.is_logging_out = False

        # После logout страницы переводятся в _alive=False.
        # При следующем логине обязательно реанимируем их.
        for page in (self.friends_page, self.chats_page, self.channels_page, self.profile_page):
            try:
                page._alive = True
            except Exception:
                pass

        # Восстанавливаем сервисные таймеры (интервалы задаст policy).
        try:
            if hasattr(self, "call_events_timer") and not self.call_events_timer.isActive():
                self.call_events_timer.start()
        except Exception:
            pass
        try:
            if hasattr(self, "heartbeat_timer") and not self.heartbeat_timer.isActive():
                self.heartbeat_timer.start()
        except Exception:
            pass
        try:
            if hasattr(self, "channel_invites_badge_timer") and not self.channel_invites_badge_timer.isActive():
                self.channel_invites_badge_timer.start()
        except Exception:
            pass

        # Обновляем профиль/мини-карточку
        try:
            self.profile_page.login = self.ctx.login
            self.profile_page.nickname = self.ctx.nickname
            self.profile_page.nickname_edit.setText(self.ctx.nickname)
            if hasattr(self.profile_page, "login_label"):
                self.profile_page.login_label.setText(self.ctx.login or "—")
            self.profile_page.avatar_path = self.ctx.avatar or ""
            self.profile_page._apply_avatar(self.profile_page.avatar_path)
            if hasattr(self.profile_page, "set_user_data"):
                self.profile_page.set_user_data(self.ctx.login, self.ctx.nickname, getattr(self.ctx, "avatar", ""))

            self.user_nick_lbl.setText(self.ctx.nickname or "Гость")
            self.user_login_lbl.setText(self.ctx.login or "")
            self.user_avatar.set_avatar(path=getattr(self.ctx, "avatar", ""), login=self.ctx.login, nickname=self.ctx.nickname)
            self.user_avatar.set_online(None if not self.ctx.login else False, ring_color="#2f3136")
        except Exception:
            pass

        # Передаем новый контекст дочерним страницам
        try:
            self.friends_page.ctx = self.ctx
        except Exception:
            pass

        try:
            self.chats_page.ctx = self.ctx
        except Exception:
            pass

        try:
            self.channels_page.ctx = self.ctx
        except Exception:
            pass

        try:
            self.profile_page.ctx = self.ctx
        except Exception:
            pass

        try:
            if hasattr(self, "self_status_timer") and not self.self_status_timer.isActive():
                self.self_status_timer.start()
        except Exception:
            pass
        self.refresh_self_status(force=True)
        self.poll_channel_invites_badge(force=True)

        if full_reset:
            # Сброс страниц под нового пользователя
            try:
                if hasattr(self.friends_page, "reset_for_user"):
                    self.friends_page.reset_for_user()
                else:
                    self.friends_page.clear_list()
                    self.friends_page._loading_friends = False
                    self.friends_page._loading_requests = False
                    self.friends_page._found_user = None
                self.friends_page.refresh()
            except Exception:
                pass

            try:
                if hasattr(self.chats_page, "reset_for_user"):
                    self.chats_page.reset_for_user()
                else:
                    self.chats_page.stop_auto_update()
                    self.chats_page.active_friend = None
                    self.chats_page._loading_friends = False
                    self.chats_page._loading_messages = False
                    self.chats_page._sending = False
                    self.chats_page._loading_unread = False
                    self.chats_page.unread_counts = {}
                    self.chats_page.unread_total = 0
                    self.chats_page.chat_header.setText("Выберите друга")
                    self.chats_page._clear_friends()
                    self.chats_page._clear_messages()
                self.chats_page.start_auto_update(force_refresh=True)  # подтянет unread + friends
            except Exception:
                pass

            try:
                if hasattr(self.channels_page, "reset_for_user"):
                    self.channels_page.reset_for_user()
            except Exception:
                pass

        # По умолчанию открываем друзей
        self.show_friends()
        self._apply_polling_policy(force=True)


    def prepare_to_close_app(self):
        """
        Вызывается контейнером AppWindow при закрытии приложения.
        """
        try:
            self._sync_release_call_state(timeout_sec=0.9)
        except Exception:
            pass

        try:
            self._sync_set_presence_offline(timeout_sec=0.7)
        except Exception:
            pass

        try:
            if hasattr(self, "call_events_timer") and self.call_events_timer.isActive():
                self.call_events_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "heartbeat_timer") and self.heartbeat_timer.isActive():
                self.heartbeat_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "channel_invites_badge_timer") and self.channel_invites_badge_timer.isActive():
                self.channel_invites_badge_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "self_status_timer") and self.self_status_timer.isActive():
                self.self_status_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_self_status_thread", None) and self._self_status_thread.isRunning():
                self._self_status_thread.abort()
        except Exception:
            pass

        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass
        try:
            self.channels_page.stop_auto_update()
        except Exception:
            pass

        try:
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
        except Exception:
            pass
        try:
            if hasattr(self.channels_page, "stop_voice_session"):
                self.channels_page.stop_voice_session(show_toast=False)
        except Exception:
            pass
        try:
            if hasattr(self.friends_page, "timer"):
                self.friends_page.timer.stop()
        except Exception:
            pass

        for page in (self.friends_page, self.chats_page, self.channels_page, self.profile_page):
            try:
                page._alive = False
                if hasattr(page, "shutdown_requests"):
                    page.shutdown_requests(wait_ms=1200)
            except Exception:
                pass

