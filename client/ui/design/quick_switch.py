"""Keyboard navigation over real loaded contacts and channels."""

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QStandardItemModel, QStandardItem, QPainter, QColor
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from .widgets import avatar, draw_text, font
from .tokens import FG, SUB
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QListView,
    QLabel,
)


from .overlay import OverlayDialog


class QuickDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(722, 87)

    def paint(self, painter, option, index):
        row = index.data(Qt.UserRole)
        if not row:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(0, 0, 0, -12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(
            QColor("#2E425F" if option.state & QStyle.State_Selected else "#202D3F")
        )
        painter.drawRoundedRect(r, 10, 10)
        name = row.get("nickname") or row.get("name") or row.get("login", "")
        initials = "".join(part[0] for part in name.split()[:2])
        avatar(painter, r.x() + 19, r.y() + 17, initials, 40, bool(row.get("online")))
        painter.setFont(font(16, True))
        name = painter.fontMetrics().elidedText(
            name, Qt.ElideRight, int(r.width() - 100)
        )
        draw_text(painter, r.x() + 77, r.y() + 29, name, 16, FG, True)
        subtitle = (
            (
                "@"
                + row["login"]
                + " · "
                + ("В сети" if row.get("online") else "Не в сети")
            )
            if row.get("login")
            else "Канал"
        )
        draw_text(painter, r.x() + 77, r.y() + 53, subtitle, 13, SUB)
        painter.restore()


class QuickSwitch(OverlayDialog):
    def __init__(self, main):
        super().__init__(main, 750, 490, anchor="quick")
        self.main = main
        self.setWindowTitle("Быстрый переход")
        self.setStyleSheet(
            "QDialog#OverlayDialog {background:#202D3F;border:1px solid #4A5D7B;border-radius:16px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 20, 14, 44)
        root.setSpacing(12)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Имя друга или название канала")
        self.query.setFixedHeight(54)
        root.addWidget(self.query)
        heading = QLabel("ДИАЛОГИ И КАНАЛЫ")
        heading.setObjectName("Muted")
        heading.setFixedHeight(30)
        root.addWidget(heading)
        self.list = QListView()
        self.model = QStandardItemModel(self)
        self.list.setModel(self.model)
        self.list.setItemDelegate(QuickDelegate(self.list))
        self.list.setStyleSheet(
            "QListView::item {padding:12px;} QListView::item:selected {background:#2B3B51;}"
        )
        root.addWidget(self.list)
        self.hint = QLabel("Enter — открыть · Esc — закрыть")
        root.addWidget(self.hint)
        self.query.textChanged.connect(self.filter)
        self.query.returnPressed.connect(self.open_selected)
        self.list.activated.connect(self.open_selected)
        self.filter("")
        self.query.setFocus()

    def filter(self, text):
        self.targets = []
        labels = []
        contacts = getattr(self.main.friends_page, "_friends_data", [])
        channels = self.main.channels_page.channels
        for kind, rows in [("chat", contacts), ("channel", channels)]:
            for row in rows:
                name = row.get("nickname") or row.get("name") or row.get("login", "")
                if (
                    text.casefold()
                    not in (name + " " + row.get("login", "")).casefold()
                ):
                    continue
                labels.append(("Чат · " if kind == "chat" else "Канал · ") + name)
                self.targets.append((kind, dict(row)))
        self.model.clear()
        for label, (_, row) in zip(labels, self.targets):
            item = QStandardItem(label)
            item.setData(row, Qt.UserRole)
            item.setEditable(False)
            self.model.appendRow(item)
        self.list.setCurrentIndex(self.model.index(0, 0))
        self.hint.setText(
            "Enter — открыть · Esc — закрыть" if self.targets else "Совпадений нет"
        )

    def open_selected(self, *_):
        index = self.list.currentIndex()
        if not index.isValid() or not 0 <= index.row() < len(self.targets):
            return
        kind, row = self.targets[index.row()]
        if kind == "chat":
            self.main.show_chats()
            self.main.chats_page.open_chat(row)
        else:
            self.main.show_channels()
            self.main.channels_page.open_channel(row)
        self.accept()
