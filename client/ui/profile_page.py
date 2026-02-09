import os
import shutil

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt

from config import load_config, save_config, clear_config
from utils.thread_safe_mixin import ThreadSafeMixin
from ui.avatar_widget import AvatarLabel


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
        self.layout.setSpacing(14)
        self.layout.setContentsMargins(30, 30, 30, 30)

        self.setStyleSheet("background-color:#36393f; color:white; border-radius:10px;")

        # Аватар
        self.avatar_label = AvatarLabel(size=110)
        self.layout.addWidget(self.avatar_label, alignment=Qt.AlignHCenter)

        # Статус
        self.status_label = QLabel("● Offline")
        self.status_label.setStyleSheet("color:#f04747; font-weight:bold;")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.status_label)

        # Ник
        self.nickname_edit = QLineEdit(self.nickname)
        self.nickname_edit.setPlaceholderText("Никнейм")
        self.nickname_edit.setStyleSheet(self.lineedit_style())
        self.layout.addWidget(self.nickname_edit)

        # Логин
        self.login_label = QLabel(f"Логин: {self.login}")
        self.login_label.setStyleSheet("color:#b9bbbe;")
        self.layout.addWidget(self.login_label)

        # Пароль
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Новый пароль (необязательно)")
        self.password_edit.setStyleSheet(self.lineedit_style())
        self.layout.addWidget(self.password_edit)

        # Кнопки
        btn_avatar = QPushButton("Изменить аватар")
        btn_avatar.setStyleSheet(self.button_style())
        btn_avatar.clicked.connect(self.choose_avatar)
        self.layout.addWidget(btn_avatar)

        btn_save = QPushButton("Сохранить изменения")
        btn_save.setStyleSheet(self.button_style())
        btn_save.clicked.connect(self.save_changes)
        self.layout.addWidget(btn_save)

        btn_logout = QPushButton("Выйти из аккаунта")
        btn_logout.setStyleSheet(self.button_style(danger=True))
        btn_logout.clicked.connect(self.logout)
        self.layout.addWidget(btn_logout)

        self.layout.addStretch()

    def lineedit_style(self):
        return """
            QLineEdit {
                background-color:#202225;
                border:1px solid #2f3136;
                border-radius:6px;
                padding:8px;
                color:white;
            }
            QLineEdit:focus {
                border:1px solid #5865F2;
            }
        """

    def button_style(self, danger=False):
        if danger:
            return """
                QPushButton {
                    background-color:#f04747;
                    border-radius:6px;
                    padding:8px;
                    color:white;
                }
                QPushButton:hover {
                    background-color:#d83c3c;
                }
            """
        return """
            QPushButton {
                background-color:#3c3f45;
                border-radius:6px;
                padding:8px;
                color:white;
            }
            QPushButton:hover {
                background-color:#5865F2;
            }
        """

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

    def _load_initial_profile_data(self):
        """
        Источник приоритета:
        1) config.json avatar
        2) fallback avatars/<login>.(png/jpg/jpeg)
        """
        cfg = load_config()

        # Ник из контекста окна приоритетный, но если пустой — берем из config
        if not self.nickname and cfg.get("nickname"):
            self.nickname = cfg.get("nickname", "")
            self.nickname_edit.setText(self.nickname)

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
            QMessageBox.warning(self, "Ошибка", "Никнейм не может быть пустым")
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

            QMessageBox.information(self, "Готово", "Профиль обновлён")
        else:
            QMessageBox.warning(self, "Ошибка", resp.get("message", "Не удалось обновить профиль"))

    def update_status(self, online: bool):
        if online:
            self.status_label.setText("● Online")
            self.status_label.setStyleSheet("color:#43b581; font-weight:bold;")
        else:
            self.status_label.setText("● Offline")
            self.status_label.setStyleSheet("color:#f04747; font-weight:bold;")

    def logout(self):
        data = {"action": "logout", "login": self.login}
        self.start_request(data, self.on_logout_finished)

    def on_logout_finished(self, _resp):
        clear_config()
        if self.parent_window:
            self.parent_window.show_login()

    # ==================================================
    # ==================== Lifecycle ===================
    # ==================================================

    def closeEvent(self, event):
        self._alive = False
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)
