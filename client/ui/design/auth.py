"""Shared authentication composition; forms remain connected to real handlers."""

from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QWidget,
    QLineEdit,
    QSizePolicy,
)
from PySide6.QtSvgWidgets import QSvgWidget
from .widgets import ASSETS


def build_auth_layout(page, title, subtitle):
    outer = QHBoxLayout(page)
    outer.setContentsMargins(100, 80, 100, 64)
    outer.setSpacing(80)
    hero = QVBoxLayout()
    hero.setSpacing(12)
    hero.addStretch()
    words = QLabel('Свои люди.<br><span style="color:#91ADFF">Рядом в Nodus.</span>')
    words.setObjectName("AuthHero")
    words.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed)
    hero.addWidget(words)
    tagline = QLabel("Разговоры, которые хочется продолжать.")
    tagline.setObjectName("AuthSubtitle")
    tagline.setWordWrap(True)
    tagline.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed)
    hero.addWidget(tagline)
    illustration = QSvgWidget(str(ASSETS / "illustration-chat.svg"))
    illustration.setFixedSize(300, 180)
    hero.addSpacing(30)
    hero.addWidget(illustration, 0, Qt.AlignHCenter)
    hero.addStretch()
    outer.addLayout(hero, 1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setMinimumWidth(380)
    scroll.setMaximumWidth(500)
    scroll.setMaximumHeight(680)
    card = QFrame()
    card.setObjectName("AuthCard")
    form = QVBoxLayout(card)
    form.setContentsMargins(34, 30, 34, 30)
    form.setSpacing(14)
    brand = QLabel("N")
    brand.setObjectName("PageTitle")
    form.addWidget(brand)
    heading = QLabel(title)
    heading.setObjectName("AuthTitle")
    form.addWidget(heading)
    caption = QLabel(subtitle)
    caption.setObjectName("Muted")
    caption.setWordWrap(True)
    form.addWidget(caption)
    form.addSpacing(12)
    scroll.setWidget(card)
    outer.addWidget(scroll, 1)
    class FitAuth(QObject):
        def eventFilter(self, obj, event):
            if event.type()==QEvent.Resize:
                margin=max(24,min(80,(page.height()-520)//2))
                outer.setContentsMargins(80,margin,80,margin)
                form.setSpacing(8 if page.height()<700 else 14)
            return False
    page._fit_auth=FitAuth(page);page.installEventFilter(page._fit_auth)
    return form


def field(form, title, password=False):
    label = QLabel(title)
    label.setObjectName("FieldTitle")
    form.addWidget(label)
    edit = QLineEdit()
    edit.setAccessibleName(title)
    edit.setPlaceholderText(title)
    if password:
        edit.setEchoMode(QLineEdit.Password)
        action = edit.addAction(
            QIcon(str(ASSETS / "eye.svg")), QLineEdit.TrailingPosition
        )
        action.setToolTip("Показать или скрыть пароль")
        action.triggered.connect(
            lambda: edit.setEchoMode(
                QLineEdit.Normal
                if edit.echoMode() == QLineEdit.Password
                else QLineEdit.Password
            )
        )
    form.addWidget(edit)
    return edit
