"""Nonblocking confirmations inside the main application window."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel
from .widgets import Button
from .overlay import OverlayDialog


def confirm(parent, title, description, accept_text, callback, *, danger=False):
    previous = getattr(parent, "_confirmation", None)
    if previous is not None:
        try:
            previous.reject()
        except RuntimeError:
            pass
    dialog = OverlayDialog(parent, 620, 280, anchor="modal")
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.setWindowTitle(title)
    dialog.setStyleSheet(
        "QDialog#OverlayDialog {background:#202C3B;border:1px solid #465772;border-radius:16px;}"
    )
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(32, 26, 32, 32)
    layout.setSpacing(0)
    heading = QLabel(title)
    heading.setStyleSheet("font-size:23px;font-weight:600;")
    heading.setWordWrap(True)
    layout.addWidget(heading)
    layout.addSpacing(24)
    text = QLabel(description)
    text.setStyleSheet("font-size:14px;color:#A9B8CD;")
    text.setWordWrap(True)
    layout.addWidget(text)
    layout.addStretch()
    row = QHBoxLayout()
    row.setSpacing(16)
    row.addStretch()
    cancel = Button("Отмена")
    cancel.setFixedSize(132, 40)
    cancel.clicked.connect(dialog.reject)
    row.addWidget(cancel)
    accept = Button(accept_text, primary=not danger)
    accept.setFixedSize(156, 40)
    if danger:
        accept.setProperty("danger",True)
        accept.setStyleSheet(
            "color:#FF9C9C;background:#49313B;border:1px solid #6B424C;"
        )
    accept.clicked.connect(lambda: (dialog.accept(), callback()))
    row.addWidget(accept)
    layout.addLayout(row)
    parent._confirmation = dialog
    dialog.open()
    cancel.setFocus()
    return dialog
