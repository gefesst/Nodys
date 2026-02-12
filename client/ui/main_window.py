from PySide6.QtCore import QTimer
import os

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QSizePolicy, QStackedWidget, QApplication, QLabel, QFrame, QMessageBox
)
from PySide6.QtGui import QIcon

from ui.channels_page import ChannelsPage
from ui.profile_page import ProfilePage
from ui.friends_page import FriendsPage
from ui.chats_page import ChatsPage
from ui.avatar_widget import AvatarLabel
from ui.incoming_call_dialog import IncomingCallDialog
from ui.call_window import ActiveCallWindow

from user_context import UserContext
from network import NetworkThread
from voice_client import VoiceClient


class MainWindow(QWidget):
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.ctx = UserContext()

        self.is_logging_out = False
        self._is_closing = False

        self.setWindowTitle("Nodys")
        self.setMinimumSize(900, 600)
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

        # Подписка на обновление общего unread из ChatsPage
        self.chats_page.on_unread_total_changed = self.update_chats_badge

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

        def make_button(text, callback):
            btn = QPushButton(text)
            btn.setFixedHeight(50)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setObjectName("NavButton")
            btn.clicked.connect(callback)
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

        # Стартовая вкладка
        self.show_friends()

        # И сразу подгрузим unread, чтобы кнопка "Чаты" была актуальной
        self.chats_page.load_unread_counts()

        # Call signaling poll
        self.current_call_user = None
        self.voice_client = None
        self.call_poll_thread = None
        self.call_window = None
        self.call_events_timer = QTimer(self)
        self.call_events_timer.timeout.connect(self.poll_call_events)
        self.call_events_timer.start(1000)

    # ==================================================
    # ================== Бейдж "Чаты" ==================
    # ==================================================

    def update_chats_badge(self, total: int):
        if total > 0:
            self.btn_chats.setText(f"Чаты ({total})")
        else:
            self.btn_chats.setText("Чаты")

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

        # ВАЖНО: polling входящих звонков должен работать на любых вкладках,
        # поэтому НЕ останавливаем call_events_timer в "Друзьях".
        try:
            if hasattr(self, "call_events_timer") and not self.call_events_timer.isActive():
                self.call_events_timer.start(1000)
        except Exception:
            pass

        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass

        try:
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
            self._close_call_window()
        except Exception:
            pass
        try:
            self.friends_page.refresh()
            if hasattr(self.friends_page, "timer") and not self.friends_page.timer.isActive():
                self.friends_page.timer.start(5000)
        except Exception:
            pass


    def show_chats(self):
        self.set_active_nav(self.btn_chats)
        self.stack.setCurrentWidget(self.chats_page)
        try:
            if hasattr(self.friends_page, "timer") and self.friends_page.timer.isActive():
                self.friends_page.timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "call_events_timer") and not self.call_events_timer.isActive():
                self.call_events_timer.start(1000)
        except Exception:
            pass
        try:
            self.chats_page.start_auto_update()
        except Exception:
            pass

    def show_channels(self):
        self.set_active_nav(self.btn_channels)
        self.chats_page.stop_auto_update()
        self.stack.setCurrentIndex(2)
        try:
            if hasattr(self, "call_events_timer") and not self.call_events_timer.isActive():
                self.call_events_timer.start(1000)
        except Exception:
            pass

    def show_profile(self):
        self.set_active_nav(self.btn_profile)
        self.chats_page.stop_auto_update()
        self.stack.setCurrentIndex(3)
        try:
            if hasattr(self, "call_events_timer") and not self.call_events_timer.isActive():
                self.call_events_timer.start(1000)
        except Exception:
            pass

        # Обновляем онлайн-статус профиля
        data = {"action": "status", "login": self.ctx.login}
        self.status_thread = NetworkThread("127.0.0.1", 5555, data)

        def on_status(resp):
            self.profile_page.update_status(resp.get("online", False))

        self.status_thread.finished.connect(on_status)
        self.status_thread.start()

    # ==================================================
    # ============== Переход к авторизации =============
    # ==================================================

    def show_login(self):
        """
        Вызывается из ProfilePage после logout.
        Это НЕ закрытие приложения, а смена сессии.
        """
        self.is_logging_out = True

        # Остановить автообновления
        try:
            if hasattr(self, "call_events_timer") and self.call_events_timer.isActive():
                self.call_events_timer.stop()
        except Exception:
            pass

        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass

        try:
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
            self._close_call_window()
        except Exception:
            pass
        try:
            if hasattr(self.friends_page, "timer"):
                self.friends_page.timer.stop()
        except Exception:
            pass

        # Корректно остановить запросы страниц
        for page in (self.friends_page, self.chats_page, self.profile_page):
            try:
                page._alive = False
                if hasattr(page, "shutdown_requests"):
                    page.shutdown_requests(wait_ms=1000)
            except Exception:
                pass

        self.ctx.clear()

        if self.controller is not None:
            self.controller.logout_to_auth()

    # ==================================================
    # ================== Закрытие окна =================
    # ==================================================


    def poll_call_events(self):
        if not getattr(self.ctx, "login", None):
            return
        if self.call_poll_thread and self.call_poll_thread.isRunning():
            return
        self.call_poll_thread = NetworkThread(
            "127.0.0.1", 5555,
            {"action": "poll_events", "login": self.ctx.login}
        )
        self.call_poll_thread.finished.connect(self.handle_call_events)
        self.call_poll_thread.start()

    def handle_call_events(self, resp):
        if resp.get("status") != "ok":
            return
        for ev in resp.get("events", []):
            et = ev.get("type")
            if et == "incoming_call":
                from_user = ev.get("from_user")
                dlg = IncomingCallDialog(
                    self.ctx.login, from_user, parent=self,
                    on_result=self._on_incoming_result
                )
                dlg.exec()

            elif et == "call_accepted":
                by_user = ev.get("by_user")
                self.current_call_user = by_user
                self._start_voice_for_peer(by_user)
                self._open_call_window(by_user)

            elif et == "call_started":
                with_user = ev.get("with_user")
                self.current_call_user = with_user
                self._start_voice_for_peer(with_user)
                self._open_call_window(with_user)

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
                QMessageBox.information(self, "Звонок", f"{by_user} отклонил вызов")

            elif et == "call_ended":
                with_user = ev.get("with_user")
                self.current_call_user = None
                self._close_call_window()
                try:
                    if self.voice_client:
                        self.voice_client.stop()
                        self.voice_client = None
                except Exception:
                    pass
                QMessageBox.information(self, "Звонок", f"Звонок с {with_user} завершён")

    def _on_incoming_result(self, result, resp):
        # Хук на будущее (например, открыть экран активного звонка)
        pass

    def _start_voice_for_peer(self, peer_login: str):
        try:
            if self.voice_client:
                self.voice_client.stop()
            self.voice_client = VoiceClient(login=self.ctx.login)
            self.voice_client.start(peer_login=peer_login)
        except Exception as e:
            QMessageBox.warning(self, "Аудио", f"Не удалось запустить аудио: {e}")

    def _open_call_window(self, peer_login: str):
        def on_end_call():
            try:
                t = NetworkThread("127.0.0.1", 5555, {
                    "action": "end_call",
                    "login": self.ctx.login,
                    "with_user": peer_login
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
        info_t = NetworkThread("127.0.0.1", 5555, {"action": "find_user", "login": peer_login})
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
            if hasattr(self, "call_events_timer") and self.call_events_timer.isActive():
                self.call_events_timer.stop()
        except Exception:
            pass

        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass

        try:
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
        except Exception:
            pass

        try:
            if hasattr(self.friends_page, "timer"):
                self.friends_page.timer.stop()
        except Exception:
            pass

        # Остановить фоновые запросы страниц
        for page in (self.friends_page, self.chats_page, self.profile_page):
            try:
                page._alive = False
                if hasattr(page, "shutdown_requests"):
                    page.shutdown_requests(wait_ms=1000)
            except Exception:
                pass

        # Снять online-статус на сервере (коротко)
        try:
            if self.ctx.login:
                t = NetworkThread("127.0.0.1", 5555, {"action": "logout", "login": self.ctx.login})
                t.start()
                t.wait(500)
        except Exception:
            pass

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
        self.ctx = UserContext()

        # Обновляем профиль
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

        if full_reset:
            # Friends page reset
            try:
                self.friends_page.clear_list()
                self.friends_page._loading_friends = False
                self.friends_page._loading_requests = False
                self.friends_page._found_user = None
                self.friends_page.refresh()
                if hasattr(self.friends_page, "timer") and not self.friends_page.timer.isActive():
                    self.friends_page.timer.start(5000)
            except Exception:
                pass

            # Chats page reset
            try:
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
                self.chats_page.start_auto_update()  # подтянет unread + friends
            except Exception:
                pass

        # По умолчанию открываем друзей
        self.show_friends()



    def prepare_to_close_app(self):
        """
        Вызывается контейнером AppWindow при закрытии приложения.
        """
        try:
            if hasattr(self, "call_events_timer") and self.call_events_timer.isActive():
                self.call_events_timer.stop()
        except Exception:
            pass

        try:
            self.chats_page.stop_auto_update()
        except Exception:
            pass

        try:
            if self.voice_client:
                self.voice_client.stop()
                self.voice_client = None
        except Exception:
            pass
        try:
            if hasattr(self.friends_page, "timer"):
                self.friends_page.timer.stop()
        except Exception:
            pass

        for page in (self.friends_page, self.chats_page, self.profile_page):
            try:
                page._alive = False
                if hasattr(page, "shutdown_requests"):
                    page.shutdown_requests(wait_ms=1200)
            except Exception:
                pass

