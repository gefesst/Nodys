from application.call_controller import CallController
from application.polling import PollingController
from application.session_cleanup import submit as submit_session_cleanup
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
from network import NetworkThread
from application.voice_session import VoiceSession
from config import clear_config
from settings import get_voice_endpoint, get_api_endpoint
from ui.micro_interactions import install_opacity_feedback

from ui.design.motion import TransitionStack as QStackedWidget


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

        # Shared narrow navigation rail from the approved design.
        from ui.design.shell import NavButton
        from ui.design.widgets import Button
        from ui.design.tokens import RAIL_WIDTH
        sidebar = QWidget()
        sidebar.setObjectName('Sidebar')
        sidebar.setFixedWidth(RAIL_WIDTH)
        menu_layout = QVBoxLayout(sidebar)
        menu_layout.setContentsMargins(12,24,12,16)
        menu_layout.setSpacing(18)
        brand = Button('', 'n', True)
        brand.setFixedSize(50,50)
        brand.setFocusPolicy(Qt.NoFocus)
        brand.clicked.connect(self.show_friends)
        menu_layout.addWidget(brand,0,Qt.AlignHCenter)
        wordmark = QLabel('nodus');wordmark.setAlignment(Qt.AlignCenter)
        menu_layout.addWidget(wordmark)
        self.btn_friends = NavButton('Друзья','users')
        self.btn_chats = NavButton('Чаты','chat')
        self.btn_channels = NavButton('Каналы','hash')
        for button, action in ((self.btn_friends,self.show_friends),(self.btn_chats,self.show_chats),(self.btn_channels,self.show_channels)):
            button.clicked.connect(action);menu_layout.addWidget(button)
        menu_layout.addStretch()
        self.quick_button = Button('', 'keyboard');self.quick_button.setToolTip('Найти диалог')
        self.quick_button.setProperty('flat', True)
        self.quick_button.clicked.connect(self.open_quick_switch)
        from PySide6.QtGui import QShortcut, QKeySequence
        self.quick_shortcut = QShortcut(QKeySequence('Meta+K' if __import__('sys').platform=='darwin' else 'Ctrl+K'),self)
        self.quick_shortcut.activated.connect(self.open_quick_switch)
        menu_layout.addWidget(self.quick_button)
        self.settings_button = Button('', 'settings');self.settings_button.setToolTip('Настройки приложения')
        self.settings_button.setProperty('flat', True)
        self.settings_button.clicked.connect(self.show_settings)
        menu_layout.addWidget(self.settings_button)
        divider=QFrame();divider.setObjectName('Divider');divider.setFixedHeight(1);menu_layout.addWidget(divider)
        self.user_card=QFrame();self.user_card.setObjectName('UserMiniCard')
        user_layout=QVBoxLayout(self.user_card);user_layout.setContentsMargins(0,0,0,0);user_layout.setSpacing(2)
        self.user_avatar=AvatarLabel(size=40);user_layout.addWidget(self.user_avatar,0,Qt.AlignHCenter)
        self.user_nick_lbl=QLabel('Вы');self.user_nick_lbl.setObjectName('UserMiniNick');self.user_nick_lbl.setAlignment(Qt.AlignCenter)
        self.user_login_lbl=QLabel();self.user_login_lbl.hide()
        user_layout.addWidget(self.user_nick_lbl)
        self.user_card.mousePressEvent=lambda event:self.show_profile()
        menu_layout.addWidget(self.user_card)
        self.btn_profile=NavButton('Профиль','profile');self.btn_profile.hide()
        self.btn_profile.clicked.connect(self.show_profile)
        root=QHBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(0)
        root.addWidget(sidebar)
        workspace=QWidget();workspace_layout=QVBoxLayout(workspace);workspace_layout.setContentsMargins(0,0,0,0);workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self.stack,1)
        self.voice_dock=QFrame();self.voice_dock.setObjectName('CallCard');dock=QHBoxLayout(self.voice_dock)
        self.voice_dock_label=QLabel();dock.addWidget(self.voice_dock_label,1)
        open_voice=Button('Открыть','wave');open_voice.clicked.connect(self.open_voice_surface);dock.addWidget(open_voice)
        end_voice=Button('Отключиться','end');end_voice.clicked.connect(self.end_voice_surface);dock.addWidget(end_voice)
        workspace_layout.addWidget(self.voice_dock);self.voice_dock.hide();root.addWidget(workspace,1)

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
        self.call_window = None
        self.calls = CallController(lambda: self.ctx, self)
        self.calls.state_changed.connect(self._reconcile_call_state)
        self.calls.notice.connect(lambda text, timeout: self._show_call_notice(text, timeout_ms=timeout))
        self.calls.response_finished.connect(self._incoming_response_finished)
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

        self.polling = PollingController(
            [(self.call_events_timer, 1000, 2600), (self.heartbeat_timer, 10000, 18000),
             (self.self_status_timer, 5000, 12000), (self.channel_invites_badge_timer, 9000, 18000)],
            [(lambda: self.friends_page.set_polling_enabled(True), lambda: self.friends_page.set_polling_enabled(False)),
             (lambda: self.chats_page.start_auto_update(force_refresh=True), self.chats_page.stop_auto_update),
             (self.channels_page.start_auto_update, self.channels_page.stop_auto_update)])
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

    def _apply_polling_policy(self, force=False):
        if not hasattr(self, "polling"):
            return
        became_active = self.polling.apply(self._window_is_active_for_polling(),
                                           self.stack.currentIndex(), bool(self.ctx.login), force)
        if became_active:
            self.refresh_self_status(force=True)

    # ==================================================
    # ============ Inline call UI (in-app) ============
    # ==================================================

    def _setup_inline_call_ui(self):
        self._incoming_from_user = None

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

        self.incoming_shade=QFrame(self)
        self.incoming_shade.setStyleSheet('background:rgba(8,14,24,170);')
        self.incoming_shade.hide()
        self.incoming_card = QFrame(self)
        self.incoming_card.setObjectName("IncomingCallInlineCard")
        self.incoming_card.setVisible(False)
        incoming_l = QVBoxLayout(self.incoming_card)
        incoming_l.setContentsMargins(32, 32, 32, 32)
        incoming_l.setSpacing(10)

        incoming_title = QLabel("Входящий вызов", self.incoming_card)
        incoming_title.setObjectName("IncomingCallInlineTitle")
        incoming_title.setAlignment(Qt.AlignCenter)
        incoming_l.addWidget(incoming_title)
        incoming_l.addSpacing(24)
        self.incoming_avatar=AvatarLabel(96)
        incoming_l.addWidget(self.incoming_avatar,0,Qt.AlignHCenter)

        self.incoming_from_lbl = QLabel("", self.incoming_card)
        self.incoming_from_lbl.setObjectName("IncomingCallInlineFrom")
        self.incoming_from_lbl.setWordWrap(True)
        self.incoming_from_lbl.setAlignment(Qt.AlignCenter)
        incoming_l.addWidget(self.incoming_from_lbl)
        incoming_l.addSpacing(32)

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
        if hasattr(self,"incoming_shade"):
            self.incoming_shade.setGeometry(self.rect())
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
            # Toast width, but constrained by current page width
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
            self.incoming_card.move(_center_x(in_w), max(16,(self.height()-in_h)//2))
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
        peer=next((r for r in self.friends_page._friends_data if r.get('login')==from_user),{})
        name=peer.get('nickname') or from_user
        self.incoming_avatar.set_avatar(path=peer.get('avatar',''),login=from_user,nickname=name)
        self.incoming_from_lbl.setText(f"{name}\n@{from_user}")
        self._set_incoming_buttons_enabled(True)
        self._reposition_inline_call_ui()
        self.incoming_shade.setGeometry(self.rect())
        self.incoming_shade.show()
        self.incoming_shade.raise_()
        self.incoming_card.show()
        self.incoming_card.raise_()

    def _hide_incoming_inline(self):
        self._incoming_from_user = None
        if getattr(self, "incoming_card", None):
            self.incoming_card.hide()
            self.incoming_shade.hide()

    def _set_incoming_buttons_enabled(self, enabled: bool):
        try:
            self.incoming_accept_btn.setEnabled(enabled)
            self.incoming_decline_btn.setEnabled(enabled)
        except Exception:
            pass

    def _respond_incoming_inline(self, accept: bool):
        if self.calls.respond(accept):
            self._set_incoming_buttons_enabled(False)

    def _incoming_response_finished(self, success):
        self._set_incoming_buttons_enabled(True)
        if success:
            self._hide_incoming_inline()

    def _accept_incoming_inline(self):
        self._respond_incoming_inline(True)

    def _decline_incoming_inline(self):
        self._respond_incoming_inline(False)

    def start_outgoing_call(self, friend_login: str):
        if not self.calls.start_call(friend_login):
            self._show_call_notice("Подождите, предыдущий вызов ещё отправляется", timeout_ms=1800)

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
        self.settings_button.primary = active_btn is None
        self.settings_button.update()
        for b in (self.btn_friends, self.btn_chats, self.btn_channels, self.btn_profile):
            b.setProperty("active", b is active_btn)
            b.update()


    def open_quick_switch(self):
        from ui.design.quick_switch import QuickSwitch
        self.quick_switch = QuickSwitch(self)
        self.quick_switch.show()

    def show_settings(self):
        self.set_active_nav(None)
        from ui.design.settings_page import SettingsPage
        if not hasattr(self,'settings_page'):
            self.settings_page=SettingsPage(self)
            self.stack.addWidget(self.settings_page)
        self.stack.setCurrentWidget(self.settings_page)
        self._apply_polling_policy(force=True)

    def show_friends(self):
        self.set_active_nav(self.btn_friends)
        self.stack.setCurrentWidget(self.friends_page)

        self._apply_polling_policy(force=True)


    def show_chats(self):
        self.set_active_nav(self.btn_chats)
        self.stack.setCurrentWidget(self.chats_page)
        self._apply_polling_policy(force=True)

    def show_channels(self):
        self.set_active_nav(self.btn_channels)
        self.stack.setCurrentIndex(2)
        self._apply_polling_policy(force=True)
        # Explicit navigation must load once even before the OS reports focus.
        if not self.channels_page._loading_channels:
            self.channels_page.load_channels(force_refresh=True)


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

        self._queue_session_cleanup("logout")
        self._do_logout_transition()

    def _queue_session_cleanup(self, action, timeout_sec=1):
        token = getattr(self.ctx, "session_token", "")
        login = getattr(self.ctx, "login", "")
        if token and login:
            try:
                endpoint = get_api_endpoint()
            except (ValueError, TypeError):
                return
            payload = {"action":action, "login":login, "token":token}
            if action == "release_call_state":
                state = self.calls.state
                if not state:
                    return
                payload["call_id"] = state["call_id"]
            submit_session_cleanup(endpoint, payload, timeout=timeout_sec)

    def _queue_presence_offline(self, timeout_sec=0.7):
        self._queue_session_cleanup("presence_offline", timeout_sec)

    def _do_logout_transition(self):
        self._stop_background_work()

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
        self.calls.poll()
        self.refresh_voice_dock()

    def refresh_voice_dock(self):
        private = bool(self.voice_client)
        channel = bool(getattr(self.channels_page,'_voice_joined',False))
        self.voice_dock.setVisible(private or channel)
        if private:
            activity=self.voice_client.get_activity()
            peer=self.current_call_user or 'Собеседник'
            self.voice_dock_label.setText(f'Звонок · {peer} · {activity.get("quality","Подключение")}')
        elif channel:
            self.voice_dock_label.setText('Голосовой канал · '+str((self.channels_page.active_channel or {}).get('name','')))

    def open_voice_surface(self):
        if self.call_window:
            self.call_window.show();self.call_window.raise_()
        else:
            self.show_channels();self.channels_page.switch_to_voice_tab()

    def end_voice_surface(self):
        if self.call_window:
            self.call_window._end_clicked()
        else:
            self.channels_page.stop_voice_session()
        self.voice_dock.hide()

    def handle_call_events(self, response):
        self.calls.receive(response)

    def _reconcile_call_state(self, state):
        """The snapshot heals missed/expired events and avoids duplicate audio starts."""
        key = (self.ctx.session_token, None if state is None else
               (state.get("call_id"), state.get("peer"), state.get("status"), state.get("incoming")))
        if getattr(self, "_rendered_call_key", None) == key:
            return
        self._rendered_call_key = key
        outgoing = getattr(self, 'outgoing_window', None)
        if outgoing is not None:
            outgoing.finished_by_server = True
            outgoing.close()
            self.outgoing_window = None
        if state is None:
            self._hide_incoming_inline()
            if self.current_call_user or self.voice_client or self.call_window:
                self.current_call_user = None
                if self.voice_client:
                    self.voice_client.stop()
                    self.voice_client = None
                self._close_call_window()
            return
        peer = state.get("peer")
        if state.get("status") == "active":
            self._hide_incoming_inline()
            self.current_call_user = peer
            self._start_voice_for_peer(peer)
            self._open_call_window(peer)
        elif state.get("status") == "ringing" and state.get("incoming"):
            self._show_incoming_inline(peer)
        elif state.get('status') == 'ringing':
            from ui.call_window import OutgoingCallWindow
            call_id = state['call_id']
            self.outgoing_window = OutgoingCallWindow(peer, lambda: self.calls.end_call(call_id, peer), self)
            self.outgoing_window.show()

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
            self.voice_client = VoiceSession(
                login=self.ctx.login,
                token=getattr(self.ctx, "session_token", ""),
                host=v_host,
                port=v_port,
            )
            voice = self.voice_client
            def failed(message):
                if self.voice_client is voice:
                    voice.stop()
                    self.voice_client = None
                    self._show_call_notice(f"Не удалось запустить аудио: {message}", timeout_ms=2800)
            voice.failed.connect(failed)
            self.voice_client.start(peer_login=peer_login)
        except Exception as e:
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
            self._show_call_notice(f"Не удалось запустить аудио: {e}", timeout_ms=2800)

    def _open_call_window(self, peer_login: str):
        call_id = self.calls.state["call_id"] if self.calls.state else ""
        token = self.ctx.session_token
        def on_end_call():
            if self.ctx.session_token == token and call_id:
                self.calls.end_call(call_id, peer_login)

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
        call_window = self.call_window
        def _apply_info(resp):
            if resp.get("status") == "ok" and self.ctx.session_token == token and self.call_window is call_window:
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

    def _queue_release_call_state(self, timeout_sec=0.8):
        self._queue_session_cleanup("release_call_state", timeout_sec)
        self.calls.reset()
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
        if not self._is_closing and not self.is_logging_out:
            self._is_closing = True
            self.prepare_to_close_app()
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
        self.calls.reset()
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

            self.user_nick_lbl.setText("Вы")
            self.user_card.setToolTip(self.ctx.nickname or self.ctx.login)
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
        self._queue_release_call_state(timeout_sec=0.9)
        self._queue_presence_offline(timeout_sec=0.7)
        self._stop_background_work()

    def _stop_background_work(self):
        """One nonblocking cleanup path for logout and application close."""
        self.calls.reset()
        outgoing = getattr(self, 'outgoing_window', None)
        if outgoing is not None:
            outgoing.finished_by_server = True
            outgoing.close()
            self.outgoing_window = None
        quick = getattr(self, 'quick_switch', None)
        if quick is not None:
            quick.close()
        settings = getattr(self, 'settings_page', None)
        microphone = getattr(settings, 'microphone_check', None)
        if microphone is not None:
            microphone.close()
        dock = getattr(self, 'voice_dock', None)
        if dock is not None:
            dock.hide()
        for name in ("call_events_timer", "heartbeat_timer", "self_status_timer",
                     "channel_invites_badge_timer", "_call_notice_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        for name in ("_self_status_thread", "_channel_invites_badge_thread"):
            request = getattr(self, name, None)
            if request is not None:
                request.abort()
        self.chats_page.stop_auto_update()
        self.channels_page.stop_auto_update()
        self.friends_page.set_polling_enabled(False)
        self.channels_page.stop_voice_session(show_toast=False)
        if self.voice_client:
            self.voice_client.stop()
            self.voice_client = None
        self._close_call_window()
        self._hide_incoming_inline()
        self._hide_call_notice()
        for page in (self.friends_page, self.chats_page, self.channels_page, self.profile_page):
            page._alive = False
            page.shutdown_requests(wait_ms=0)

