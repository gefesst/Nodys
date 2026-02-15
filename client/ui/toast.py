from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget


class InlineToast:
    """Small reusable bottom-centered toast helper for page widgets.

    Usage:
        self._toast = InlineToast(self)
        self._toast.show("Saved", 1800)
        self._toast.reposition()  # call from resizeEvent
    """

    def __init__(
        self,
        parent: QWidget,
        *,
        object_name: str = "InlineToast",
        min_width: int = 220,
        max_width: int = 560,
        horizontal_margin: int = 12,
        bottom_margin: int = 16,
    ) -> None:
        self.parent = parent
        self.min_width = max(120, int(min_width))
        self.max_width = max(self.min_width, int(max_width))
        self.horizontal_margin = max(4, int(horizontal_margin))
        self.bottom_margin = max(4, int(bottom_margin))

        self.label = QLabel("", parent)
        self.label.setObjectName(object_name)
        self.label.setVisible(False)
        self.label.setWordWrap(True)

        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def is_visible(self) -> bool:
        return self.label.isVisible()

    def hide(self) -> None:
        self.label.setVisible(False)

    def show(self, text: str, msec: int = 1800) -> None:
        if not text:
            return
        self.label.setText(str(text))
        self.label.setVisible(True)
        self.reposition()
        self.label.raise_()
        self._timer.start(max(700, int(msec or 0)))

    def reposition(self) -> None:
        if not self.label.isVisible() or self.parent is None:
            return

        available_w = max(120, self.parent.width() - self.horizontal_margin * 2)
        width = min(max(self.min_width, available_w), self.max_width)
        self.label.setFixedWidth(width)
        self.label.adjustSize()

        x = max(self.horizontal_margin, (self.parent.width() - self.label.width()) // 2)
        y = max(self.horizontal_margin, self.parent.height() - self.label.height() - self.bottom_margin)
        self.label.move(x, y)
