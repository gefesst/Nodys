"""Preserve Cocoa cursors after pointer events and asynchronous UI updates."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


class DesktopApplication(QApplication):
    def notify(self, receiver, event):
        result = super().notify(receiver, event)
        if event.type() in (QEvent.MouseMove, QEvent.UpdateRequest, QEvent.LayoutRequest, QEvent.Timer, QEvent.MetaCall) and self.platformName() == "cocoa":
            self._finish_mouse_move()
        return result

    def _finish_mouse_move(self):
        if self.applicationState() != Qt.ApplicationActive or self.overrideCursor() is not None:
            return
        target = self.widgetAt(QCursor.pos())
        if target is None:
            return
        from ui.design.motion import interactive_cursor
        shape = interactive_cursor(target)
        if shape is None:
            return
        try:
            from AppKit import NSCursor
        except ImportError:
            return
        native = {Qt.IBeamCursor: NSCursor.IBeamCursor,
                  Qt.PointingHandCursor: NSCursor.pointingHandCursor,
                  Qt.ArrowCursor: NSCursor.arrowCursor}.get(shape)
        if native is not None:
            native().set()
