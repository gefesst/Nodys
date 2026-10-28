"""Keyboard navigation over real loaded contacts and channels."""

from PySide6.QtCore import QStringListModel
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QListView,
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
        self.list = QListView()
        self.model = QStringListModel(self)
        self.list.setModel(self.model)
        self.list.setStyleSheet("QListView::item {padding:12px;} QListView::item:selected {background:#2B3B51;}")
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
                labels.append(('Чат · ' if kind == 'chat' else 'Канал · ') + name)
                self.targets.append((kind, dict(row)))
        self.model.setStringList(labels)
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
