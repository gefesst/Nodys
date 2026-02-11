import os


def _read_file(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_styles(*names: str) -> str:
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles")
    chunks = []
    for name in names:
        chunks.append(_read_file(os.path.join(base_dir, f"{name}.qss")))
    return "\n\n".join([c for c in chunks if c])


def apply_app_styles(app, *names: str):
    app.setStyleSheet(load_styles(*names))


def apply_widget_styles(widget, *names: str):
    widget.setStyleSheet(load_styles(*names))
