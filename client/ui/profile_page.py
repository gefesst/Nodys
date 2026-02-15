import os
import shutil

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QFrame
)
from PySide6.QtCore import Qt

from config import load_config, save_config, clear_config
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel
from ui.toast import InlineToast
from user_context import UserContext


class ProfilePage(QWidget, ThreadSafeMixin):
    def __init__(self, login, nickname, parent_window=None):
        super().__init__(parent_window)

        self.login = login or ""
        self.nickname = nickname or ""
        self.parent_window = parent_window

        # Может быть абсолютным (после выбора файла) или относительным (avatars/xxx.jpg)
        self.avatar_path = ""

        # Для ThreadSafeMixin
        self._threads = []
        self._alive = True

        self._build_ui()
        self._load_initial_profile_data()

    # ==================================================
    # ===================== UI ==========================
    # ==================================================

    def _build_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(12)
        self.layout.setContentsMargins(18, 18, 18, 18)

        self.setObjectName("ProfilePage")

        # Внешняя карточка
        self.card = QFrame()
        self.card.setObjectName("ProfileCard")
        card_l = QVBoxLayout(self.card)
        card_l.setSpacing(12)
        card_l.setContentsMargins(20, 20, 20, 20)

        # Аватар
        self.avatar_label = AvatarLabel(size=110)
        card_l.addWidget(self.avatar_label, alignment=Qt.AlignHCenter)

        # Статус
        self.status_label = QLabel("● Offline")
        self.status_label.setObjectName("ProfileStatusOffline")
        self.status_label.setAlignment(Qt.AlignCenter)
        card_l.addWidget(self.status_label)

        # Логин
        self.login_title = QLabel("Логин")
        self.login_title.setObjectName("FieldTitle")
        card_l.addWidget(self.login_title)

        self.login_label = QLabel(self.login)
        self.login_label.setObjectName("ProfileLogin")
        card_l.addWidget(self.login_label)

        # Никнейм
        self.nick_title = QLabel("Никнейм")
        self.nick_title.setObjectName("FieldTitle")
        card_l.addWidget(self.nick_title)

        self.nickname_edit = QLineEdit(self.nickname)
        self.nickname_edit.setPlaceholderText("Никнейм")
        card_l.addWidget(self.nickname_edit)

        # Пароль
        self.pass_title = QLabel("Изменение пароля")
        self.pass_title.setObjectName("FieldTitle")
        card_l.addWidget(self.pass_title)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Новый пароль (необязательно)")
        card_l.addWidget(self.password_edit)

        # Кнопки
        btn_avatar = QPushButton("Изменить аватар")
        btn_avatar.setObjectName("ProfilePrimaryButton")
        btn_avatar.clicked.connect(self.choose_avatar)
        card_l.addWidget(btn_avatar)

        btn_save = QPushButton("Сохранить изменения")
        btn_save.setObjectName("ProfilePrimaryButton")
        btn_save.clicked.connect(self.save_changes)
        card_l.addWidget(btn_save)

        btn_logout = QPushButton("Выйти из аккаунта")
        btn_logout.setObjectName("ProfileDangerButton")
        btn_logout.clicked.connect(self.logout)
        card_l.addWidget(btn_logout)

        self.layout.addWidget(self.card)
        self.layout.addStretch()

        # toast-уведомления внутри страницы (единый компонент)
        self._toast = InlineToast(
            self,
            object_name="InlineToast",
            min_width=240,
            max_width=520,
            horizontal_margin=12,
            bottom_margin=14,
        )

    def _reposition_toast(self):
        if getattr(self, "_toast", None):
            self._toast.reposition()

    def show_toast(self, text: str, msec: int = 2600):
        if not text:
            return
        if getattr(self, "_toast", None):
            self._toast.show(text, max(900, int(msec)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_toast()

    # ==================================================
    # ================== Avatar logic ==================
    # ==================================================

    def _client_dir(self):
        # client/ui/profile_page.py -> client
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _avatars_dir(self):
        path = os.path.join(self._client_dir(), "avatars")
        os.makedirs(path, exist_ok=True)
        return path

    def _to_abs_avatar_path(self, path: str) -> str:
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        return os.path.join(self._client_dir(), path)

    def _normalize_avatar_to_project(self, source_path: str) -> str:
        """
        Копируем выбранный файл в client/avatars/<login>.<ext>
        Возвращаем относительный путь вида: avatars/<login>.<ext>
        """
        if not source_path or not os.path.exists(source_path):
            return ""

        ext = os.path.splitext(source_path)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg"):
            ext = ".jpg"

        dst_name = f"{self.login}{ext}"
        dst_abs = os.path.join(self._avatars_dir(), dst_name)

        try:
            shutil.copy2(source_path, dst_abs)
        except Exception:
            return ""

        return f"avatars/{dst_name}"

    def _apply_avatar(self, path: str):
        self.avatar_label.set_avatar(
            path=path,
            login=self.login,
            nickname=self.nickname_edit.text().strip() or self.nickname
        )

    def _sync_context_and_parent(self):
        """Синхронизировать ник/аватар после сохранения профиля без перезапуска окна."""
        try:
            ctx = UserContext()
            ctx.login = self.login or ctx.login
            ctx.nickname = self.nickname
            if self.avatar_path:
                ctx.avatar = self.avatar_path
        except Exception:
            pass

        pw = self.parent_window
        if pw is None:
            return

        try:
            if hasattr(pw, "ctx"):
                pw.ctx.login = self.login or getattr(pw.ctx, "login", "")
                pw.ctx.nickname = self.nickname
                if self.avatar_path:
                    pw.ctx.avatar = self.avatar_path
        except Exception:
            pass

        try:
            if hasattr(pw, "user_nick_lbl"):
                pw.user_nick_lbl.setText(self.nickname or "Гость")
            if hasattr(pw, "user_login_lbl"):
                pw.user_login_lbl.setText(self.login or "")
            if hasattr(pw, "user_avatar"):
                pw.user_avatar.set_avatar(
                    path=self.avatar_path,
                    login=self.login,
                    nickname=self.nickname,
                )
        except Exception:
            pass

    def set_user_data(self, login, nickname, avatar=""):
        """
        Обновляет страницу профиля после перелогина без пересоздания страницы.
        """
        self.login = login or ""
        self.nickname = nickname or ""
        self.avatar_path = avatar or ""

        try:
            self.login_label.setText(self.login or "—")
        except Exception:
            pass
        try:
            self.nickname_edit.setText(self.nickname)
            self.login_label.setText(self.login or "—")
        except Exception:
            pass
        try:
            self._apply_avatar(self.avatar_path)
        except Exception:
            pass

    def _load_initial_profile_data(self):
        """
        Источник приоритета:
        1) config.json avatar
        2) fallback avatars/<login>.(png/jpg/jpeg)
        """
        cfg = load_config()

        # Логин из контекста приоритетный, но если пустой — берем из config
        if (not self.login) and cfg.get("login"):
            self.login = cfg.get("login", "")
        self.login_label.setText(self.login or "—")

        # Ник из контекста окна приоритетный, но если пустой — берем из config
        if not self.nickname and cfg.get("nickname"):
            self.nickname = cfg.get("nickname", "")
            self.nickname_edit.setText(self.nickname)
            self.login_label.setText(self.login or "—")

        self.avatar_path = cfg.get("avatar", "") or ""

        if not self.avatar_path:
            for ext in (".png", ".jpg", ".jpeg"):
                rel = f"avatars/{self.login}{ext}"
                abs_p = self._to_abs_avatar_path(rel)
                if os.path.exists(abs_p):
                    self.avatar_path = rel
                    break

        self._apply_avatar(self.avatar_path)

    # ==================================================
    # ==================== Actions =====================
    # ==================================================

    def choose_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите аватар",
            "",
            "Images (*.png *.jpg *.jpeg)"
        )
        if not path:
            return

        self.avatar_path = path  # пока абсолютный путь (до сохранения)
        self._apply_avatar(self.avatar_path)

    def save_changes(self):
        nickname = self.nickname_edit.text().strip()
        if not nickname:
            self.show_toast("Никнейм не может быть пустым", msec=2800)
            return

        # Если выбран файл из проводника (абсолютный путь), копируем в client/avatars
        avatar_for_server = self.avatar_path
        if self.avatar_path and os.path.isabs(self.avatar_path):
            normalized = self._normalize_avatar_to_project(self.avatar_path)
            if normalized:
                self.avatar_path = normalized
                avatar_for_server = normalized

        data = {
            "action": "update_profile",
            "login": self.login,
            "nickname": nickname,
            "password": self.password_edit.text().strip(),  # можно пустым
            "avatar": avatar_for_server
        }

        self.start_request(data, self.handle_save_response)

    def handle_save_response(self, resp):
        if resp.get("status") == "ok":
            self.nickname = self.nickname_edit.text().strip()

            # Обновляем локальный config для автологина
            cfg = load_config()
            cfg["login"] = self.login
            cfg["nickname"] = self.nickname
            cfg["avatar"] = self.avatar_path or cfg.get("avatar", "")
            save_config(cfg)

            self._apply_avatar(self.avatar_path)
            self.password_edit.clear()

            # Важно: чтобы ник сразу обновился в мини-карточке слева (MainWindow)
            self._sync_context_and_parent()

            self.show_toast("Профиль обновлён")
        else:
            self.show_toast(resp.get("message", "Не удалось обновить профиль"), msec=3200)

    def update_status(self, online: bool):
        if online:
            self.status_label.setText("● Online")
            self.status_label.setObjectName("ProfileStatusOnline")
            self.status_label.style().unpolish(self.status_label); self.status_label.style().polish(self.status_label)
        else:
            self.status_label.setText("● Offline")
            self.status_label.setObjectName("ProfileStatusOffline")
            self.status_label.style().unpolish(self.status_label); self.status_label.style().polish(self.status_label)

    def logout(self):
        # Используем единый пайплайн логаута (останавливает таймеры/voice и чистит контекст)
        if self.parent_window and hasattr(self.parent_window, "perform_logout"):
            self.parent_window.perform_logout()
            return

        # Fallback (на всякий случай)
        data = {"action": "logout", "login": self.login}
        self.start_request(data, self.on_logout_finished)

    def on_logout_finished(self, _resp):
        clear_config()
        UserContext().clear()
        if self.parent_window:
            # для single-window контроллера
            if hasattr(self.parent_window, "controller") and self.parent_window.controller:
                self.parent_window.controller.logout_to_auth()
            else:
                self.parent_window.show_login()

    # ==================================================
    # ==================== Lifecycle ===================
    # ==================================================

    def closeEvent(self, event):
        self._alive = False
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)
