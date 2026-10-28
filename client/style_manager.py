"""One theme for all pages; legacy callers may still pass page names."""
from pathlib import Path
from ui.design import tokens


def load_styles(*names):
    text = (Path(__file__).parent/'styles/nodus.qss').read_text(encoding='utf-8')
    for name, value in vars(tokens).items():
        if name.isupper():
            text = text.replace('@'+name+'@', str(value))
    return text


def apply_app_styles(app, *names):
    app.setStyleSheet(load_styles())


def apply_widget_styles(widget, *names):
    widget.setStyleSheet(load_styles())
