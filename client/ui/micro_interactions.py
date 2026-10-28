"""Native Qt hover/press feedback.

Button feedback is styled through QSS :hover/:pressed. Avoid allocating a
QGraphicsOpacityEffect per transient list button: Qt can crash while rebuilding
those effect trees during asynchronous list refreshes.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def install_opacity_feedback(
    widget: QWidget,
    *,
    hover_opacity: float = 0.985,
    pressed_opacity: float = 0.93,
    duration_ms: int = 90,
) -> None:
    """Compatibility entry point; native styles now own interaction rendering."""
    if widget is not None:
        widget.setAttribute(Qt.WA_Hover, True)
