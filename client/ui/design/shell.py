"""Native movable frameless shell; content retains full opacity."""

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from .widgets import Button, icon, font
from .tokens import FG, ACC, SUB


class WindowDot(QPushButton):
    def __init__(self, color, parent):
        super().__init__(parent)
        self.color=color
        self.setFixedSize(12,12)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet('padding:0;border:0;min-height:0;')

    def paintEvent(self, event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen);painter.setBrush(QColor(self.color))
        painter.drawEllipse(QRectF(0,0,12,12))


class TitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(42)
        import sys
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 18, 0)
        row.setSpacing(10)
        if sys.platform == 'darwin':
            for color, text, callback in (
                ('#F47973', 'Закрыть', parent.close),
                ('#E8BC64', 'Свернуть', parent.showMinimized),
                ('#70C7A0', 'Развернуть', self.maximize),
            ):
                button = WindowDot(color, self)
                button.setToolTip(text);button.setAccessibleName(text)
                button.clicked.connect(callback);row.addWidget(button)
            row.addStretch()
            self.brand = QLabel('Nodus', self)
            self.brand.setObjectName('WindowBrand')
            self.brand.setAlignment(Qt.AlignCenter)
            self.brand.setAttribute(Qt.WA_TransparentForMouseEvents)
        else:
            from .brand import BrandMark
            row.addWidget(BrandMark(24))
            logo=QLabel('Nodus');logo.setObjectName('WindowBrand');row.addWidget(logo);row.addStretch()
            for text, tip, callback in [('—','Свернуть',parent.showMinimized),('□','Развернуть',self.maximize),('×','Закрыть',parent.close)]:
                button=Button(text);button.setProperty('flat',True);button.setFixedSize(36,32)
                button.setToolTip(tip);button.setAccessibleName(tip);button.clicked.connect(callback);row.addWidget(button)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'brand'):
            self.brand.setGeometry(self.width()//2-100,0,200,self.height())

    def maximize(self):
        self.window().showNormal() if self.window().isMaximized() else self.window().showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        self.maximize()

    def paintEvent(self, event):
        pass  # The window paints the title surface once, at the chosen alpha.


class NavButton(Button):
    def __init__(self, text, name, parent=None):
        super().__init__(text, name, parent=parent)
        self.setFixedSize(64, 68)
        self.setToolTip(text)

    def sizeHint(self):
        return QSize(64, 68)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        active = bool(self.property("active"))
        if active or self._hover:
            color = QColor("#2B3B51")
            color.setAlpha(255 if active else int(150 * self._hover))
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(4, 0, 56, 68), 14, 14)
        icon(p, self.icon_name, QRectF(23, 10, 18, 18), ACC if active else SUB)
        p.setPen(QColor(FG if active else SUB))
        p.setFont(font(11, True))
        p.drawText(QRectF(0, 38, 64, 25), Qt.AlignCenter, self.text().split(" (")[0])
        if self.hasFocus() and self._keyboard_focus:
            p.setBrush(Qt.NoBrush);p.setPen(QPen(QColor(ACC),2))
            p.drawRoundedRect(QRectF(2,1,60,66),14,14)
        if "(" in self.text():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACC))
            p.drawEllipse(QRectF(45, 6, 8, 8))


class ResizeHandle(QWidget):
    """Thin native resize target; keeps frameless windows resizable on every edge."""

    def __init__(self, parent, edges, cursor):
        super().__init__(parent)
        self.edges = edges
        self.setCursor(cursor)
        self.drag_origin = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.window().windowHandle():
            if not self.window().windowHandle().startSystemResize(self.edges):
                # Some platform plugins do not implement native frameless resize.
                self.drag_origin = event.globalPosition().toPoint()
                self.drag_geometry = self.window().geometry()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_origin is None:
            return
        delta = event.globalPosition().toPoint() - self.drag_origin
        rect = self.drag_geometry.adjusted(0, 0, 0, 0)
        window = self.window()
        if self.edges & Qt.LeftEdge:
            rect.setLeft(min(rect.right() - window.minimumWidth() + 1, rect.left() + delta.x()))
        if self.edges & Qt.RightEdge:
            rect.setRight(max(rect.left() + window.minimumWidth() - 1, rect.right() + delta.x()))
        if self.edges & Qt.TopEdge:
            rect.setTop(min(rect.bottom() - window.minimumHeight() + 1, rect.top() + delta.y()))
        if self.edges & Qt.BottomEdge:
            rect.setBottom(max(rect.top() + window.minimumHeight() - 1, rect.bottom() + delta.y()))
        window.setGeometry(rect)
        event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_origin = None
        event.accept()


def create_resize_handles(window):
    return [ResizeHandle(window, edges, cursor) for edges, cursor in (
        (Qt.LeftEdge, Qt.SizeHorCursor), (Qt.RightEdge, Qt.SizeHorCursor),
        (Qt.TopEdge, Qt.SizeVerCursor), (Qt.BottomEdge, Qt.SizeVerCursor),
        (Qt.TopEdge | Qt.LeftEdge, Qt.SizeFDiagCursor),
        (Qt.TopEdge | Qt.RightEdge, Qt.SizeBDiagCursor),
        (Qt.BottomEdge | Qt.LeftEdge, Qt.SizeBDiagCursor),
        (Qt.BottomEdge | Qt.RightEdge, Qt.SizeFDiagCursor),
    )]


def position_resize_handles(window):
    w, h, d = window.width(), window.height(), 5
    corner = 14  # Reach the visible arc; a 5px square is outside the rounded mask.
    geometries = ((0,d,d,h-2*d), (w-d,d,d,h-2*d),
                  (d,0,w-2*d,d), (d,h-d,w-2*d,d),
                  (0,0,corner,corner), (w-corner,0,corner,corner),
                  (0,h-corner,corner,corner), (w-corner,h-corner,corner,corner))
    for handle, geometry in zip(window.resize_handles, geometries):
        handle.setGeometry(*geometry)
        handle.setVisible(not window.isMaximized() and not window.isFullScreen())
        handle.raise_()
