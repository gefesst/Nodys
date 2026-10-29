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
    outer.setSpacing(80)
    hero = QVBoxLayout()
    hero.setSpacing(0)
    hero.addStretch(1)
    hero.addSpacing(5)
    words = QLabel('Свои люди.<br><span style="color:#91ADFF">Рядом в Nodus.</span>')
    words.setObjectName("AuthHero")
    words.setStyleSheet("font-size:48px;font-weight:700;")
    words.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    hero.addWidget(words)
    hero.addSpacing(32)
    tagline = QLabel("Разговоры, которые хочется продолжать.")
    tagline.setObjectName("AuthSubtitle")
    tagline.setStyleSheet("font-size:18px;")
    tagline.setWordWrap(True)
    hero.addWidget(tagline)
    hero.addStretch(4)
    outer.addLayout(hero, 1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFixedWidth(500)
    scroll.setMaximumHeight(680)
    card = QFrame()
    card.setObjectName("AuthCard")
    card.setMinimumHeight(680)
    form = QVBoxLayout(card)
    form.setContentsMargins(41, 39, 41, 56)
    form.setSpacing(0)
    brand = QSvgWidget(str(ASSETS / "n.svg"))
    brand.setFixedSize(30, 30)
    form.addWidget(brand)
    form.addSpacing(20)
    heading = QLabel(title)
    heading.setObjectName("AuthTitle")
    heading.setFixedHeight(35)
    heading.setStyleSheet("font-size:29px;font-weight:700;")
    form.addWidget(heading)
    form.addSpacing(12)
    caption = QLabel(subtitle)
    caption.setObjectName("Muted")
    caption.setFixedHeight(17)
    caption.setStyleSheet("font-size:14px;color:#ACB9CC;")
    form.addWidget(caption)
    form.addSpacing(28)
    scroll.setWidget(card)
    outer.addWidget(scroll)

    class FitAuth(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Resize:
                fraction = max(0, min(1, (page.width() - 1120) / 320))
                left = round(40 + 150 * fraction)
                right = round(40 + 97 * fraction)
                outer.setSpacing(round(40 + 40 * fraction))
                top = max(20, min(92, (page.height() - 680) // 2 + 3))
                outer.setContentsMargins(left, top, right, max(20, top - 6))
            return False

    page._fit_auth = FitAuth(page)
    page.installEventFilter(page._fit_auth)
    return form


def finish_auth_layout(form, status, primary, secondary, registration=False):
    # Every field consumes 92px, including its trailing inter-field spacing.
    if not registration:
        form.addSpacing(92)
    form.addSpacing(11)
    status.setMinimumHeight(17)
    status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    form.addWidget(status)
    form.addSpacing(31)
    primary.setFixedHeight(40)
    form.addWidget(primary)
    form.addSpacing(27)
    secondary.setFixedHeight(40)
    secondary.setProperty("flat", True)
    form.addWidget(secondary)
    form.addStretch()


def field(form, title, password=False):
    label = QLabel(title)
    label.setObjectName("FieldTitle")
    label.setFixedHeight(17)
    form.addWidget(label)
    form.addSpacing(12)
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
    edit.setFixedHeight(46)
    edit.setStyleSheet("min-height:22px;max-height:22px;")
    form.addWidget(edit)
    form.addSpacing(17)
    return edit
