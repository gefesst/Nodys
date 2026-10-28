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
            return m.text
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
        # Common polling response: append only; read receipts update individual rows.
        if len(rows) >= len(self.rows) and all(
            a.id == b.id and a.text == b.text and a.group == b.group
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
        self.filter("")

    def filter(self, q):
        self.beginResetModel()
        self.rows = [
            r
            for r in self.all_rows
            if q.casefold() in (r.get("nickname", "") + " " + r["login"]).casefold()
        ]
        self.endResetModel()
