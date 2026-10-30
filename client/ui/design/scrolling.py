"""Shared wheel easing; native trackpad motion and thumb dragging stay direct."""
from PySide6.QtCore import QObject, QPropertyAnimation, QEasingCurve, Qt
from PySide6.QtWidgets import QApplication


class SmoothScroll(QObject):
    def __init__(self, area):
        super().__init__(area)
        self.area = area
        self.bar = area.verticalScrollBar()
        self.animation = QPropertyAnimation(self.bar, b'value', self)
        self.animation.setDuration(170)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.bar.sliderPressed.connect(self.animation.stop)
        self.bar.actionTriggered.connect(self.animation.stop)

    def wheel(self, event):
        if hasattr(self.area, 'reflow'):
            self.area.reflow.stop()
        # Pixel deltas already contain the OS trackpad/momentum trajectory.
        # Easing these again causes lag and stalls on each tiny wheel event.
        if (not event.pixelDelta().isNull() or not event.angleDelta().y()
                or event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)
                or QApplication.instance().property('reduce_motion')):
            self.animation.stop()
            return False
        if self.bar.maximum() <= self.bar.minimum():
            return False
        running = self.animation.state() == QPropertyAnimation.Running
        delta = event.angleDelta().y() / 120 * 24 * QApplication.wheelScrollLines()
        target = self.animation.endValue() if running else self.bar.value()
        # A reversed wheel should reverse immediately instead of finishing
        # the accumulated movement in the old direction.
        if running and (target - self.bar.value()) * delta > 0:
            target = self.bar.value()
        target = max(self.bar.minimum(), min(self.bar.maximum(), int(target - delta)))
        self.animation.stop()
        self.animation.setStartValue(self.bar.value())
        self.animation.setEndValue(target)
        self.animation.start()
        event.accept()
        return True


def controller(area):
    if not hasattr(area, '_smooth_scroll'):
        area._smooth_scroll = SmoothScroll(area)
    return area._smooth_scroll
