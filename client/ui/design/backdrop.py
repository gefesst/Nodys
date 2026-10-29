"""Optional native backdrop. Failure never prevents the application from opening."""

import sys


def install(window):
    from PySide6.QtWidgets import QApplication

    if QApplication.platformName() in ("offscreen", "minimal"):
        window.backdrop_description = "Offscreen: системные эффекты не проверяются"
        return
    window.backdrop_description = "Фон 96%; системное размытие недоступно"
    existing = getattr(window, "_native_backdrop", None)
    if existing is not None:
        existing.setHidden_(not bool(window.property("translucent_background")))
        window.backdrop_description = (
            "macOS: NSVisualEffectView за фоном 96%"
            if window.property("translucent_background")
            else "Непрозрачный фон"
        )
        return
    if not window.property("translucent_background"):
        window.backdrop_description = "Непрозрачный фон"
        return
    try:
        if sys.platform == "darwin":
            import objc
            from AppKit import (
                NSVisualEffectView,
                NSViewWidthSizable,
                NSViewHeightSizable,
            )

            view = objc.objc_object(c_void_p=int(window.winId()))
            parent = view.superview()
            if parent is None:
                return
            effect = NSVisualEffectView.alloc().initWithFrame_(view.frame())
            effect.setMaterial_(13)  # NSVisualEffectMaterialHUDWindow
            effect.setBlendingMode_(0)  # BehindWindow
            effect.setState_(1)  # Active
            effect.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            parent.addSubview_positioned_relativeTo_(effect, -1, view)
            window._native_backdrop = effect
            from .window_shape import apply

            apply(window)
            window.backdrop_description = "macOS: NSVisualEffectView за фоном 96%"
        elif sys.platform == "win32":
            import ctypes

            if sys.getwindowsversion().build < 22621:
                return
            value = ctypes.c_int(3)  # DWMSBT_TRANSIENTWINDOW, Windows 11 22H2+
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(int(window.winId())),
                38,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                window.backdrop_description = (
                    "Windows: системный Acrylic включён; визуальная проверка необходима"
                )
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        pass
