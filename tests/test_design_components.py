"""Regression checks for the integrated theme and bounded audio counters."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))


class AudioDiagnosticsTests(unittest.TestCase):
    def test_status_flags_and_callback_counters(self):
        from audio.diagnostics import AudioDiagnostics

        diagnostics = AudioDiagnostics()
        for kind, status in [
            ("capture", SimpleNamespace(input_overflow=True)),
            ("playback", SimpleNamespace(output_underflow=True)),
        ]:
            started = diagnostics.begin(kind, status)
            diagnostics.end(kind, started)
        snapshot = diagnostics.snapshot()
        self.assertEqual(snapshot["input_overflows"], 1)
        self.assertEqual(snapshot["output_underflows"], 1)
        self.assertEqual(snapshot["capture_callbacks"], 1)
        self.assertEqual(snapshot["playback_callbacks"], 1)
        self.assertNotIn("audio", snapshot)
        snapshot["input_overflows"] = 99
        self.assertEqual(diagnostics.snapshot()["input_overflows"], 1)


class DesignGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from application.qt_runtime import prepare_platform_plugins

        prepare_platform_plugins()
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_theme_does_not_clip_navigation_or_icon_buttons(self):
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        from ui.design.shell import NavButton
        from ui.design.widgets import Button
        from style_manager import load_styles

        window = QWidget()
        layout = QVBoxLayout(window)
        nav = NavButton("Друзья", "users")
        send = Button("", "send", True)
        layout.addWidget(nav)
        layout.addWidget(send)
        layout.addStretch()
        window.setStyleSheet(load_styles("main"))
        window.resize(150, 250)
        window.show()
        self.app.processEvents()
        self.assertGreaterEqual(nav.height(), 64)
        self.assertGreaterEqual(send.height(), 40)
        window.close()

    def test_call_controls_toggle_real_callbacks_without_repolishing(self):
        from ui.call_window import ActiveCallWindow
        mic, sound = [], []
        window = ActiveCallWindow('alice','bob',on_mic_toggle=mic.append,on_sound_toggle=sound.append)
        window._mic_clicked()
        window._sound_clicked()
        self.assertEqual(mic,[False])
        self.assertEqual(sound,[False])
        self.assertTrue(window.btn_mic.primary)
        window._mic_clicked()
        self.assertEqual(mic,[False,True])
        window.close()
