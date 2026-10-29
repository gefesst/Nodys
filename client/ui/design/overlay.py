"""Dialogs contained by the application window, with bounded placement."""

import weakref
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QWidget


class DismissShade(QFrame):
    def __init__(self, host, dialog):
        super().__init__(host)
        self.dialog_ref = weakref.ref(dialog)

    def mousePressEvent(self, event):
        dialog = self.dialog_ref()
        if dialog is not None:
            dialog.reject()
        event.accept()


class OverlayDialog(QDialog):
    def __init__(self, parent, width=520, height=420, anchor="center", dim=True):
        controller = getattr(parent, "controller", None)
        host = controller.window() if isinstance(controller, QWidget) else parent.window()
        super().__init__(host)
        self.setWindowFlags(Qt.Widget)
        self._host_ref = weakref.ref(host)
        self.anchor = anchor
        self.dim = dim
        self.preferred_size = (width, height)
        self.setObjectName("OverlayDialog")
        self.shade = DismissShade(host, self)
        self.shade.setStyleSheet(
            "background:rgba(5,10,18,130);border:0;"
            if dim
            else "background:transparent;border:0;"
        )
        self.shade.hide()
        self.previous_focus = None
        host.installEventFilter(self)
        self.finished.connect(self._finished)
        self.destroyed.connect(self.shade.deleteLater)

    @property
    def host(self):
        return self._host_ref()

    def position_panel(self):
        self.shade.setGeometry(self.host.rect())
        width = min(self.preferred_size[0], self.host.width() - 40)
        height = min(self.preferred_size[1], self.host.height() - 60)
        x = (self.host.width() - width) // 2
        y = (self.host.height() - height) // 2
        if self.anchor == "right":
            x = max(20, self.host.width() - width - 44)
            y = min(190, self.host.height() - height - 20)
        if self.anchor == "quick":
            x = min(
                self.host.width() - width - 20, max(20, self.host.width() // 2 - 260)
            )
            y = max(20, (self.host.height() - height) // 2 - 29)
            self.shade.setGeometry(
                88, 42, self.host.width() - 88, self.host.height() - 42
            )
        if self.anchor == "call":
            x = min(
                self.host.width() - width - 20, (self.host.width() - width) // 2 + 204
            )
            y = max(20, (self.host.height() - height) // 2 + 16)
            self.shade.setGeometry(
                88, 42, self.host.width() - 88, self.host.height() - 42
            )
            self.shade.setStyleSheet("background:rgba(8,13,21,153);border:0;" if self.dim else "background:transparent;border:0;")
        if self.anchor == "modal":
            x = min(
                self.host.width() - width - 20, (self.host.width() - width) // 2 + 125
            )
            y = max(20, (self.host.height() - height) // 2 - 28)
            self.shade.setGeometry(
                88, 42, self.host.width() - 88, self.host.height() - 42
            )
            self.shade.setStyleSheet("background:rgba(8,13,21,153);border:0;" if self.dim else "background:transparent;border:0;")
        self.setGeometry(x, y, width, height)

    def show(self):
        self.previous_focus = QApplication.focusWidget()
        super().show()

    def showEvent(self, event):
        self.position_panel()
        self.shade.show()
        self.shade.raise_()
        self.raise_()
        super().showEvent(event)
        self.setFocus(Qt.OtherFocusReason)
        self.focusNextChild()

    def focusNextPrevChild(self, forward):
        candidates = [
            child
            for child in self.findChildren(QWidget)
            if child.isVisible()
            and child.isEnabled()
            and child.focusPolicy() & Qt.TabFocus
        ]
        if not candidates:
            return False
        current = QApplication.focusWidget()
        index = (
            candidates.index(current)
            if current in candidates
            else (-1 if forward else 0)
        )
        candidates[(index + (1 if forward else -1)) % len(candidates)].setFocus(
            Qt.TabFocusReason if forward else Qt.BacktabFocusReason
        )
        return True

    def open(self):
        self.show()

    def hideEvent(self, event):
        self.shade.hide()
        super().hideEvent(event)

    def _finished(self, result):
        self.shade.hide()
        if self.previous_focus is not None:
            try:
                self.previous_focus.setFocus(Qt.OtherFocusReason)
            except RuntimeError:
                pass

    def eventFilter(self, watched, event):
        if watched is self.host and event.type() == QEvent.Resize:
            self.position_panel()
        return super().eventFilter(watched, event)
