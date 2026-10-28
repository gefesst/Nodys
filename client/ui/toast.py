"""Shared nonmodal animated notification, retained API for existing pages."""
from ui.design.widgets import Toast


class InlineToast:
    def __init__(self,parent,*,object_name='InlineToast',min_width=220,max_width=560,horizontal_margin=12,bottom_margin=16):
        self.parent=parent
        self.label=Toast(parent)
        self.max_width=max_width
        self.margin=horizontal_margin
        self.bottom=bottom_margin
    def is_visible(self):return self.label.isVisible()
    def hide(self):self.label.hide()
    def show(self,text,msec=1800):
        if not text:return
        self.label.show_message(text)
        self.label.timer.start(max(700,int(msec)))
        self.reposition()
    def reposition(self):
        if not self.label.isVisible():return
        width=min(self.max_width,max(160,self.parent.width()-2*self.margin))
        self.label.setGeometry((self.parent.width()-width)//2,self.parent.height()-74-self.bottom,width,74)
