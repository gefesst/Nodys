"""Small local animations without QGraphicsEffect trees on transient rows."""

from PySide6.QtCore import (
    QObject,
    QEvent,
    QPropertyAnimation,
    Property,
    Qt,
    QEasingCurve,
)
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QDialog,
    QMenu,
)


def reduced():
    app = QApplication.instance()
    return bool(app and app.property("reduce_motion"))


class FocusRing(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # Parent field styles may constrain content height; the overlay follows
        # the entire control, including its padding and border.
        self.setStyleSheet("min-width:0;min-height:0;max-width:16777215;max-height:16777215;padding:0;border:0;background:transparent;")
        self._level = 0.0
        self.animation = QPropertyAnimation(self, b"level", self)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)

    def get_level(self):
        return self._level

    def set_level(self, value):
        self._level = value
        self.update()

    level = Property(float, get_level, set_level)

    def change(self, value):
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.animation.stop()
        self.animation.setDuration(0 if reduced() else 130)
        self.animation.setStartValue(self._level)
        self.animation.setEndValue(value)
        self.animation.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#91ADFF")
        color.setAlpha(int(150 * self._level))
        painter.setPen(QPen(color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 10, 10)


class MotionFilter(QObject):
    def watch(self, widget):
        if not isinstance(widget, QWidget) or getattr(widget, '_nodus_motion_watched', False):
            return
        widget._nodus_motion_watched = True
        if isinstance(widget, (QPushButton, QLineEdit, QPlainTextEdit)):
            widget.setAttribute(Qt.WA_MacShowFocusRect, False)
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            self.watch(child)

    def eventFilter(self, widget, event):
        kind = event.type()
        if kind == QEvent.ChildPolished:
            self.watch(event.child())
            return False
        if kind not in (QEvent.Enter, QEvent.Leave, QEvent.FocusIn,
                        QEvent.FocusOut, QEvent.Resize, QEvent.Show):
            return False
        if (not hasattr(widget,"_keyboard_focus") and not widget.property("no_focus_ring")
            and isinstance(widget, (QLineEdit, QPlainTextEdit))) and kind in (
            QEvent.Enter,
            QEvent.Leave,
            QEvent.FocusIn,
            QEvent.FocusOut,
            QEvent.Resize,
        ):
            if not hasattr(widget, "_focus_ring") and kind in (
                QEvent.Enter,
                QEvent.FocusIn,
            ):
                widget._focus_ring = FocusRing(widget)
            ring = getattr(widget, "_focus_ring", None)
            if ring:
                if kind == QEvent.Resize:
                    ring.setGeometry(widget.rect())
                else:
                    ring.change(1.0 if kind in (QEvent.Enter, QEvent.FocusIn) else 0.0)
        if (
            isinstance(widget, (QDialog, QMenu))
            and kind == QEvent.Show
            and not reduced()
            and QApplication.platformName() not in ("offscreen", "minimal")
        ):
            animation = QPropertyAnimation(widget, b"windowOpacity", widget)
            animation.setDuration(150)
            animation.setStartValue(0.85)
            animation.setEndValue(1.0)
            widget._appearance_animation = animation
            animation.start()
        return False


def install(app):
    from config import load_config

    app.setProperty("reduce_motion", bool(load_config().get("reduce_motion", False)))
    app._nodus_motion = MotionFilter(app)
    # Only watch finished application widgets. An application-wide filter also
    # wraps Qt's internal objects while they are being constructed/destroyed.


def watch(window):
    app = QApplication.instance()
    controller = getattr(app, '_nodus_motion', None)
    if controller is not None:
        controller.watch(window)


class PageOverlay(QWidget):
    """Short snapshot transition; no opacity effect on the live widget tree."""

    def __init__(self, stack, pixmap):
        super().__init__(stack)
        self.pixmap = pixmap
        self._progress = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(stack.rect())
        self.animation = QPropertyAnimation(self, b"progress", self)
        self.animation.setDuration(160)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self.animation.start()

    def get_progress(self):
        return self._progress

    def set_progress(self, value):
        self._progress = value
        self.update()

    progress = Property(float, get_progress, set_progress)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(1 - self._progress)
        painter.drawPixmap(int(-8 * self._progress), 0, self.pixmap)


from PySide6.QtWidgets import QStackedWidget


class TransitionStack(QStackedWidget):
    def setCurrentWidget(self, widget):
        old = self.currentWidget()
        snapshot = (
            old.grab()
            if old is not None
            and old is not widget
            and self.isVisible()
            and not reduced()
            else None
        )
        super().setCurrentWidget(widget)
        if snapshot is not None:
            PageOverlay(self, snapshot)

    def setCurrentIndex(self, index):
        widget = self.widget(index)
        if widget is not None:
            self.setCurrentWidget(widget)
