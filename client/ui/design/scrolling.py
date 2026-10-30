"""Shared wheel/trackpad easing; thumb dragging stays direct."""
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
        pixels = event.pixelDelta().y()
        if ((not pixels and not event.angleDelta().y())
                or event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)
                or QApplication.instance().property('reduce_motion')):
            self.animation.stop()
            return False
        if self.bar.maximum() <= self.bar.minimum():
            return False
        running = self.animation.state() == QPropertyAnimation.Running
        delta = pixels if pixels else event.angleDelta().y() / 120 * 24 * QApplication.wheelScrollLines()
        target = self.animation.endValue() if running else self.bar.value()
        # A reversed wheel should reverse immediately instead of finishing
        # the accumulated movement in the old direction.
        if running and (target - self.bar.value()) * delta > 0:
            target = self.bar.value()
        target = max(self.bar.minimum(), min(self.bar.maximum(), int(target - delta)))
        self.animation.stop()
        # Cocoa also delivers discrete mouse scrolling as pixel deltas.
        # Smooth that route too, with a shorter response for continuous input.
        self.animation.setDuration(90 if pixels else 170)
        self.animation.setStartValue(self.bar.value())
        self.animation.setEndValue(target)
        self.animation.start()
        event.accept()
        return True


def controller(area):
    if not hasattr(area, '_smooth_scroll'):
        area._smooth_scroll = SmoothScroll(area)
    return area._smooth_scroll
