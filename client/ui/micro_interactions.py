from __future__ import annotations

from PySide6.QtCore import QObject, QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


class _OpacityFeedbackFilter(QObject):
    """Lightweight hover/press feedback with tiny opacity animation.

    No timers or continuous animations are used, so this stays cheap even on
    lower-end devices.
    """

    def __init__(
        self,
        target: QWidget,
        *,
        hover_opacity: float = 0.985,
        pressed_opacity: float = 0.93,
        duration_ms: int = 90,
    ) -> None:
        super().__init__(target)
        self._target = target
        self._hover = float(hover_opacity)
        self._pressed = float(pressed_opacity)
        self._duration = max(40, int(duration_ms))
        self._entered = False
        self._pressed_now = False

        effect = target.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(target)
            effect.setOpacity(1.0)
            target.setGraphicsEffect(effect)
        self._effect: QGraphicsOpacityEffect = effect

        self._anim = QPropertyAnimation(self._effect, b"opacity", target)
        self._anim.setDuration(self._duration)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def _animate_to(self, value: float) -> None:
        try:
            value = max(0.35, min(1.0, float(value)))
            if abs(self._effect.opacity() - value) < 0.002:
                return
            self._anim.stop()
            self._anim.setStartValue(self._effect.opacity())
            self._anim.setEndValue(value)
            self._anim.start()
        except Exception:
            # Silent fallback in case some platform style blocks effects.
            try:
                self._effect.setOpacity(value)
            except Exception:
                pass

    def eventFilter(self, obj, event):
        et = event.type()

        if et == QEvent.Enter:
            self._entered = True
            self._animate_to(self._pressed if self._pressed_now else self._hover)
            return False

        if et == QEvent.Leave:
            self._entered = False
            if not self._pressed_now:
                self._animate_to(1.0)
            return False

        if et == QEvent.MouseButtonPress:
            self._pressed_now = True
            self._animate_to(self._pressed)
            return False

        if et == QEvent.MouseButtonRelease:
            self._pressed_now = False
            self._animate_to(self._hover if self._entered else 1.0)
            return False

        if et in (QEvent.EnabledChange, QEvent.Hide):
            if not self._target.isEnabled() or not self._target.isVisible():
                self._pressed_now = False
                self._entered = False
                self._animate_to(1.0)
            return False

        return False


def install_opacity_feedback(
    widget: QWidget,
    *,
    hover_opacity: float = 0.985,
    pressed_opacity: float = 0.93,
    duration_ms: int = 90,
) -> None:
    """Attach subtle hover/press micro-interaction to a widget."""
    if widget is None:
        return

    # avoid duplicate install
    if hasattr(widget, "_opacity_feedback_filter"):
        return

    flt = _OpacityFeedbackFilter(
        widget,
        hover_opacity=hover_opacity,
        pressed_opacity=pressed_opacity,
        duration_ms=duration_ms,
    )
    widget.installEventFilter(flt)
    widget._opacity_feedback_filter = flt
