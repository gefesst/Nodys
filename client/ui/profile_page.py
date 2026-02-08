import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from config import load_config, save_config, clear_config
from utils.thread_safe_mixin import ThreadSafeMixin


class ProfilePage(QWidget, ThreadSafeMixin):
    def __init__(self, login, nickname, parent_window=None):
        super().__init__(parent_window)
        self.login = login or ""
        self.nickname = nickname or ""
        self.parent_window = parent_window

        self.avatar_path = ""
        self._threads = []
        self._alive = True

        self._build_ui()
        self._load_initial_avatar()

    def _build_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(14)
        self.layout.setContentsMargins(30, 30, 30, 30)

        self.setStyleSheet("background-color:#36393f; color:white; border-radius:10px;")

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(110, 110)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setStyleSheet("border-radius:55px; border:2px solid #5865F2; background:#2f3136;")
        self.layout.addWidget(self.avatar_label, alignment=Qt.AlignHCenter)

        self.status_label = QLabel("● Offline")
        self.status_label.setStyleSheet("color:#f04747; font-weight:bold;")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.status_label)

        self.nickname_edit = QLineEdit(self.nickname)
        self.nickname_edit.setPlaceholderText("Никнейм")
        self.nickname_edit.setStyleSheet(self.lineedit_style())
        self.layout.addWidget(self.nickname_edit)

        self.login_label = QLabel(f"Логин: {self.login}")
        self.login_label.setStyleSheet("color:#b9bbbe;")
        self.layout.addWidget(self.login_label)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Новый пароль (необязательно)")
        self.password_edit.setStyleSheet(self.lineedit_style())
        self.layout.addWidget(self.password_edit)

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

    def _load_initial_avatar(self):
        cfg = load_config()
        self.avatar_path = cfg.get("avatar", "") or ""

        if not self.avatar_path:
            for ext in (".png", ".jpg", ".jpeg"):
                p = os.path.join("avatars", f"{self.login}{ext}")
                if os.path.exists(p):
                    self.avatar_path = p
                    break

        self._apply_avatar(self.avatar_path)

    def _apply_avatar(self, path: str):
        if path and os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self.avatar_label.setPixmap(
                    pix.scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        self.avatar_label.setPixmap(QPixmap())

    def choose_avatar(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите аватар", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.avatar_path = path
            self._apply_avatar(path)

    def save_changes(self):
        nickname = self.nickname_edit.text().strip()
        if not nickname:
            QMessageBox.warning(self, "Ошибка", "Никнейм не может быть пустым")
            return

        data = {
            "action": "update_profile",
            "login": self.login,
            "nickname": nickname,
            "password": self.password_edit.text().strip(),
            "avatar": self.avatar_path
        }

        self.start_request(data, self.handle_save)

    def handle_save(self, resp):
        if resp.get("status") == "ok":
            self.nickname = self.nickname_edit.text().strip()
            cfg = load_config()
            cfg["login"] = self.login
            cfg["nickname"] = self.nickname
            cfg["avatar"] = self.avatar_path or cfg.get("avatar", "")
            save_config(cfg)

            QMessageBox.information(self, "Готово", "Профиль обновлён")
            self.password_edit.clear()
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

    def closeEvent(self, event):
        self._alive = False
        self.shutdown_requests(wait_ms=3000)
        super().closeEvent(event)
