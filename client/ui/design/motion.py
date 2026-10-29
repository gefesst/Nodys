"""Small local animations without QGraphicsEffect trees on transient rows."""

from PySide6.QtCore import (
    QObject,
    QEvent,
    QPropertyAnimation,
    Property,
    Qt,
    QEasingCurve,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QComboBox,
    QDialog,
    QMenu,
)


def reduced():
    app = QApplication.instance()
    return bool(app and app.property("reduce_motion"))


class MotionFilter(QObject):
    def watch(self, widget):
        if not isinstance(widget, QWidget) or getattr(widget, '_nodus_motion_watched', False):
            return
        widget._nodus_motion_watched = True
        if isinstance(widget, (QPushButton, QLineEdit, QPlainTextEdit, QTextEdit, QComboBox)):
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
        if isinstance(widget, QPlainTextEdit) and widget.objectName() == "MessageComposer":
            frame = widget.parentWidget()
            if frame is not None and frame.objectName() == "ComposerFrame" and kind in (QEvent.FocusIn, QEvent.FocusOut):
                frame.setProperty("editorFocused", kind == QEvent.FocusIn)
                frame.style().unpolish(frame)
                frame.style().polish(frame)
                frame.update()
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
