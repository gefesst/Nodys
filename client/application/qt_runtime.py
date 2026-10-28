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
