from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication, QSizeGrip
from PySide6.QtCore import Qt, Slot, QTimer, QEvent, QPoint, QRect
from network import NetworkThread
from PySide6.QtGui import QIcon, QPainter, QColor, QPainterPath
from ui.design.shell import TitleBar, create_resize_handles, position_resize_handles
from ui.design.tokens import BACKGROUND_ALPHA, BACKGROUND
import os

from auth_window import AuthWindow
from register_window import RegisterWindow
from ui.main_window import MainWindow
from config import load_config, save_config, clear_config
from user_context import UserContext

from ui.design.motion import TransitionStack as QStackedWidget


class AppWindow(QWidget):
    """
    Single-window контейнер приложения.
    Все экраны внутри одного QStackedWidget.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("noda")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        available = self.screen().availableGeometry()
        self.resize(min(1280, available.width() - 80), min(800, available.height() - 80))
        self.move(available.center() - self.rect().center())
        self.setProperty('translucent_background',load_config().get('translucent_background',True))
        # Стартовый минимум: шире, но чуть ниже по высоте.
        self.setMinimumSize(1120, 620)

        # Иконка
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        from application.logout_outbox import retry_pending
        retry_pending()
        self._logout_retry_timer = QTimer(self)
        self._logout_retry_timer.setInterval(30000)
        self._logout_retry_timer.timeout.connect(retry_pending)
        self._logout_retry_timer.start()
        self.ctx = UserContext()
        self._resume_token = None
        self._resume_thread = None
        self._closing = False
        self._startup_barrier = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(TitleBar(self))

        self.stack = QStackedWidget(self)
        root.addWidget(self.stack)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16,16)
        self.resize_handles = create_resize_handles(self)

        # Создаем auth/register сразу, а MainWindow — лениво после успешной авторизации.
        # Это убирает фоновую активность (таймеры/запросы) до логина.
        self.auth_page = AuthWindow()
        self.register_page = RegisterWindow()
        self.main_page = None

        self.stack.addWidget(self.auth_page)
        self.stack.addWidget(self.register_page)

        # Колбэки навигации
        self.auth_page.on_login_success = self.show_main
        self.auth_page.on_open_register = self.show_register

        self.register_page.on_registered = self.show_auth
        self.register_page.on_back = self.show_auth

        # Стартовый экран: стараемся восстановить сессию по токену
        cfg = load_config()
        token = cfg.get("token") or ""

        # При отсутствии токена оставляем пользователя на экране входа
        # (так мы не храним пароль в конфиге).
        if not token:
            if cfg.get("login"):
                try:
                    self.auth_page.login.setText(cfg.get("login", ""))
                except Exception:
                    pass
            self.show_auth()
            return

        from ui.design.startup import StartupPage
        self.resume_page = StartupPage(self._cancel_resume)
        self.stack.addWidget(self.resume_page)
        self.stack.setCurrentWidget(self.resume_page)
        self._resume_token = token
        self._resume_thread = NetworkThread(None, None, {"action":"resume_session", "token":token})
        self._resume_thread.finished.connect(self._handle_resume_response, Qt.QueuedConnection)
        self._resume_thread.start()

    def showEvent(self, event):
        super().showEvent(event)
        from ui.design.window_shape import apply
        apply(self)
        if not hasattr(self, "backdrop_description"):
            from ui.design.backdrop import install
            QTimer.singleShot(0, lambda: install(self))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            from ui.design.window_shape import apply
            apply(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        color = QColor(BACKGROUND)
        color.setAlpha(BACKGROUND_ALPHA if self.property('translucent_background') is not False else 255)
        from ui.design.window_shape import RADIUS
        from PySide6.QtCore import QRectF
        outline=QPainterPath()
        if self.isMaximized() or self.isFullScreen():outline.addRect(QRectF(self.rect()))
        else:outline.addRoundedRect(QRectF(self.rect()),RADIUS,RADIUS)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPath(outline)
        # Each structural surface replaces the base, rather than stacking alpha
        # over it (96% over 96% is effectively opaque).
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        colors = {"Sidebar": "#19222D", "SectionSidebar": "#202B36",
                  "ChannelsSidebarCard": "#202B36"}
        for child in self.findChildren(QWidget):
            shade = colors.get(child.objectName())
            if isinstance(child, TitleBar):
                shade = "#1B2430"
            if shade and child.isVisibleTo(self):
                panel = QColor(shade)
                panel.setAlpha(color.alpha())
                region=QPainterPath()
                region.addRect(QRectF(QRect(child.mapTo(self, QPoint()), child.size())))
                painter.setBrush(panel)
                painter.drawPath(outline.intersected(region))

    def resizeEvent(self, event):
        if hasattr(self, 'grip'):
            self.grip.move(self.width()-18,self.height()-18)
            self.grip.raise_()
        if hasattr(self, "resize_handles"):
            position_resize_handles(self)
        from ui.design.window_shape import apply
        apply(self)
        super().resizeEvent(event)

    def _cancel_resume(self):
        self._resume_token = None
        if self._resume_thread:
            self._resume_thread.abort()
        self.show_auth()

    @Slot(dict)
    def _handle_resume_response(self, resp):
        token = self._resume_token
        cfg = load_config()
        if self._closing or not token or cfg.get("token") != token:
            return
        self._resume_token = None
        if resp.get("status") == "ok":
            login = resp.get("login", "")
            nickname = resp.get("nickname", "")
            avatar = resp.get("avatar", "")
            expires_at = resp.get("expires_at", cfg.get("token_expires_at", ""))
            self.ctx.set_user(login=login, nickname=nickname, avatar=avatar, session_token=token, token_expires_at=expires_at)
            save_config({
                "login": login,
                "nickname": nickname,
                "avatar": avatar,
                "token": token,
                "token_expires_at": expires_at,
                # при желании можно переопределить endpoints: api_host/api_port/voice_host/voice_port
            })
            self.show_main()
        else:
            # Preserve credentials on transient network failures.
            try:
                if resp.get("code") == "session_invalid":
                    clear_config()
            except Exception:
                pass
            self.show_auth()

    def _ensure_main_page(self):
        if self.main_page is None:
            self.main_page = MainWindow(controller=self)
            self.stack.addWidget(self.main_page)

    def show_auth(self):
        if self._startup_barrier:
            self._startup_barrier.cancel()
        self.stack.setCurrentWidget(self.auth_page)

    def show_register(self):
        self.stack.setCurrentWidget(self.register_page)

    def show_main(self):
        from application.startup_barrier import StartupBarrier
        from ui.design.startup import StartupPage
        self._resume_token = None
        if self._startup_barrier:
            self._startup_barrier.cancel()
        if not hasattr(self, 'resume_page'):
            self.resume_page = StartupPage(self._cancel_resume)
            self.stack.addWidget(self.resume_page)
        self.resume_page.set_status('Подготавливаем переписки и каналы…')
        self.stack.setCurrentWidget(self.resume_page)
        self._ensure_main_page()
        barrier = self._startup_barrier = StartupBarrier(self)
        token = self.ctx.session_token
        for page in (self.main_page.friends_page, self.main_page.chats_page,
                     self.main_page.channels_page):
            page.startup_barrier = barrier

        def current():
            return (not self._closing and self._startup_barrier is barrier
                    and self.ctx.session_token == token
                    and self.stack.currentWidget() is self.resume_page)

        def ready():
            if not current():
                return
            self.main_page.layout().activate()
            self.stack.setCurrentWidget(self.main_page)
            from application.qt_runtime import present_window
            present_window(self)
            print('noda startup: initial data ready; main presented', flush=True)

        def failed(message):
            if current():
                self.resume_page.set_status(message, self.show_main)
                print('noda startup: preparation failed; retry available', flush=True)

        barrier.ready.connect(ready)
        barrier.failed.connect(failed)
        print('noda startup: preparing initial data', flush=True)
        self.main_page.reload_from_context(full_reset=True)
        self.main_page.friends_page.ensure_initial_load()
        self.main_page.channels_page.load_channel_invites(force=True)
        barrier.seal()

    def logout_to_auth(self):
        # Вызывается из MainWindow/ProfilePage
        self.show_auth()

    def closeEvent(self, event):
        self._closing = True
        if self._startup_barrier:
            self._startup_barrier.cancel()
        self._resume_token = None
        if self._resume_thread:
            self._resume_thread.abort()
        for page in (self.auth_page, self.register_page):
            request = getattr(page, "thread", None)
            if request:
                request.abort()
        # Корректно закрыть внутреннюю main-страницу (остановка таймеров/потоков)
        try:
            if self.main_page is not None:
                self.main_page.prepare_to_close_app()
        except Exception:
            pass
        app = QApplication.instance()
        if app:
            app.quit()
        event.accept()
