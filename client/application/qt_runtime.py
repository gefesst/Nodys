"""Prepare macOS Qt plugin visibility immediately before QApplication startup."""
import os
from pathlib import Path
import stat
import sys


def prepare_platform_plugins():
    if sys.platform != 'darwin':
        return
    from PySide6.QtCore import QLibraryInfo
    directory = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath))
    # Hidden plugin binaries are skipped by Qt on macOS. Image-format plugins
    # are needed for SVG controls and uploaded JPEG/WebP avatars as well.
    for path in directory.rglob('*.dylib'):
        flags = path.stat().st_flags
        if flags & stat.UF_HIDDEN:
            os.chflags(path, flags & ~stat.UF_HIDDEN)
    # Populate the image factory while all plugins are visible, before SVG
    # rendering can trigger a partial first scan of that same factory.
    from PySide6.QtGui import QImageReader
    QImageReader.supportedImageFormats()


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
