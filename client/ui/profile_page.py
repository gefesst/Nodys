import os
import shutil

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from network import NetworkThread
from config import clear_config, load_config, save_config
from user_context import UserContext


class ProfilePage(QWidget):
    def __init__(self, login: str, nickname: str, parent_window=None):
        super().__init__(parent_window)

        self.login = login
        self.nickname = nickname
        self.parent_window = parent_window
        self.avatar_path = ""

        # ---------------- Layout ----------------
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(15)
        self.setLayout(self.layout)

        # ---------------- Avatar ----------------
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(100, 100)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setStyleSheet("""
            QLabel {
                border-radius: 50px;
                border: 2px solid #5865F2;
                background-color: #202225;
            }
        """)
        self.layout.addWidget(self.avatar_label, alignment=Qt.AlignHCenter)

        # ---------------- Status ----------------
        self.status_label = QLabel("● Offline")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color:#f04747; font-weight:bold;")
        self.layout.addWidget(self.status_label)

        # ---------------- Nickname ----------------
        self.nickname_edit = QLineEdit(nickname)
        self.nickname_edit.setPlaceholderText("Никнейм")
        self.nickname_edit.setStyleSheet(self.input_style())
        self.layout.addWidget(self.nickname_edit)

        # ---------------- Login ----------------
        self.login_label = QLabel(f"Логин: {login}")
        self.login_label.setStyleSheet("color:#b9bbbe;")
        self.layout.addWidget(self.login_label)

        # ---------------- Password ----------------
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Новый пароль")
        self.password_edit.setStyleSheet(self.input_style())
        self.layout.addWidget(self.password_edit)

        # ---------------- Buttons ----------------
        self.btn_avatar = QPushButton("Изменить аватар")
        self.btn_avatar.setStyleSheet(self.button_style())
        self.btn_avatar.clicked.connect(self.choose_avatar)
        self.layout.addWidget(self.btn_avatar)

        self.btn_save = QPushButton("Сохранить изменения")
        self.btn_save.setStyleSheet(self.button_style())
        self.btn_save.clicked.connect(self.save_changes)
        self.layout.addWidget(self.btn_save)

        self.btn_logout = QPushButton("Выйти из аккаунта")
        self.btn_logout.setStyleSheet(self.button_style())
        self.btn_logout.clicked.connect(self.logout)
        self.layout.addWidget(self.btn_logout)

        self.layout.addStretch()

        # ---------------- Page style ----------------
        self.setStyleSheet("""
            QWidget {
                background-color: #36393f;
                color: white;
                border-radius: 10px;
            }
        """)

        # ---------------- Load avatar if exists ----------------
        self.load_avatar()

    # ==================================================
    # ===================== STYLES =====================
    # ==================================================

    def input_style(self):
        return """
            QLineEdit {
                background-color:#202225;
                border:1px solid #2f3136;
                border-radius:6px;
                padding:6px;
                color:white;
            }
        """

    def button_style(self):
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
    # ===================== LOGIC ======================
    # ==================================================

    def update_status(self, online: bool):
        if online:
            self.status_label.setText("● Online")
            self.status_label.setStyleSheet("color:#43b581; font-weight:bold;")
        else:
            self.status_label.setText("● Offline")
            self.status_label.setStyleSheet("color:#f04747; font-weight:bold;")

    def load_avatar(self):
        if not os.path.exists("avatars"):
            return

        for ext in (".png", ".jpg", ".jpeg"):
            path = os.path.join("avatars", f"{self.login}{ext}")
            if os.path.exists(path):
                self.avatar_path = path
                pixmap = QPixmap(path).scaled(
                    100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.avatar_label.setPixmap(pixmap)
                break

    def choose_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите аватар", "", "Images (*.png *.jpg *.jpeg)"
        )
        if not path:
            return

        os.makedirs("avatars", exist_ok=True)

        ext = os.path.splitext(path)[1]
        new_path = os.path.join("avatars", f"{self.login}{ext}")

        shutil.copy(path, new_path)
        self.avatar_path = new_path

        pixmap = QPixmap(new_path).scaled(
            100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.avatar_label.setPixmap(pixmap)

    def save_changes(self):
        nickname = self.nickname_edit.text().strip()
        if not nickname:
            QMessageBox.warning(self, "Ошибка", "Никнейм не может быть пустым")
            return

        data = {
            "action": "update_profile",
            "login": self.login,
            "nickname": nickname,
            "password": self.password_edit.text(),
            "avatar": self.avatar_path
        }

        self.thread = NetworkThread("127.0.0.1", 5555, data)
        self.thread.finished.connect(self.handle_save)
        self.thread.start()

    def handle_save(self, resp):
        if resp.get("status") == "ok":
            QMessageBox.information(self, "Готово", "Профиль обновлён")

            new_nickname = self.nickname_edit.text().strip()
            self.nickname = new_nickname

            # 1) обновляем контекст
            ctx = UserContext()
            ctx.nickname = new_nickname
            ctx.avatar_path = self.avatar_path

            # 2) обновляем config.json (чтобы автологин был актуальным)
            cfg = load_config()
            if cfg.get("login") == self.login:
                cfg["logged_in"] = True
                cfg["login"] = self.login
                cfg["nickname"] = new_nickname
                cfg["avatar"] = self.avatar_path
                save_config(cfg)

        else:
            clear_config()
            QMessageBox.warning(self, "Ошибка", "Сессия устарела, войдите снова")
            self.parent_window.show_login()

    def logout(self):
        self.thread = NetworkThread(
            "127.0.0.1", 5555,
            {"action": "logout", "login": self.login}
        )
        self.thread.finished.connect(self.on_logout_finished)
        self.thread.start()

    def on_logout_finished(self, resp):
        clear_config()
        self.parent_window.show_login()
