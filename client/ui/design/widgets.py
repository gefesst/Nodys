from collections import OrderedDict
from pathlib import Path
import time
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
    QEvent,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QFont,
    QFontMetricsF,
    QPen,
    QTextLayout,
    QTextOption,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QSizePolicy,
    QApplication,
    QPushButton,
    QStyledItemDelegate,
    QStyle,
    QPlainTextEdit,
    QLineEdit,
    QListView,
    QAbstractItemView,
    QComboBox,
    QProxyStyle,
)
from PySide6.QtSvg import QSvgRenderer
from .motion import reduced
from .tokens import ACC, PRIMARY, FG, SUB, MUT, EDGE, GREEN, RED, BUTTON_BG, BUTTON_HOVER, BUTTON_PRESSED

ASSETS = Path(__file__).parent / "assets"
COMBO_ARROW_STYLE = (
    ' QComboBox::down-arrow {image:url("'
    + (ASSETS / "chevron-down.svg").as_posix()
    + '");width:14px;height:14px;}'
)
ICONS = {}


class SearchField(QLineEdit):
    """Identical optical inset on every search field, independent of Qt actions."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextMargins(28, 0, 0, 0)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        icon(painter, "search", QRectF(16, (self.height()-18)/2, 18, 18), SUB)


class SelectorStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)


class SelectorDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(super().sizeHint(option, index).width() + 44, 40)

    def paint(self, painter, option, index):
        painter.save()
        rect = QRectF(option.rect).adjusted(4, 2, -4, -2)
        selected = index.row() == self.parent().currentIndex()
        active = bool(option.state & (QStyle.State_Selected | QStyle.State_MouseOver))
        enabled = bool(index.flags() & Qt.ItemIsEnabled)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        if active and enabled:
            painter.setBrush(QColor("#4E5058"))
            painter.drawRoundedRect(rect, 7, 7)
        elif selected:
            painter.setBrush(QColor("#404249"))
            painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor(FG if enabled else MUT))
        painter.setFont(option.font)
        text_rect = rect.adjusted(12, 0, -34, 0)
        text = option.fontMetrics.elidedText(str(index.data() or ""), Qt.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        if selected:
            painter.setPen(QPen(QColor(ACC), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x, y = rect.right() - 19, rect.center().y()
            path = QPainterPath(); path.moveTo(x-4, y); path.lineTo(x-1, y+3); path.lineTo(x+5, y-4)
            painter.drawPath(path)
        painter.restore()


class ScrollSafeComboBox(QComboBox):
    """Shared selector with consistent rows and no accidental wheel changes."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._selector_style = SelectorStyle("Fusion")
        self._selector_style.setParent(self)
        self.setStyle(self._selector_style)
        view = QListView(self)
        view.setMouseTracking(True)
        view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setStyleSheet("QListView {background:#2B2D31;border:1px solid #41434A;border-radius:10px;padding:6px;outline:0;} ")
        self.setView(view)
        self.setItemDelegate(SelectorDelegate(self))
        self.setMaxVisibleItems(7)
        self.setAttribute(Qt.WA_MacShowFocusRect, False)
        self.setStyleSheet("QComboBox {min-height:24px;max-height:24px;padding:10px 40px 10px 14px;background:#1E1F22;border:1px solid #41434A;border-radius:10px;} QComboBox:hover {border-color:#62656E;} QComboBox:focus,QComboBox:on {border-color:#B6BCFF;} QComboBox::drop-down {border:0;width:32px;}" + COMBO_ARROW_STYLE)

    def showPopup(self):
        popup = self.view().window()
        popup.setAttribute(Qt.WA_TranslucentBackground)
        popup.setAutoFillBackground(False)
        popup.setStyleSheet("QFrame {background:transparent;border:0;}")
        popup.clearMask()
        super().showPopup()

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class ElidedLabel(QLabel):
    """Keep the full name accessible while fitting the available header width."""
    def __init__(self,text='',parent=None):
        super().__init__(text,parent)
        self.full_text=text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.setToolTip(text);self.setAccessibleName(text)

    def setText(self,text):
        self.full_text=text
        self.setToolTip(text);self.setAccessibleName(text)
        self._fit()

    def _fit(self):
        super().setText(self.fontMetrics().elidedText(self.full_text,Qt.ElideRight,max(0,self.contentsRect().width())))

    def resizeEvent(self,event):
        super().resizeEvent(event);self._fit()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange,QEvent.StyleChange) and hasattr(self,'full_text'):
            self._fit()


class MessageList(QListView):
    """Preserve a visible row after width-dependent message reflow."""

    def __init__(self):
        super().__init__()
        self.anchor = 0
        self.reflow = QTimer(self)
        self.reflow.setSingleShot(True)
        self.reflow.setInterval(100)
        self.reflow.timeout.connect(self.restore_anchor)
        self.verticalScrollBar().actionTriggered.connect(lambda _:self.reflow.stop())
        self.verticalScrollBar().sliderPressed.connect(self.reflow.stop)
        self.verticalScrollBar().setSingleStep(24)

    def wheelEvent(self,event):
        self.reflow.stop()
        super().wheelEvent(event)

    def resizeEvent(self, event):
        from PySide6.QtCore import QPoint

        index = self.indexAt(QPoint(80, 12))
        if index.isValid():
            self.anchor = index.row()
            self.anchor_offset = self.visualRect(index).top()
        bar = self.verticalScrollBar()
        self.anchor_bottom = bar.maximum() - bar.value() < 20
        super().resizeEvent(event)
        if event.size().width()!=event.oldSize().width():
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
        self.setLayoutMode(QListView.SinglePass)


def font(px=15, bold=False):
    f = QFont("Arial")
    f.setPixelSize(px)
    f.setWeight(QFont.DemiBold if bold else QFont.Normal)
    return f


def icon(p, name, rect, color=SUB):
    key = (name, color)
    if key not in ICONS:
        file = ASSETS / (name + ".svg")
        data = file.read_text().replace("#B5BAC1", color)
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
    p.setBrush(QColor("#4A485E" if own else "#465772"))
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
        p.setPen(QPen(QColor("#1E1F22"), 2))
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
        self._keyboard_focus = False
        self.setAttribute(Qt.WA_MacShowFocusRect,False)
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

    def focusInEvent(self,event):
        self._keyboard_focus=event.reason() in (Qt.TabFocusReason,Qt.BacktabFocusReason,Qt.ShortcutFocusReason)
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self,event):
        super().focusOutEvent(event)
        self.update()

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
        flat = bool(self.property("flat"))
        filled_primary = self.primary and not flat
        # Selected flat navigation controls keep a dark surface under their
        # accent icon. Only filled primary actions use the light blue surface.
        a = QColor(PRIMARY if filled_primary else "#454B78" if self.primary else BUTTON_BG)
        b = QColor("#4752C4" if filled_primary else BUTTON_BG if flat else BUTTON_HOVER)
        if self.property("danger"):
            a, b = QColor("#492D39"), QColor("#603748")
        t = self._hover
        bg = QColor.fromRgbF(
            a.redF() * (1 - t) + b.redF() * t,
            a.greenF() * (1 - t) + b.greenF() * t,
            a.blueF() * (1 - t) + b.blueF() * t,
        )
        if self.isDown():
            bg = QColor("#3D2530" if self.property("danger") else "#3C45A5" if filled_primary else BUTTON_PRESSED)
        if not self.isEnabled():
            bg = QColor("#2B2D31")
        if flat and not self.primary and not self._hover and not self.isDown():
            bg.setAlpha(0)
        keyboard_focus = self.hasFocus() and self._keyboard_focus
        # Filled controls need no decorative border; keyboard focus keeps
        # one contour without a second inset rectangle.
        p.setPen(QPen(QColor(ACC), 2) if keyboard_focus else Qt.NoPen)
        p.setBrush(bg)
        inset = 1.0 if keyboard_focus else 0.5
        p.drawRoundedRect(QRectF(inset, inset, self.width() - 2*inset, self.height() - 2*inset),
                          9.5-inset, 9.5-inset)
        color = ACC if self.primary and self.property("flat") else "#FFFFFF" if self.primary else SUB if self.property("flat") else FG
        if self.property("danger"):
            color = RED
        if self.property("text_color"):
            color = self.property("text_color")
        if not self.isEnabled():
            color = "#80848E"
        p.setFont(self.font())
        available=max(0,self.width()-24-(26 if self.icon_name and self.text() else 0))
        label=p.fontMetrics().elidedText(self.text(),Qt.ElideRight,available)
        width = p.fontMetrics().horizontalAdvance(label)
        # The 8 px gap belongs between an icon and its label. Reserving it
        # for icon-only buttons shifts every symbol 4 px left of its centre.
        total = width + ((18 + (8 if self.text() else 0)) if self.icon_name else 0)
        x = 12 if self.property("align_left") else (self.width() - total) / 2
        if self.icon_name:
            symbol_color = ACC if self.icon_name == "phone" and self.isEnabled() and not self.primary and not self.property("danger") else color
            icon(p, self.icon_name, QRectF(x, (self.height() - 18) / 2, 18, 18), symbol_color)
            x += 26
        p.setPen(QColor(color))
        p.drawText(QRectF(x, 0, width + 3, self.height()), Qt.AlignVCenter, label)


def set_voice_button_state(button, symbol, enabled, label=None):
    """One visual state for channel, call and dock controls."""
    off=not enabled
    button.icon_name=symbol+"-off" if off else symbol
    button.primary=False
    button.setProperty("danger",off)
    button.setProperty("off","true" if off else "false")
    button.setCheckable(True)
    button.setChecked(off)
    noun="Микрофон" if symbol=="mic" else "Звук"
    if label is not None:button.setText(label)
    button.setAccessibleName(noun+(" выключен" if off else " включён"))
    button.setToolTip(("Включить " if off else "Выключить ")+noun.lower())
    button.update()


class RoundCallButton(Button):
    def __init__(self, label, symbol, danger=False):
        super().__init__(label, symbol)
        self.setFixedSize(52,52)
        self.setProperty('danger',danger)
        self.setAccessibleName(label)

    def sizeHint(self):
        return QSize(52, 52)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        danger=bool(self.property('danger'))
        off=self.property('off')=='true'
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#704151' if danger and self._hover else '#50313F' if danger else BUTTON_HOVER if self._hover else BUTTON_BG))
        painter.drawEllipse(QRectF(0,0,52,52))
        icon(painter,self.icon_name,QRectF(15,15,22,22),RED if danger or off else FG)
        if off and not self.icon_name.endswith("-off"):
            painter.setPen(QPen(QColor(RED),1.65));painter.drawLine(15,16,37,38)
        if self.hasFocus() and self._keyboard_focus:
            painter.setBrush(Qt.NoBrush);painter.setPen(QPen(QColor(ACC),2));painter.drawEllipse(QRectF(1,1,50,50))


class DialogDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        from ui.avatar_widget import AvatarLabel

        self._avatar_helper = AvatarLabel(38)
        self._avatar_helper.hide()
        self._avatars = OrderedDict()

    def sizeHint(self, o, i):
        view=self.parent()
        height=view.viewport().height() if view is not None else 410
        return QSize(300, min(76, max(64, height//5)))

    def paint(self, p, o, index):
        d = index.data(Qt.UserRole)
        r = o.rect.adjusted(0, 3, 0, -5)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        selected = bool(o.state & QStyle.State_Selected)
        hover = bool(o.state & QStyle.State_MouseOver)
        if selected or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#404249" if selected else "#35373C"))
            p.drawRoundedRect(r, 11, 11)
        if selected:
            p.setBrush(QColor(ACC))
            p.drawRoundedRect(QRectF(r.left(), r.center().y() - 19, 3, 38), 1.5, 1.5)
        n = d.get("nickname", d["login"])
        ini = self._avatar_helper._initials(n)
        avatar(p, r.left() + 14, r.center().y() - 19, ini, 38, d.get("online", False))
        if d.get("avatar"):
            key = (d["avatar"], d["login"], bool(d.get("online")))
            if key not in self._avatars:
                self._avatar_helper.set_avatar(d["avatar"], d["login"], n)
                self._avatar_helper.set_online(bool(d.get("online")))
                self._avatars[key] = self._avatar_helper.grab()
                if len(self._avatars) > 128:
                    self._avatars.popitem(last=False)
            p.drawPixmap(r.left() + 14, r.center().y() - 19, self._avatars[key])
        p.setFont(font(14, True))
        title = p.fontMetrics().elidedText(n, Qt.ElideRight, r.width() - 126)
        draw_text(p, r.left() + 67, r.center().y() - 9, title, 14, FG, True)
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
        draw_text(p, r.left() + 67, r.center().y() + 15, preview, 12, SUB)
        timestamp = summary.get("timestamp", "")
        if timestamp:
            from datetime import datetime, timedelta

            try:
                date = datetime.fromisoformat(timestamp)
                stamp = (
                    date.strftime("%H:%M")
                    if date.date() == datetime.now().date()
                    else "Вчера"
                    if date.date() == datetime.now().date() - timedelta(days=1)
                    else date.strftime("%d.%m")
                )
                p.setFont(font(11))
                stamp_width = p.fontMetrics().horizontalAdvance(stamp)
                draw_text(p, r.right() - 18 - stamp_width, r.center().y() - 9, stamp, 11, MUT)
            except (ValueError, TypeError):
                pass
        count = int(d.get("unread_count", 0) or 0)
        if count:
            badge_width = 20 if count < 10 else 28
            badge = QRectF(r.right() - 14 - badge_width, r.center().y() + 6, badge_width, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(PRIMARY))
            p.drawRoundedRect(badge, 10, 10)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(font(11, True))
            p.drawText(badge, Qt.AlignCenter, str(min(count, 99)))
        p.restore()


class MessageDelegate(QStyledItemDelegate):
    def __init__(self, view, me, own_name=None):
        super().__init__(view)
        self.view = view
        self.me = me
        self.own_name = own_name or (lambda: me)
        from ui.avatar_widget import AvatarLabel
        self._avatar_helper = AvatarLabel(32, view)
        self._avatar_helper.hide()
        self._avatars = OrderedDict()
        self.cache = OrderedDict()
        self.image_cache = None
        self.paint_count = 0
        self.paint_ns = []
        self.highlight_id = None
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

    def footer(self, m):
        text = ('изменено · ' if m.edited else '') + m.time
        width = QFontMetricsF(font(11)).horizontalAdvance(text)
        return text, width + (24 if m.author == self.me else 0)

    def image_size(self, m, width):
        from shared.attachments import is_image_attachment
        if not is_image_attachment(m.attachment):
            return (0, 0)
        image = self.image_cache.get(m.attachment) if self.image_cache else None
        available = max(126, min(420, width - 114))
        if image is None:
            return (available, available * .6)
        ratio = image.width() / max(1, image.height())
        w = min(available, 320 * ratio)
        return (w, w / ratio)

    def media_offset(self, m, width):
        height = self.image_size(m, width)[1]
        return height + 2 if height else 0

    def geometry(self, m, width):
        maxw = max(150, min(660, width - 90))
        from shared.attachments import is_image_attachment
        picture = is_image_attachment(m.attachment)
        if picture:
            maxw = max(100, min(maxw, self.image_size(m, width)[0]))
        key = (self.image_size(m, width), m.text, maxw, m.group, m.divider, m.unread_count, picture, m.link_text, m.edited, m.author == self.me, tuple(sorted(m.reply.items())) if m.reply else None, m.reactions)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        layout = QTextLayout(m.text, font(15))
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        formats = []
        from .message_links import link_spans
        for start, length, url in link_spans(m.link_text if m.link_text is not None else m.text):
            f = QTextLayout.FormatRange()
            f.start = start
            f.length = length
            f.format = QTextCharFormat()
            f.format.setForeground(QColor(ACC))
            f.format.setFontUnderline(True)
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
        if not m.text:
            y = 0
        bw = min(maxw, max(160 if m.edited else 100, natural + 32))
        if m.reply:
            bw = max(bw, min(maxw, 320))
        inline_time = layout.lineCount() == 1 and not (m.reply or m.edited or picture or m.reactions) and natural + 110 <= maxw
        if inline_time:
            bw = max(bw, natural + 110)
        if picture:
            bw = max(bw, self.image_size(m, width)[0])
        bh = y + (20 if inline_time else 30) + (50 if m.reply else 0) + self.media_offset(m, width)
        head = 42 if m.group and m.author != self.me else (12 if m.group else 0)
        head += 52 if m.divider else 0
        head += 40 if m.unread_count else 0
        # Leave room for the antialiased stroke even in consecutive bubbles.
        head += 2
        if m.reactions:
            bw = max(bw, min(maxw, 270 if m.edited else 220))
        columns = max(1, int((bw - 24) // 76))
        reaction_height = ((len(m.reactions) + columns - 1) // columns) * 30 if m.reactions else 0
        # Reactions share the footer with the time whenever the last row leaves room.
        last_count = (len(m.reactions) - 1) % columns + 1 if m.reactions else 0
        shared_footer = m.reactions and last_count * 76 + (self.footer(m)[1] + 12) <= bw - 24
        bh += reaction_height - (9 if shared_footer else 0)
        if picture and not m.text and not m.reactions and not m.edited:
            bh = self.image_size(m, width)[1] + (50 if m.reply else 0)
        height = head + bh + 10
        value = (layout, bw, bh, head, height)
        self.cache[key] = value
        if len(self.cache) > 600:
            self.cache.popitem(last=False)
        return value

    def bubble_x(self, message, width):
        bw = self.geometry(message, width)[1]
        return max(12, width - bw - 18) if message.author == self.me else 52

    def bubble_rect(self, message, width):
        _, bw, bh, head, _ = self.geometry(message, width)
        return QRectF(self.bubble_x(message, width), head, bw, bh)

    def reaction_rects(self, message, width):
        _, bw, bh, head, _ = self.geometry(message, width)
        columns = max(1, int((bw - 24) // 76))
        height = ((len(message.reactions)+columns-1)//columns)*30
        last_count = (len(message.reactions)-1)%columns+1 if message.reactions else 0
        shared = last_count*76 + (self.footer(message)[1] + 12) <= bw-24
        return [(reaction, QRectF(self.bubble_x(message, width) + 12 + (i % columns)*76,
                                 head + bh - height - (4 if shared else 17) + (i//columns)*30, 70, 26))
                for i, reaction in enumerate(message.reactions)]

    def reaction_at(self, message, width, point):
        return next((r[0] for r, rect in self.reaction_rects(message, width) if rect.contains(point)), None)

    def reply_at(self, message, width, point):
        if not message.reply or message.reply.get('deleted'):
            return None
        _, bw, _, head, _ = self.geometry(message, width)
        if QRectF(self.bubble_x(message, width) + 12, head + 8, bw - 24, 44).contains(point):
            return message.reply['id']
        return None

    def link_at(self, message, width, point):
        from .message_links import link_spans
        layout, _, _, head, _ = self.geometry(message, width)
        position = point - __import__('PySide6.QtCore', fromlist=['QPointF']).QPointF(self.bubble_x(message, width) + 16, head + 11 + (50 if message.reply else 0) + self.media_offset(message, width))
        for number in range(layout.lineCount()):
            line = layout.lineAt(number)
            if line.naturalTextRect().contains(position):
                cursor = line.xToCursor(position.x())
                for start, length, url in link_spans(message.link_text if message.link_text is not None else message.text):
                    if start <= cursor < start + length:
                        return url
        return None

    def sizeHint(self, o, i):
        m = i.data(Qt.UserRole)
        return QSize(
            0, int(self.geometry(m, max(350, self.view.viewport().width()))[-1])
        )

    @staticmethod
    def shape(x, y, w, h, tail, own=False):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), 14, 14)
        if tail:
            fin = QPainterPath()
            if own:
                fin.moveTo(x+w-13, y+h)
                fin.quadTo(x+w, y+h+1, x+w+7, y+h)
                fin.quadTo(x+w, y+h-4, x+w, y+h-15)
                fin.lineTo(x+w-13, y+h-15)
            else:
                fin.moveTo(x+13, y+h)
                fin.quadTo(x, y+h+1, x-7, y+h)
                fin.quadTo(x, y+h-4, x, y+h-15)
                fin.lineTo(x+13, y+h-15)
            fin.closeSubpath()
            path = path.united(fin)
        return path

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
        x = o.rect.x() + self.bubble_x(m, self.view.viewport().width())
        y = o.rect.y() + head
        unread_offset = 40 if m.unread_count else 0
        date_offset = head - 34
        if m.unread_count:
            count=m.unread_count
            noun='непрочитанное сообщение' if count%10==1 and count%100!=11 else 'непрочитанных сообщения' if count%10 in (2,3,4) and count%100 not in (12,13,14) else 'непрочитанных сообщений'
            label=f'{count} {noun}'
            p.setFont(font(12));label_width=p.fontMetrics().horizontalAdvance(label)
            center=self.view.viewport().width()/2;line_y=o.rect.y()+20
            p.setPen(QPen(QColor(ACC),1))
            p.drawLine(10,line_y,int(center-label_width/2-16),line_y)
            p.drawLine(int(center+label_width/2+16),line_y,self.view.viewport().width()-10,line_y)
            draw_text(p,center-label_width/2,o.rect.y()+24,label,12,ACC)
        if m.divider:
            p.setFont(font(11))
            label_width = p.fontMetrics().horizontalAdvance(m.date)
            center = o.rect.center().x()
            p.setPen(QPen(QColor(EDGE), 1))
            line_y = o.rect.y() + unread_offset + 22
            p.setBrush(QColor('#2B2D31'))
            p.setPen(QPen(QColor(EDGE), 1))
            date_rect = QRectF(center-label_width/2-12, line_y-15, label_width+24, 26)
            p.drawRoundedRect(date_rect, 13, 13)
            p.setPen(QColor(MUT))
            p.drawText(date_rect, Qt.AlignCenter, m.date)
        if m.group and not own:
            display_name = self.own_name() if own else m.name
            initials = self._avatar_helper._initials(display_name)
            avatar(
                p,
                o.rect.x() + 10,
                o.rect.y() + 2 + date_offset,
                initials,
                32,
                False,
                own,
            )
            if m.avatar:
                key = (m.avatar, m.author, display_name, self.view.devicePixelRatioF())
                if key not in self._avatars:
                    self._avatar_helper.setProperty("own_avatar", own)
                    self._avatar_helper.set_avatar(m.avatar, m.author, display_name)
                    self._avatars[key] = self._avatar_helper.pixmap()
                    if len(self._avatars) > 128:
                        self._avatars.popitem(last=False)
                else:
                    self._avatars.move_to_end(key)
                p.drawPixmap(o.rect.x()+10, o.rect.y()+2+date_offset, self._avatars[key])
            p.setFont(font(13, True))
            name = p.fontMetrics().elidedText(
                m.name, Qt.ElideRight, self.view.viewport().width() - 120
            )
            draw_text(
                p, x, o.rect.y() + 14 + date_offset, name, 13, ACC if own else FG, True
            )
        p.setBrush(QColor("#454B78" if own else "#383A40"))
        p.setPen(Qt.NoPen)
        if m.id == self.highlight_id:
            p.setPen(QPen(QColor(ACC), 2))
        following = index.model().index(index.row()+1).data(Qt.UserRole)
        tail = following is None or following.group or following.author != m.author
        p.drawPath(self.shape(x, y, bw, bh, tail, own))
        if m.reply:
            box = QRectF(x + 12, y + 8, bw - 24, 44)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#34394F'))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QPen(QColor(ACC), 2))
            p.drawLine(int(x+16), int(y+15), int(x+16), int(y+46))
            author = 'Вы' if m.reply['author'] == self.me else m.reply['author']
            p.setFont(font(12, True))
            title = p.fontMetrics().elidedText(author or 'Исходное сообщение', Qt.ElideRight, int(bw-52))
            draw_text(p, x+26, y+25, title, 12, ACC, True)
            p.setFont(font(12))
            quote = p.fontMetrics().elidedText(' '.join(m.reply['text'].split()), Qt.ElideRight, int(bw-52))
            draw_text(p, x+26, y+42, quote, 12, MUT)
        p.setPen(QColor(FG))
        layout.draw(
            p,
            __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(x + 16, y + 11 + (50 if m.reply else 0) + self.media_offset(m, self.view.viewport().width())),
        )
        from shared.attachments import is_image_attachment
        if is_image_attachment(m.attachment):
            box = QRectF(x, y + (50 if m.reply else 0), bw, self.image_size(m, self.view.viewport().width())[1])
            clip = self.shape(x, y, bw, bh, tail, own)
            p.save()
            p.setClipPath(clip, Qt.IntersectClip)
            p.fillRect(box, QColor('#232428'))
            image = self.image_cache.get(m.attachment) if self.image_cache else None
            if image is not None:
                size = image.size().scaled(box.size().toSize(), Qt.KeepAspectRatio)
                target = QRectF(box.center().x()-size.width()/2, box.center().y()-size.height()/2, size.width(), size.height())
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawImage(target, image)
            else:
                p.setPen(QColor(MUT))
                p.setFont(font(12))
                failed = self.image_cache and m.attachment['id'] in self.image_cache.errors
                p.drawText(box.adjusted(12, 8, -12, -8), Qt.AlignCenter | Qt.TextWordWrap,
                           'Не удалось показать изображение. Нажмите для просмотра.' if failed else 'Изображение…')
                if self.image_cache:
                    self.image_cache.ensure(m.attachment)
            p.restore()
        if is_image_attachment(m.attachment) and not m.text and not m.reactions and not m.edited:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 23, 180))
            p.drawRoundedRect(QRectF(x+bw-(78 if own else 57), y+bh-28, 70 if own else 49, 22), 11, 11)
        footer_text, footer_width = self.footer(m)
        draw_text(p, x + bw - 12 - footer_width, y + bh - 12, footer_text, 11, MUT)
        if own:
            icon(
                p,
                "double" if m.read else "check",
                QRectF(x + bw - 30, y + bh - 24, 16, 16),
                ACC if m.read else MUT,
            )
        for reaction, box in self.reaction_rects(m, self.view.viewport().width()):
            emoji, count, mine = reaction
            box.translate(o.rect.topLeft())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#5865A0' if mine else '#4B4F65'))
            p.drawRoundedRect(box, 13, 13)
            p.setPen(QColor(FG))
            p.setFont(font(15))
            p.drawText(box.adjusted(5, 0, -39, 0), Qt.AlignCenter, emoji)
            people = dict(m.reaction_people).get(emoji, ())
            if people and count <= 3:
                for number, (login, name, photo) in enumerate(people[:3]):
                    ax = box.x()+36+number*8
                    avatar(p, ax, box.y()+3, self._avatar_helper._initials(name or login), 20, False, False)
                    if photo:
                        key = (photo, login, name, 'reaction')
                        if key not in self._avatars:
                            self._avatar_helper.set_avatar(photo, login, name or login)
                            self._avatars[key] = self._avatar_helper.pixmap()
                            if len(self._avatars) > 128:
                                self._avatars.popitem(last=False)
                        pixmap = self._avatars[key]
                        if pixmap:
                            p.drawPixmap(QRectF(ax, box.y()+3, 20, 20).toRect(), pixmap)
            else:
                p.setFont(font(11, True))
                p.drawText(box.adjusted(32, 0, -4, 0), Qt.AlignCenter, str(count) if count < 1000 else '999+')
        p.restore()
        self.paint_count += 1
        if len(self.paint_ns) < 50000:
            self.paint_ns.append(time.perf_counter_ns() - started)


class Composer(QPlainTextEdit):
    submit = Signal()
    attachment_input = Signal(object)

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
        self.document().setDocumentMargin(0)
        # Keep the initial empty composer fixed; adjust_height grows it for text.
        # Raising maximumHeight here undoes setFixedHeight and lets the first
        # layout expand it before the deferred resize callback shrinks it again.
        self.setFixedHeight(44)
        self.setTabChangesFocus(True)
        self.textChanged.connect(self.adjust_height)
        self._resize_height_timer=QTimer(self)
        self._resize_height_timer.setSingleShot(True)
        self._resize_height_timer.timeout.connect(self.adjust_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width()!=event.oldSize().width() and hasattr(self,'_resize_height_timer'):
            self._resize_height_timer.start(0)

    def adjust_height(self):
        lines = max(1, int(self.document().documentLayout().documentSize().height()))
        self.setFixedHeight(min(130, max(44, lines * self.fontMetrics().lineSpacing() + 24)))

    def canInsertFromMimeData(self, source):
        from .attachment_input import is_attachment
        return is_attachment(source) or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if self.isReadOnly():
            return
        from .attachment_input import is_attachment
        if is_attachment(source):
            self.attachment_input.emit(source)
        else:
            super().insertFromMimeData(source)

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
        parent.installEventFilter(self)
        self.hide()

    def get_progress(self):
        return self._progress

    def set_progress(self, p):
        self._progress = p
        self.update()

    progress = Property(float, get_progress, set_progress)

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type()==QEvent.Resize:
            self.reposition()
        return super().eventFilter(watched,event)

    def reposition(self):
        self.setGeometry(
            max(12, self.parent().width() - 600),
            self.parent().height() - 66,
            min(560, self.parent().width() - 24),
            46,
        )
    def show_message(self, text):
        self.message = text
        self.reposition()
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
        p.setBrush(QColor("#404249"))
        p.setPen(QPen(QColor("#62656E"), 1))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 10, 10)
        p.setFont(font(13))
        p.setPen(QColor(FG))
        p.drawText(
            self.rect().adjusted(18, 8, -18, -8),
            Qt.AlignVCenter | Qt.TextWordWrap,
            self.message,
        )
