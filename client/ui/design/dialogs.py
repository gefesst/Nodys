"""Nonblocking confirmation dialog, with no nested event loop."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel
from .widgets import Button


def confirm(parent, title, description, accept_text, callback):
    dialog = QDialog(parent)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(390)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(28, 26, 28, 24)
    layout.setSpacing(20)
    heading = QLabel(title)
    heading.setObjectName("PageTitle")
    heading.setWordWrap(True)
    layout.addWidget(heading)
    text = QLabel(description)
    text.setWordWrap(True)
    layout.addWidget(text)
    row = QHBoxLayout()
    cancel = Button("Отмена")
    cancel.clicked.connect(dialog.reject)
    row.addWidget(cancel)
    accept = Button(accept_text, primary=True)
    accept.clicked.connect(lambda: (dialog.accept(), callback()))
    row.addWidget(accept)
    layout.addLayout(row)
    parent._confirmation = dialog
    dialog.open()
    return dialog
