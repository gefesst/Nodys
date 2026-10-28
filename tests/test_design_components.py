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

    def test_profile_sections_do_not_submit_hidden_password_or_profile_drafts(self):
        from ui.profile_page import ProfilePage
        page = ProfilePage('alice','Alice')
        page.ctx = SimpleNamespace(avatar='saved-avatar')
        sent = []
        page.start_request = lambda payload, callback: sent.append((payload,callback))
        page.show_section("password")
        page.save_changes()
        self.assertEqual(sent, [])
        page.nickname_edit.setText('Unsubmitted name')
        page.avatar_path = 'unsubmitted-avatar'
        page.password_edit.setText('new-password')
        page.current_password_edit.setText('current-password')
        page.show_section('password')
        page.save_changes()
        self.assertEqual(sent[-1][0]['nickname'],'Alice')
        self.assertEqual(sent[-1][0]['avatar'],'saved-avatar')
        self.assertEqual(sent[-1][0]['password'],'new-password')
        sent[-1][1]({'status':'error','message':'test rejection'})
        page.show_section('edit')
        page.save_changes()
        self.assertEqual(sent[-1][0]['password'],'')
        self.assertEqual(sent[-1][0]['current_password'],'')
        self.assertEqual(sent[-1][0]['nickname'],'Unsubmitted name')
        page.close()

    def test_late_preferred_channel_does_not_override_manual_selection(self):
        from ui.channels_page import ChannelsPage
        from unittest.mock import Mock
        callbacks=[]
        selected=[2]
        page=SimpleNamespace(_alive=True,_loading_channels=False,ctx=SimpleNamespace(login='alice'),
            _channels_loaded_once=True,_channel_navigation_revision=1,
            start_request=lambda payload,callback:callbacks.append(callback),
            _active_channel_id=lambda:selected[0],_apply_channel_header=Mock(),
            render_channels=Mock(),_apply_channel_permissions_ui=Mock(),
            main_stack=SimpleNamespace(currentWidget=lambda:'settings'),
            placeholder_page='placeholder',open_channel=Mock(),show_toast=Mock())
        ChannelsPage.load_channels(page,force_refresh=True,preferred_channel_id=2)
        selected[0]=1
        page._channel_navigation_revision+=1
        callbacks[0]({'status':'ok','channels':[{'id':1,'name':'Owner'},{'id':2,'name':'Member'}]})
        self.assertEqual(page.active_channel['id'],1)
        page.open_channel.assert_not_called()

    def test_only_latest_channel_list_reply_applies(self):
        from ui.channels_page import ChannelsPage
        from unittest.mock import Mock
        callbacks=[]
        page=SimpleNamespace(_alive=True,_loading_channels=False,ctx=SimpleNamespace(login='alice'),
            _channels_loaded_once=True,
            start_request=lambda payload,callback:callbacks.append(callback),
            _active_channel_id=lambda:1,_apply_channel_header=Mock(),
            render_channels=Mock(),_apply_channel_permissions_ui=Mock(),
            main_stack=SimpleNamespace(currentWidget=lambda:'settings'),
            placeholder_page='placeholder',open_channel=Mock(),show_toast=Mock())
        ChannelsPage.load_channels(page,force_refresh=True)
        ChannelsPage.load_channels(page,force_refresh=True)
        callbacks[1]({'status':'ok','channels':[{'id':1,'name':'Current'}]})
        callbacks[0]({'status':'ok','channels':[{'id':1,'name':'Outdated'}]})
        self.assertEqual(page.active_channel['name'],'Current')
