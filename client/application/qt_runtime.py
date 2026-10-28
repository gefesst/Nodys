"""Prepare macOS Qt plugin visibility immediately before QApplication startup."""
import os
from pathlib import Path
import stat
import sys


def prepare_platform_plugins():
    if sys.platform != 'darwin':
        return
    from PySide6.QtCore import QLibraryInfo
    directory = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath))/'platforms'
    for path in directory.glob('*.dylib'):
        flags = path.stat().st_flags
        if flags & stat.UF_HIDDEN:
            os.chflags(path, flags & ~stat.UF_HIDDEN)


def prepare_application_fonts(app):
    """Offscreen Windows has no native font database; use installed OS fonts."""
    if sys.platform != 'win32' or app.platformName() not in ('offscreen', 'minimal'):
        return
    from PySide6.QtGui import QFontDatabase
    directory = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    for name in ('arial.ttf', 'arialbd.ttf', 'segoeui.ttf', 'segoeuib.ttf'):
        path = directory / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
