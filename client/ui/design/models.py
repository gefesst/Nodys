"""Data-only models; no QWidget is allocated for an individual message."""

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    id: int
    author: str
    name: str
    text: str
    time: str = ""
    read: bool = False
    group: bool = True
    date: str = ""
    divider: bool = False
    unread_count: int = 0
    avatar: str = ""
    attachment: object = None
    link_text: str | None = None
    edited: bool = False
    reply: object = None
    reactions: tuple = ()
    reaction_people: tuple = ()


class MessageModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.generation = 0

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        m = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return m.text or (m.attachment or {}).get('name', '')
        if role == Qt.UserRole:
            return m
        if role == Qt.ToolTipRole:
            return m.name + "\n" + m.text

    def replace(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.generation += 1
        self.endResetModel()

    def append(self, m):
        n = len(self.rows)
        self.beginInsertRows(QModelIndex(), n, n)
        self.rows.append(m)
        self.endInsertRows()

    def prepend(self, rows):
        if not rows:
            return
        self.beginInsertRows(QModelIndex(), 0, len(rows) - 1)
        self.rows[0:0] = rows
        self.endInsertRows()

    def sync(self, rows):
        # Remove vanished messages without resetting the entire history view.
        target_ids = {row.id for row in rows}
        for index in range(len(self.rows) - 1, -1, -1):
            if self.rows[index].id not in target_ids:
                self.beginRemoveRows(QModelIndex(), index, index)
                del self.rows[index]
                self.endRemoveRows()
        # Common polling response: append only; read receipts update individual rows.
        if len(rows) >= len(self.rows) and all(
            a.id == b.id
            for a, b in zip(self.rows, rows)
        ):
            for i, m in enumerate(rows[: len(self.rows)]):
                if self.rows[i] != m:
                    self.rows[i] = m
                    self.dataChanged.emit(self.index(i), self.index(i))
            extra = rows[len(self.rows) :]
            if extra:
                n = len(self.rows)
                self.beginInsertRows(QModelIndex(), n, n + len(extra) - 1)
                self.rows.extend(extra)
                self.endInsertRows()
        elif rows != self.rows:
            self.replace(rows)


class DialogModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.all_rows = []
        self.query = ""

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        m = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return m.get("nickname", m["login"])
        if role == Qt.UserRole:
            return m

    def replace(self, rows):
        self.all_rows = list(rows)
        self.filter(self.query)

    def filter(self, q):
        self.query = q
        rows = [
            r for r in self.all_rows
            if q.casefold() in (r.get("nickname", "") + " " + r["login"]).casefold()
        ]
        # Polling normally updates previews/presence, not row identities. Avoid
        # invalidating focus, accessibility indexes and scroll position.
        if [r["login"] for r in rows] == [r["login"] for r in self.rows]:
            for index, row in enumerate(rows):
                if row != self.rows[index]:
                    self.rows[index] = row
                    self.dataChanged.emit(self.index(index), self.index(index))
            return
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
