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
    # A binary QRegion produces staircase edges on scaled/Retina displays.
    window.clearMask()
    if __import__('sys').platform == 'darwin':
        from PySide6.QtWidgets import QApplication
        if QApplication.platformName() not in ('offscreen','minimal'):
            try:
                import objc
                view=objc.objc_object(c_void_p=int(window.winId()))
                view.setWantsLayer_(True)
                view.layer().setCornerRadius_(0 if square else RADIUS)
                view.layer().setMasksToBounds_(True)
            except (ImportError,AttributeError,RuntimeError,ValueError):
                pass
    effect = getattr(window, '_native_backdrop', None)
    if effect is not None:
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(0 if square else RADIUS)
        effect.layer().setMasksToBounds_(True)
