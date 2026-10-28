from application.avatars import encode_avatar
import os
import shutil

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QFrame, QHBoxLayout, QScrollArea
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
        from ui.design.tokens import LIST_WIDTH
        from ui.design.widgets import Button
        self.setObjectName('ProfilePage')
        outer=QHBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName('SectionSidebar');sidebar.setFixedWidth(LIST_WIDTH)
        side=QVBoxLayout(sidebar);side.setContentsMargins(20,30,20,20);side.setSpacing(10)
        eyebrow=QLabel('АККАУНТ');eyebrow.setObjectName('Eyebrow');side.addWidget(eyebrow)
        title=QLabel('Мой профиль');title.setObjectName('PageTitle');side.addWidget(title);side.addSpacing(14)
        self.profile_tabs={}
        for key,text in [('main','Профиль'),('edit','Редактирование'),('password','Пароль')]:
            button=QPushButton(text);button.setObjectName('SectionTab');button.setCheckable(True);button.clicked.connect(lambda checked=False,k=key:self.show_section(k));side.addWidget(button);self.profile_tabs[key]=button
        side.addStretch();logout=QPushButton('Выйти из аккаунта');logout.setObjectName('ProfileDangerButton');logout.clicked.connect(self.confirm_logout);side.addWidget(logout)
        outer.addWidget(sidebar)
        scroll=QScrollArea();scroll.setWidgetResizable(True);outer.addWidget(scroll,1)
        content=QWidget();scroll.setWidget(content);self.layout=QVBoxLayout(content);self.layout.setContentsMargins(40,30,40,30);self.layout.setSpacing(20)
        self.page_title=QLabel('Ваш профиль');self.page_title.setObjectName('PageTitle');self.layout.addWidget(self.page_title)
        subtitle=QLabel('Так вас видят друзья и участники каналов');subtitle.setObjectName('Muted');self.layout.addWidget(subtitle)
        divider=QFrame();divider.setObjectName('Divider');divider.setFixedHeight(1);self.layout.addWidget(divider)
        self.card=QFrame();self.card.setObjectName('ProfileForm');self.card.setMaximumWidth(840)
        card_l=QVBoxLayout(self.card);card_l.setContentsMargins(0,16,0,0);card_l.setSpacing(18)
        identity=QHBoxLayout();identity.setSpacing(18)
        self.avatar_label=AvatarLabel(size=80);identity.addWidget(self.avatar_label)
        names=QVBoxLayout();names.setSpacing(6)
        self.display_name=QLabel(self.nickname);self.display_name.setObjectName('FieldHeading');names.addWidget(self.display_name)
        self.status_label=QLabel('Не в сети');self.status_label.setObjectName('ProfileStatusOffline');names.addWidget(self.status_label)
        identity.addLayout(names,1)
        avatar=Button('Изменить аватар','profile');avatar.clicked.connect(self.choose_avatar);identity.addWidget(avatar)
        card_l.addLayout(identity);card_l.addSpacing(14)
        login_title=QLabel('Логин · нельзя изменить');login_title.setObjectName('FieldTitle');card_l.addWidget(login_title)
        self.login_label=QLabel(self.login);self.login_label.setObjectName('ReadOnlyField');card_l.addWidget(self.login_label)
        self.edit_block=QWidget();edit=QVBoxLayout(self.edit_block);edit.setContentsMargins(0,0,0,0);edit.setSpacing(10)
        self.nick_title=QLabel('Никнейм');self.nick_title.setObjectName('FieldTitle');edit.addWidget(self.nick_title)
        self.nickname_edit=QLineEdit(self.nickname);edit.addWidget(self.nickname_edit);card_l.addWidget(self.edit_block)
        self.password_block=QWidget();password=QHBoxLayout(self.password_block);password.setContentsMargins(0,0,0,0);password.setSpacing(16)
        self.current_password_edit=QLineEdit();self.current_password_edit.setEchoMode(QLineEdit.Password);self.current_password_edit.setPlaceholderText('Текущий пароль');password.addWidget(self.current_password_edit)
        self.password_edit=QLineEdit();self.password_edit.setEchoMode(QLineEdit.Password);self.password_edit.setPlaceholderText('Новый пароль');password.addWidget(self.password_edit);card_l.addWidget(self.password_block)
        self.edit_button=Button('Изменить пароль');self.edit_button.clicked.connect(lambda:self.show_section('password'));card_l.addWidget(self.edit_button,0,Qt.AlignLeft)
        card_l.addSpacing(12)
        self.save_button=Button('Сохранить изменения',primary=True);self.save_button.clicked.connect(self.save_changes);card_l.addWidget(self.save_button,0,Qt.AlignLeft)
        self.layout.addWidget(self.card);self.layout.addStretch()
        self._saving=False
        self.show_section('main')

        # toast-уведомления внутри страницы (единый компонент)
        self._toast = InlineToast(
            self,
            object_name="InlineToast",
            min_width=240,
            max_width=520,
            horizontal_margin=12,
            bottom_margin=14,
        )

    def show_section(self,key):
        self._profile_section = key
        for name,button in self.profile_tabs.items():button.setChecked(name==key)
        self.edit_block.setVisible(True);self.password_block.setVisible(key=='password')
        self.save_button.setVisible(True);self.edit_button.setVisible(key!='password')
        self.page_title.setText('Ваш профиль')

    def confirm_logout(self):
        from ui.design.dialogs import confirm
        confirm(self,'Выйти из аккаунта?','Текущий звонок будет завершён. Вы сможете войти снова.','Выйти',self.logout)

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
                pw.user_nick_lbl.setText("Вы")
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
        self.display_name.setText(self.nickname)
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

        try:
            self.avatar_path = encode_avatar(path)
        except ValueError as error:
            self.show_toast(str(error))
            return
        self._apply_avatar(self.avatar_path)

    def save_changes(self):
        if self._saving:return
        changing_password = getattr(self, "_profile_section", "edit") == "password"
        if changing_password and not self.password_edit.text():
            self.show_toast("Введите новый пароль", msec=2800)
            return
        nickname = self.nickname if changing_password else self.nickname_edit.text().strip()
        if not nickname:
            self.show_toast("Никнейм не может быть пустым", msec=2800)
            return

        # Если выбран файл из проводника (абсолютный путь), копируем в client/avatars
        avatar_for_server = getattr(getattr(self, "ctx", None), "avatar", "") if changing_password else self.avatar_path
        if not changing_password and self.avatar_path and os.path.isabs(self.avatar_path):
            normalized = self._normalize_avatar_to_project(self.avatar_path)
            if normalized:
                self.avatar_path = normalized
                avatar_for_server = normalized

        data = {
            "action": "update_profile",
            "login": self.login,
            "nickname": nickname,
            "password": self.password_edit.text() if changing_password else "",
            "current_password": self.current_password_edit.text() if changing_password else "",
            "avatar": avatar_for_server
        }

        self.edit_block.setEnabled(False)
        self.password_block.setEnabled(False)
        self._saving=True
        self.save_button.setEnabled(False)
        self.save_button.setText('Сохраняем…')
        self._submitted_profile=dict(data)
        self.start_request(data, self.handle_save_response)

    def handle_save_response(self, resp):
        self.edit_block.setEnabled(True)
        self.password_block.setEnabled(True)
        self._saving=False
        self.save_button.setEnabled(True)
        self.save_button.setText('Сохранить изменения')
        if resp.get("status") == "ok":
            self.nickname = getattr(self,'_submitted_profile',{}).get('nickname',self.nickname_edit.text().strip())
            self.avatar_path = self._submitted_profile.get("avatar", self.avatar_path)
            self.display_name.setText(self.nickname)

            # Обновляем локальный config для автологина
            cfg = load_config()
            cfg["login"] = self.login
            cfg["nickname"] = self.nickname
            cfg["avatar"] = self.avatar_path or cfg.get("avatar", "")
            save_config(cfg)

            self._apply_avatar(self.avatar_path)
            self.password_edit.clear()
            self.current_password_edit.clear()

            # Важно: чтобы ник сразу обновился в мини-карточке слева (MainWindow)
            self._sync_context_and_parent()

            self.show_toast("Профиль обновлён")
        else:
            self.show_toast(resp.get("message", "Не удалось обновить профиль"), msec=3200)

    def update_status(self, online: bool):
        if online:
            self.status_label.setText("В сети")
            self.status_label.setObjectName("ProfileStatusOnline")
            self.status_label.style().unpolish(self.status_label); self.status_label.style().polish(self.status_label)
        else:
            self.status_label.setText("Не в сети")
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
