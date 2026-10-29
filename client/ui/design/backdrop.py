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
    if sys.platform == "win32":
        try:
            _install_windows(window, bool(window.property("translucent_background")))
        except (AttributeError, RuntimeError, ValueError, OSError):
            pass
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
    except (ImportError, AttributeError, RuntimeError, ValueError, OSError):
        pass


def _install_windows(window, enabled):
    import ctypes

    if not enabled:
        window.backdrop_description = "Непрозрачный фон"
    if sys.getwindowsversion().build < 22621:
        return
    # Explicit NONE also removes a material installed before the preference changed.
    # https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type
    value = ctypes.c_int(3 if enabled else 1)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(int(window.winId())), 38,
        ctypes.byref(value), ctypes.sizeof(value),
    )
    if result == 0:
        window.backdrop_description = (
            "Windows: системный Acrylic включён; визуальная проверка необходима"
            if enabled else "Непрозрачный фон"
        )
