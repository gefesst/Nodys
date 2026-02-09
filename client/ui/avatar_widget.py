import os
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont
from PySide6.QtCore import Qt


class AvatarLabel(QLabel):
    """
    Круглый аватар с fallback на инициалы.
    Поддерживает online-индикатор: set_online(True/False).
    """
    def __init__(self, size=40, parent=None):
        super().__init__(parent)
        self.size_px = size
        self._online = None
        self._ring_color = "#2f3136"  # цвет "обводки" статуса под фон карточки

        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border:none; background:transparent;")

        self._dot = QLabel(self)
        self._dot.hide()
        self._dot.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._reposition_dot()

    # ---------- public API ----------
    def set_avatar(self, path="", login="", nickname=""):
        pix = self._load_pixmap(path, login)
        if pix is None or pix.isNull():
            pix = self._make_initials_avatar(nickname or login or "U")

        self.setPixmap(self._to_circle(pix, self.size_px))

    def set_online(self, online: bool | None, ring_color: str | None = None):
        """
        online=True  -> зелёная точка
        online=False -> серая точка
        online=None  -> скрыть точку
        """
        self._online = online
        if ring_color:
            self._ring_color = ring_color

        if online is None:
            self._dot.hide()
            return

        dot = max(9, int(self.size_px * 0.24))
        border = max(2, int(self.size_px * 0.05))
        x = self.size_px - dot - max(1, int(self.size_px * 0.03))
        y = self.size_px - dot - max(1, int(self.size_px * 0.03))
        self._dot.setFixedSize(dot, dot)
        self._dot.move(x, y)

        color = "#43b581" if online else "#747f8d"
        self._dot.setStyleSheet(
            f"background-color:{color}; border:{border}px solid {self._ring_color}; border-radius:{dot // 2}px;"
        )
        self._dot.show()

    # ---------- internals ----------
    def _reposition_dot(self):
        if self._online is not None:
            self.set_online(self._online, self._ring_color)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_dot()

    def _client_dir(self):
        # client/ui/avatar_widget.py -> client
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _load_pixmap(self, path, login):
        # 1) Прямой путь
        if path and os.path.exists(path):
            return QPixmap(path)

        # 2) Относительный путь от client
        if path and not os.path.isabs(path):
            p2 = os.path.join(self._client_dir(), path)
            if os.path.exists(p2):
                return QPixmap(p2)

        # 3) fallback avatars/<login>.<ext>
        if login:
            for ext in (".png", ".jpg", ".jpeg"):
                p = os.path.join(self._client_dir(), "avatars", f"{login}{ext}")
                if os.path.exists(p):
                    return QPixmap(p)

        return None

    def _to_circle(self, source: QPixmap, size: int) -> QPixmap:
        if source.isNull():
            return QPixmap()

        src = source.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

        out = QPixmap(size, size)
        out.fill(Qt.transparent)

        painter = QPainter(out)
        painter.setRenderHint(QPainter.Antialiasing, True)

        clip = QPainterPath()
        clip.addEllipse(0, 0, size, size)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, src)
        painter.end()

        return out

    def _make_initials_avatar(self, name: str) -> QPixmap:
        size = self.size_px
        out = QPixmap(size, size)
        out.fill(Qt.transparent)

        painter = QPainter(out)
        painter.setRenderHint(QPainter.Antialiasing, True)

        hue = (sum(ord(c) for c in name) * 7) % 360
        bg = QColor()
        bg.setHsl(hue, 140, 110)

        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawEllipse(0, 0, size, size)

        initials = self._initials(name)
        painter.setPen(QColor("white"))
        font = QFont("Segoe UI", max(8, size // 3), QFont.Bold)
        painter.setFont(font)
        painter.drawText(out.rect(), Qt.AlignCenter, initials)

        painter.end()
        return out

    @staticmethod
    def _initials(name: str) -> str:
        parts = [p for p in name.strip().split() if p]
        if not parts:
            return "U"
        if len(parts) == 1:
            return parts[0][0].upper()
        return (parts[0][0] + parts[1][0]).upper()
