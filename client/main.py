# Preserve direct script entry points while sharing the wire protocol package.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from application.qt_runtime import prepare_platform_plugins, prepare_application_fonts
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app_window import AppWindow
from style_manager import apply_app_styles


def main():
    prepare_platform_plugins()
    app = QApplication(sys.argv)
    # User preference: one arrow across fields, buttons, dialogs and resize edges.
    # Qt owns this application-local override; no native cursor setters or timers.
    app.setOverrideCursor(Qt.ArrowCursor)
    app.setApplicationName("noda")
    app.setApplicationDisplayName("noda")
    from application.gui_gc import install as install_gui_gc
    install_gui_gc(app)
    prepare_application_fonts(app)
    apply_app_styles(app, "base", "auth", "main", "friends", "chats", "channels", "profile", "call")
    from ui.design.motion import install, watch
    install(app)
    w = AppWindow()
    watch(w)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
