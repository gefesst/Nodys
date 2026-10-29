"""The top-level native region, independent of child-widget backgrounds."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath, QRegion

RADIUS = 14


def window_region(width, height, maximized=False):
    path = QPainterPath()
    rect = QRectF(0, 0, width, height)
    if maximized:
        path.addRect(rect)
    else:
        path.addRoundedRect(rect, RADIUS, RADIUS)
    return QRegion(path.toFillPolygon().toPolygon())


def apply(window):
    square = window.isMaximized() or window.isFullScreen()
    window.setMask(window_region(window.width(), window.height(), square))
    effect = getattr(window, '_native_backdrop', None)
    if effect is not None:
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(0 if square else RADIUS)
        effect.layer().setMasksToBounds_(True)
