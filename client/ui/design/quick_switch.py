"""Keyboard navigation over real loaded contacts and channels."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QLabel,
)


class QuickSwitch(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Быстрый переход")
        self.resize(520, 420)
        root = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Имя друга или название канала")
        root.addWidget(self.query)
        self.list = QListWidget()
        root.addWidget(self.list)
        self.hint = QLabel("Enter — открыть · Esc — закрыть")
        root.addWidget(self.hint)
        self.query.textChanged.connect(self.filter)
        self.query.returnPressed.connect(self.open_selected)
        self.list.itemActivated.connect(self.open_selected)
        self.filter("")
        self.query.setFocus()

    def filter(self, text):
        self.list.clear()
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
                item = QListWidgetItem(
                    ("Чат · " if kind == "chat" else "Канал · ") + name
                )
                item.setData(Qt.UserRole, (kind, row))
                self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.hint.setText(
            "Enter — открыть · Esc — закрыть" if self.list.count() else "Совпадений нет"
        )

    def open_selected(self, *_):
        item = self.list.currentItem()
        if item is None:
            return
        kind, row = item.data(Qt.UserRole)
        if kind == "chat":
            self.main.show_chats()
            self.main.chats_page.open_chat(row)
        else:
            self.main.show_channels()
            self.main.channels_page.open_channel(row)
        self.accept()
