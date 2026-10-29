"""Keyboard-accessible context menu contained by the application window."""
from shiboken6 import isValid
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QPushButton, QWidget, QStyle, QStyleOptionButton, QStylePainter


class MenuButton(QPushButton):
    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        # Retain keyboard focus, but render the approved highlight instead of
        # the platform's dotted rectangle inside the custom menu.
        option.state &= ~QStyle.State_HasFocus
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_PushButton, option)


class ActionMenu(QFrame):
    def __init__(self, owner, danger=False, anchor_right=False):
        super().__init__(owner.window())
        self.setObjectName('InlineActionMenu')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedWidth(230)
        self.setStyleSheet('QFrame#InlineActionMenu {background:#253142;border:1px solid #485B76;border-radius:12px;}')
        self.box=QVBoxLayout(self);self.box.setContentsMargins(8,8,8,8);self.box.setSpacing(0)
        self.danger=danger
        self.anchor_right=anchor_right
        self.preferred_position=None
        self.buttons=[]
        self.previous_focus=None
        self.hide()

    def addAction(self, text, callback):
        button=MenuButton(text,self);button.setFixedHeight(40)
        button.setAttribute(Qt.WA_MacShowFocusRect,False)
        button.setProperty('keyboardFocus',False)
        color='#FFA7AE' if self.danger else '#EDF2FA'
        button.setStyleSheet('QPushButton {text-align:left;padding:0 8px;border:0;border-radius:6px;background:transparent;font-size:13px;font-weight:400;color:'+color+';} QPushButton:hover,QPushButton[keyboardFocus="true"] {background:#3A4D67;}')
        def activate():
            self.close()
            callback()
        button.clicked.connect(activate)
        self.box.addWidget(button);self.buttons.append(button)
        return button

    def popup(self, global_point):
        self.previous_focus=QApplication.focusWidget()
        self.setFixedHeight(18+40*len(self.buttons))
        self.preferred_position=self.parentWidget().mapFromGlobal(global_point)
        self.right_gap=self.parentWidget().width()-self.preferred_position.x()-self.width()
        self.move(self.preferred_position)
        self._clamp()
        QApplication.instance().installEventFilter(self)
        self.show();self.raise_()
        if self.buttons:self.buttons[0].setFocus(Qt.OtherFocusReason)

    def _clamp(self):
        host=self.parentWidget()
        point=self.preferred_position
        x=host.width()-self.width()-self.right_gap if self.anchor_right else point.x()
        self.move(max(88,min(x,host.width()-self.width()-12)),
                  max(42,min(point.y(),host.height()-self.height()-12)))

    def eventFilter(self, watched, event):
        if not isValid(self):
            return False
        if event.type()==QEvent.FocusIn and watched in self.buttons:
            if event.reason() in (Qt.TabFocusReason,Qt.BacktabFocusReason,Qt.ShortcutFocusReason):
                watched.setProperty('keyboardFocus',True)
            elif event.reason()==Qt.MouseFocusReason:
                watched.setProperty('keyboardFocus',False)
            watched.style().unpolish(watched);watched.style().polish(watched)
            watched.update()
        if event.type()==QEvent.FocusOut and watched in self.buttons:
            watched.setProperty('keyboardFocus',False)
            watched.style().unpolish(watched);watched.style().polish(watched)
            watched.update()
        if event.type()==QEvent.KeyPress and self.isVisible():
            if event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
                focused=watched if watched in self.buttons else QApplication.focusWidget()
                if focused in self.buttons:focused.click()
                return True
            if event.key()==Qt.Key_Escape:
                self.close();return True
            if event.key() in (Qt.Key_Up,Qt.Key_Down):
                current=QApplication.focusWidget()
                index=self.buttons.index(current) if current in self.buttons else 0
                button=self.buttons[(index+(1 if event.key()==Qt.Key_Down else -1))%len(self.buttons)]
                for item in self.buttons:
                    item.setProperty('keyboardFocus',item is button)
                    item.style().unpolish(item);item.style().polish(item)
                    item.update()
                button.setFocus(Qt.TabFocusReason)
                return True
        if event.type()==QEvent.MouseButtonPress and self.isVisible():
            if isinstance(watched,QWidget) and watched is not self and not self.isAncestorOf(watched):
                self.close()
        if watched is self.parentWidget():
            if event.type()==QEvent.Resize:self._clamp()
            elif event.type() in (QEvent.WindowDeactivate,QEvent.Close,QEvent.Hide):self.close()
        return super().eventFilter(watched,event)

    def closeEvent(self,event):
        QApplication.instance().removeEventFilter(self)
        try:
            if self.previous_focus is not None:self.previous_focus.setFocus(Qt.OtherFocusReason) if self.previous_focus.isVisible() and self.previous_focus.isEnabled() else None
        except RuntimeError:
            pass
        super().closeEvent(event)
