"""Keyboard navigation over real loaded contacts and channels."""

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QStandardItemModel, QStandardItem, QPainter, QColor
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from .widgets import avatar, draw_text, font, Button
from .tokens import FG, SUB
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QListView,
    QLabel,
    QHBoxLayout,
    QFrame,
    QStackedWidget,
    QWidget,
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
        root.setContentsMargins(20, 20, 20, 44)
        root.setSpacing(12)
        self.query = QLineEdit()
        self.query.setProperty("no_focus_ring",True)
        self.query.setPlaceholderText("Имя друга или название канала")
        self.query.setFixedHeight(54)
        header=QHBoxLayout();header.setSpacing(16)
        search_icon=Button('', 'search');search_icon.setProperty('flat',True);search_icon.setFixedWidth(24);search_icon.setFocusPolicy(Qt.NoFocus)
        search_icon.clicked.connect(self.query.setFocus);header.addWidget(search_icon)
        self.query.setStyleSheet('QLineEdit, QLineEdit:focus {border:0;background:transparent;font-size:19px;padding:0 4px;}')
        self.query.setAttribute(Qt.WA_MacShowFocusRect,False)
        self.query.installEventFilter(self)
        header.addWidget(self.query,1)
        escape=Button('Esc');escape.setFixedSize(48,30);escape.clicked.connect(self.reject);header.addWidget(escape)
        root.addLayout(header)
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
        self.results=QStackedWidget();self.results.addWidget(self.list)
        self.empty=QWidget();empty_layout=QVBoxLayout(self.empty);empty_layout.setContentsMargins(0,42,0,0);empty_layout.setSpacing(16)
        title=QLabel('Ничего не найдено');title.setAlignment(Qt.AlignCenter);title.setFixedHeight(28);title.setStyleSheet('font-size:23px;font-weight:600;');empty_layout.addWidget(title)
        subtitle=QLabel('Попробуйте имя, логин или название канала.');subtitle.setAlignment(Qt.AlignCenter);subtitle.setWordWrap(True);subtitle.setStyleSheet('font-size:14px;color:#ACB9CC;');empty_layout.addWidget(subtitle)
        empty_layout.addStretch();self.results.addWidget(self.empty)
        root.addWidget(self.results,1)
        self.hint = QLabel("Enter — открыть · Esc — закрыть")
        root.addWidget(self.hint)
        self.query.textChanged.connect(self.filter)
        self.query.returnPressed.connect(self.open_selected)
        self.list.activated.connect(self.open_selected)
        self.filter("")
        self.query.setFocus()

    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self);painter.setPen(QColor('#354152'))
        painter.drawLine(20,74,self.width()-20,74)

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
        self.results.setCurrentWidget(self.list if self.targets else self.empty)
        self.hint.setVisible(bool(self.targets))
        self.hint.setText(
            "Enter — открыть · Esc — закрыть" if self.targets else "Совпадений нет"
        )

    def eventFilter(self,watched,event):
        from PySide6.QtCore import QEvent
        if watched is self.query and event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Down,Qt.Key_Up):
            step=1 if event.key()==Qt.Key_Down else -1
            row=max(0,min(len(self.targets)-1,self.list.currentIndex().row()+step))
            self.list.setCurrentIndex(self.model.index(row,0))
            return True
        return super().eventFilter(watched,event)

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
