from collections import OrderedDict
from pathlib import Path
import re, time
from PySide6.QtCore import (
    Qt,
    QByteArray,
    QRectF,
    QSize,
    QPropertyAnimation,
    Property,
    QEasingCurve,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QFont,
    QPen,
    QTextLayout,
    QTextOption,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QPushButton,
    QStyledItemDelegate,
    QStyle,
    QPlainTextEdit,
    QListView,
    QAbstractItemView,
)
from PySide6.QtSvg import QSvgRenderer
from .motion import reduced
from .tokens import ACC, FG, SUB, MUT, EDGE, GREEN, RED

ASSETS = Path(__file__).parent / "assets"
ICONS = {}


class MessageList(QListView):
    """Preserve a visible row after width-dependent message reflow."""

    def __init__(self):
        super().__init__()
        self.anchor = 0
        self.reflow = QTimer(self)
        self.reflow.setSingleShot(True)
        self.reflow.setInterval(100)
        self.reflow.timeout.connect(self.restore_anchor)

    def resizeEvent(self, event):
        from PySide6.QtCore import QPoint

        index = self.indexAt(QPoint(80, 12))
        if index.isValid():
            self.anchor = index.row()
            self.anchor_offset = self.visualRect(index).top()
        bar = self.verticalScrollBar()
        self.anchor_bottom = bar.maximum() - bar.value() < 20
        super().resizeEvent(event)
        self.reflow.start()

    def restore_anchor(self):
        if not self.model() or not self.model().rowCount():
            return
        self.setLayoutMode(QListView.SinglePass)
        self.doItemsLayout()
        if getattr(self, "anchor_bottom", False):
            self.scrollToBottom()
        else:
            self.scrollTo(
                self.model().index(min(self.anchor, self.model().rowCount() - 1)),
                QAbstractItemView.PositionAtTop,
            )
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - getattr(self, "anchor_offset", 0))
        self.setLayoutMode(QListView.Batched)


def font(px=15, bold=False):
    f = QFont("Arial")
    f.setPixelSize(px)
    f.setWeight(QFont.DemiBold if bold else QFont.Normal)
    return f


def icon(p, name, rect, color=SUB):
    key = (name, color)
    if key not in ICONS:
        file = ASSETS / (name + ".svg")
        data = file.read_text().replace("#ACB9CC", color)
        # Select the byte-array overload explicitly. The constructor also accepts
        # a filename and a QXmlStreamReader; never pass untyped temporary bytes.
        renderer = QSvgRenderer(QApplication.instance())
        if not renderer.load(QByteArray(data.encode("utf-8"))):
            raise ValueError(f"Invalid bundled SVG icon: {name}")
        ICONS[key] = renderer
    ICONS[key].render(p, QRectF(rect))


def draw_text(p, x, y, s, px=15, color=FG, bold=False):
    p.setFont(font(px, bold))
    p.setPen(QColor(color))
    p.drawText(int(x), int(y), str(s))


def avatar(p, x, y, initials="АМ", size=36, online=False, own=False):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#4A485E" if own else "#40536B"))
    p.drawEllipse(QRectF(x, y, size, size))
    curve = QPainterPath()
    curve.moveTo(x+size*.14, y+size*.75)
    curve.quadTo(x+size*.45, y+size*.92, x+size*.88, y+size*.28)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(177,197,239,36), size*.025))
    p.drawPath(curve)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#66799A"))
    p.drawEllipse(QRectF(x+size*.16,y+size*.72,size*.1,size*.1))
    p.drawEllipse(QRectF(x+size*.78,y+size*.32,size*.08,size*.08))
    p.setFont(font(int(size * 0.29), True))
    p.setPen(QColor(FG))
    p.drawText(QRectF(x, y, size, size), Qt.AlignCenter, initials)
    if online:
        p.setPen(QPen(QColor("#19222D"), 2))
        p.setBrush(QColor(GREEN))
        p.drawEllipse(QRectF(x + size - 8, y + size - 8, 8, 8))


class Avatar(QWidget):
    def __init__(self, initials="АМ", size=40, online=True, parent=None):
        super().__init__(parent)
        self.initials = initials
        self.online = online
        self.setFixedSize(size + 2, size + 2)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        avatar(
            p, 1, 1, self.initials, self.width() - 2, self.online, self.initials == "АН"
        )


class Button(QPushButton):
    def __init__(self, text="", icon_name=None, primary=False, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("padding:0;border:0;min-height:0;")
        self.icon_name = icon_name
        self.primary = primary
        self._hover = 0.0
        self.setMinimumHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.animation = QPropertyAnimation(self, b"hover", self)
        self.animation.setDuration(160)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.setFont(font(13, True))

    def sizeHint(self):
        return QSize(
            max(
                46,
                self.fontMetrics().horizontalAdvance(self.text())
                + 40
                + (26 if self.icon_name else 0),
            ),
            46,
        )

    def get_hover(self):
        return self._hover

    def set_hover(self, v):
        self._hover = v
        self.update()

    hover = Property(float, get_hover, set_hover)

    def enterEvent(self, e):
        self.animation.stop()
        self.animation.setDuration(0 if reduced() else 160)
        self.animation.setStartValue(self._hover)
        self.animation.setEndValue(1.0)
        self.animation.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.animation.stop()
        self.animation.setDuration(0 if reduced() else 160)
        self.animation.setStartValue(self._hover)
        self.animation.setEndValue(0.0)
        self.animation.start()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        a = QColor(ACC if self.primary else "#28364A")
        b = QColor("#ACC0FF" if self.primary else "#3A4D67")
        if self.property("danger"):
            a, b = QColor("#54313E"), QColor("#704151")
        t = self._hover
        bg = QColor.fromRgbF(
            a.redF() * (1 - t) + b.redF() * t,
            a.greenF() * (1 - t) + b.greenF() * t,
            a.blueF() * (1 - t) + b.blueF() * t,
        )
        if self.isDown():
            bg = QColor("#7898EB" if self.primary else "#354866")
        if not self.isEnabled():
            bg = QColor("#252E3A")
        if self.property("flat") and not self._hover and not self.isDown():
            bg.setAlpha(0)
        p.setPen(Qt.NoPen if self.property("flat") else QPen(QColor("#354152"), 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 9, 9)
        color = "#142039" if self.primary else SUB if self.property("flat") else FG
        if self.property("danger"):
            color = RED
        if not self.isEnabled():
            color = "#8190A5"
        p.setFont(self.font())
        width = p.fontMetrics().horizontalAdvance(self.text())
        total = width + (26 if self.icon_name else 0)
        x = 12 if self.property("align_left") else (self.width() - total) / 2
        if self.icon_name:
            icon(p, self.icon_name, QRectF(x, (self.height() - 18) / 2, 18, 18), color)
            x += 26
        p.setPen(QColor(color))
        p.drawText(QRectF(x, 0, width + 3, self.height()), Qt.AlignVCenter, self.text())
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(ACC), 2))
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 11, 11)


class DialogDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        from ui.avatar_widget import AvatarLabel

        self._avatar_helper = AvatarLabel(38)
        self._avatar_helper.hide()
        self._avatars = OrderedDict()

    def sizeHint(self, o, i):
        return QSize(300, 80)

    def paint(self, p, o, index):
        d = index.data(Qt.UserRole)
        r = o.rect.adjusted(6, 3, -6, -3)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        selected = bool(o.state & QStyle.State_Selected)
        hover = bool(o.state & QStyle.State_MouseOver)
        if selected or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#2B3B51" if selected else "#273446"))
            p.drawRoundedRect(r, 11, 11)
        if selected:
            p.setBrush(QColor(ACC))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 18, 3, 38), 1.5, 1.5)
        n = d.get("nickname", d["login"])
        ini = "".join(s[0] for s in n.split()[:2])
        avatar(p, r.left() + 14, r.top() + 18, ini, 38, d.get("online", False))
        if d.get("avatar"):
            key = (d["avatar"], d["login"], bool(d.get("online")))
            if key not in self._avatars:
                self._avatar_helper.set_avatar(d["avatar"], d["login"], n)
                self._avatar_helper.set_online(bool(d.get("online")))
                self._avatars[key] = self._avatar_helper.grab()
                if len(self._avatars) > 128:
                    self._avatars.popitem(last=False)
            p.drawPixmap(r.left() + 14, r.top() + 18, self._avatars[key])
        p.setFont(font(14, True))
        title = p.fontMetrics().elidedText(n, Qt.ElideRight, r.width() - 126)
        draw_text(p, r.left() + 66, r.top() + 29, title, 14, FG, True)
        summary = d.get("summary") or {}
        preview = summary.get("text", "").replace("\n", " ")
        if preview and summary.get("outgoing"):
            preview = "Вы: " + preview
        if not preview:
            preview = "Начните переписку"
        p.setFont(font(12))
        preview = p.fontMetrics().elidedText(
            preview, Qt.ElideRight, max(20, r.width() - 110)
        )
        draw_text(p, r.left() + 66, r.top() + 51, preview, 12, SUB)
        timestamp = summary.get("timestamp", "")
        if timestamp:
            from datetime import datetime

            try:
                date = datetime.fromisoformat(timestamp)
                stamp = (
                    date.strftime("%H:%M")
                    if date.date() == datetime.now().date()
                    else date.strftime("%d.%m")
                )
                draw_text(p, r.right() - 45, r.top() + 27, stamp, 10, SUB)
            except (ValueError, TypeError):
                pass
        count = int(d.get("unread_count", 0) or 0)
        if count:
            badge = QRectF(r.right() - 38, r.top() + 42, 28, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACC))
            p.drawRoundedRect(badge, 10, 10)
            p.setPen(QColor("#142039"))
            p.setFont(font(10, True))
            p.drawText(badge, Qt.AlignCenter, str(min(count, 99)))
        p.restore()


class MessageDelegate(QStyledItemDelegate):
    def __init__(self, view, me, own_name=None):
        super().__init__(view)
        self.view = view
        self.me = me
        self.own_name = own_name or (lambda: me)
        self.cache = OrderedDict()
        self.paint_count = 0
        self.paint_ns = []
        self.fade_row = -1
        self.fade_start = 0
        self.fade_timer = QTimer(self)
        self.fade_timer.setInterval(16)
        self.fade_timer.timeout.connect(self.tick)

    def tick(self):
        self.view.viewport().update()
        if time.perf_counter() - self.fade_start >= 0.16:
            self.fade_timer.stop()
            self.fade_row = -1

    def animate_row(self, row):
        if reduced():
            return
        self.fade_row = row
        self.fade_start = time.perf_counter()
        self.fade_timer.start()

    def geometry(self, m, width):
        maxw = max(180, min(660, width - 114))
        key = (m.text, maxw, m.group, m.divider)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        layout = QTextLayout(m.text, font(15))
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        formats = []
        for match in re.finditer(r"https?://\S+", m.text):
            f = QTextLayout.FormatRange()
            f.start = match.start()
            f.length = match.end() - match.start()
            f.format = QTextCharFormat()
            f.format.setForeground(QColor(ACC))
            formats.append(f)
        layout.setFormats(formats)
        layout.beginLayout()
        y = 0
        natural = 0
        # QTextLayout treats line separators reliably; paragraph newlines are normalized to U+2028.
        layout.endLayout()
        layout.setText(m.text.replace("\n", "\u2028"))
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(maxw - 32)
            line.setPosition(
                __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(0, y)
            )
            y += max(23, line.height())
            natural = max(natural, line.naturalTextWidth())
        layout.endLayout()
        bw = min(maxw, max(125, natural + 32))
        bh = y + 40
        head = (27 if m.divider else 41) if m.group else 0
        head += 28 if m.divider else 0
        height = head + bh + 8
        value = (layout, bw, bh, head, height)
        self.cache[key] = value
        if len(self.cache) > 600:
            self.cache.popitem(last=False)
        return value

    def sizeHint(self, o, i):
        m = i.data(Qt.UserRole)
        return QSize(
            0, int(self.geometry(m, max(350, self.view.viewport().width()))[-1])
        )

    @staticmethod
    def shape(x, y, w, h, tail):
        r = 12
        p = QPainterPath()
        p.moveTo(x + r, y)
        p.lineTo(x + w - r, y)
        p.quadTo(x + w, y, x + w, y + r)
        p.lineTo(x + w, y + h - r)
        p.quadTo(x + w, y + h, x + w - r, y + h)
        p.lineTo(x + r, y + h)
        p.quadTo(x, y + h, x, y + h - r)
        if tail:
            p.lineTo(x, y + 26)
            p.quadTo(x, y + 22, x - 7, y + 17)
            p.quadTo(x - 9, y + 15, x - 5, y + 15)
            p.quadTo(x, y + 15, x, y + 10)
            p.quadTo(x, y, x + r, y)
        else:
            p.lineTo(x, y + r)
            p.quadTo(x, y, x + r, y)
        p.closeSubpath()
        return p

    def paint(self, p, o, index):
        started = time.perf_counter_ns()
        m = index.data(Qt.UserRole)
        layout, bw, bh, head, _ = self.geometry(m, self.view.viewport().width())
        own = m.author == self.me
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setClipRect(o.rect)
        if index.row() == self.fade_row:
            p.setOpacity(min(1, (time.perf_counter() - self.fade_start) / 0.16))
        x = o.rect.x() + 58
        y = o.rect.y() + head
        date_offset = 28 if m.divider else (14 if m.group else 0)
        if m.divider:
            p.setFont(font(11))
            label_width = p.fontMetrics().horizontalAdvance(m.date)
            center = self.view.viewport().width() / 2
            p.setPen(QPen(QColor(EDGE), 1))
            line_y = o.rect.y() + 14
            p.drawLine(10, line_y, int(center - label_width / 2 - 16), line_y)
            p.drawLine(
                int(center + label_width / 2 + 16),
                line_y,
                self.view.viewport().width() - 10,
                line_y,
            )
            draw_text(p, center - label_width / 2, o.rect.y() + 18, m.date, 11, MUT)
        if m.group:
            display_name = self.own_name() if own else m.name
            parts = display_name.split()
            initials = (
                "".join(s[0] for s in parts[:2]) if len(parts) > 1 else display_name[:2]
            )
            avatar(
                p,
                o.rect.x() + 10,
                o.rect.y() + 1 + date_offset,
                initials,
                32,
                False,
                own,
            )
            p.setFont(font(13, True))
            name = p.fontMetrics().elidedText(
                m.name, Qt.ElideRight, self.view.viewport().width() - 120
            )
            draw_text(
                p, x, o.rect.y() + 14 + date_offset, name, 13, ACC if own else FG, True
            )
        p.setBrush(QColor("#273951" if own else "#222E3D"))
        p.setPen(QPen(QColor("#3B506C" if own else "#334254"), 1))
        p.drawPath(self.shape(x, y, bw, bh, m.group))
        p.setPen(QColor(FG))
        layout.draw(
            p,
            __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(x + 16, y + 11),
        )
        draw_text(p, x + bw - (67 if own else 45), y + bh - 12, m.time, 11, MUT)
        if own:
            icon(
                p,
                "double" if m.read else "check",
                QRectF(x + bw - 30, y + bh - 24, 16, 16),
                ACC if m.read else MUT,
            )
        p.restore()
        self.paint_count += 1
        if len(self.paint_ns) < 50000:
            self.paint_ns.append(time.perf_counter_ns() - started)


class Composer(QPlainTextEdit):
    submit = Signal()

    @property
    def returnPressed(self):
        return self.submit

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(text)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(font(15))
        self.setPlaceholderText("Сообщение…")
        self.setMinimumHeight(59)
        self.setMaximumHeight(130)
        self.setTabChangesFocus(True)
        self.textChanged.connect(self.adjust_height)

    def adjust_height(self):
        lines = max(1, int(self.document().documentLayout().documentSize().height()))
        self.setFixedHeight(59 if lines == 1 else min(130, lines * 23 + 53))

    def keyPressEvent(self, e):
        if (
            e.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not e.modifiers() & Qt.ShiftModifier
        ):
            self.submit.emit()
            e.accept()
            return
        super().keyPressEvent(e)


class Toast(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._progress = 0.0
        self.message = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.anim = QPropertyAnimation(self, b"progress", self)
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def get_progress(self):
        return self._progress

    def set_progress(self, p):
        self._progress = p
        self.update()

    progress = Property(float, get_progress, set_progress)

    def show_message(self, text):
        self.message = text
        self.setGeometry(
            max(12, self.parent().width() - 600),
            self.parent().height() - 66,
            min(560, self.parent().width() - 24),
            46,
        )
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setDuration(0 if reduced() else 180)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(3500)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._progress)
        p.setBrush(QColor("#2B3B51"))
        p.setPen(QPen(QColor("#536D92"), 1))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 10, 10)
        p.setFont(font(13))
        p.setPen(QColor(FG))
        p.drawText(
            self.rect().adjusted(18, 8, -18, -8),
            Qt.AlignVCenter | Qt.TextWordWrap,
            self.message,
        )
