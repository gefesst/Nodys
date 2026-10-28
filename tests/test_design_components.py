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

    def test_resize_targets_follow_all_edges_without_covering_content(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QWidget
        from ui.design.shell import create_resize_handles, position_resize_handles

        window = QWidget()
        window.resize_handles = create_resize_handles(window)
        for width, height in ((1120, 620), (1280, 780), (1440, 900)):
            window.resize(width, height)
            position_resize_handles(window)
            for point in (QPoint(0, 0), QPoint(width - 1, height - 1),
                          QPoint(0, height // 2), QPoint(width // 2, 0),
                          QPoint(width - 1, height // 2), QPoint(width // 2, height - 1)):
                self.assertTrue(any(h.geometry().contains(point) for h in window.resize_handles))
            self.assertFalse(any(h.geometry().contains(window.rect().center())
                                 for h in window.resize_handles))
        window.close()

    def test_resize_fallback_preserves_minimum_and_opposite_corner(self):
        from PySide6.QtCore import Qt, QPoint, QPointF
        from PySide6.QtWidgets import QWidget
        from ui.design.shell import ResizeHandle

        window = QWidget()
        window.setMinimumSize(400, 300)
        window.setGeometry(100, 100, 600, 500)
        handle = ResizeHandle(window, Qt.TopEdge | Qt.LeftEdge, Qt.SizeFDiagCursor)
        handle.drag_origin = QPoint(100, 100)
        handle.drag_geometry = window.geometry()
        event = SimpleNamespace(globalPosition=lambda: QPointF(900, 900), accept=lambda: None)
        handle.mouseMoveEvent(event)
        self.assertEqual(window.size().width(), 400)
        self.assertEqual(window.size().height(), 300)
        self.assertEqual(window.geometry().bottomRight(), handle.drag_geometry.bottomRight())
        handle.mouseReleaseEvent(event)
        self.assertIsNone(handle.drag_origin)
        window.close()

    def test_voice_tiles_reflow_and_clear_all_participants(self):
        from ui.channels_page import ChannelsPage
        page=ChannelsPage()
        page._voice_participants=[{'login':str(i),'nickname':'Участник '+str(i)} for i in range(5)]
        page.main_stack.setCurrentWidget(page.channel_page)
        page.channel_inner_stack.setCurrentIndex(1)
        page.show()
        for width in (1032,1192,1352):
            page.resize(width,740)
            self.app.processEvents()
            page._render_voice_participants()
            self.assertEqual(page.voice_members_layout.count(),5)
            self.assertLessEqual(page._voice_columns,3)
            for i in range(5):
                self.assertEqual(page.voice_members_layout.itemAt(i).widget().height(),225)
        page._voice_participants=[]
        page._render_voice_participants()
        self.assertEqual(page.voice_members_layout.count(),1)
        page.close()

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

    def test_quick_switch_repeated_filtering_and_target_selection(self):
        from PySide6.QtWidgets import QWidget
        from unittest.mock import Mock
        from ui.design.quick_switch import QuickSwitch
        main=QWidget()
        main.friends_page=SimpleNamespace(_friends_data=[{'login':'alice','nickname':'Alice'}])
        main.channels_page=SimpleNamespace(channels=[{'id':1,'name':'Team'}],open_channel=Mock())
        main.chats_page=SimpleNamespace(open_chat=Mock())
        main.show_channels=Mock()
        main.show_chats=Mock()
        dialog=QuickSwitch(main)
        for _ in range(100):
            dialog.query.setText('no match')
            self.assertEqual(dialog.model.rowCount(),0)
            dialog.query.setText('Team')
            self.assertEqual(dialog.model.rowCount(),1)
            self.app.processEvents()
        dialog.open_selected()
        main.channels_page.open_channel.assert_called_once_with({'id':1,'name':'Team'})
        dialog.close()
        main.close()

    def test_all_svg_assets_render_after_repeated_collection(self):
        import gc
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QImage, QPainter
        from ui.design.widgets import ASSETS, icon, ICONS
        # Exercise initial parsing, cache hits, and QObject lifetime together.
        image = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
        for repeat in range(3):
            for path in ASSETS.glob('*.svg'):
                image.fill(Qt.transparent)
                painter = QPainter(image)
                try:
                    icon(painter, path.stem, QRectF(0, 0, 32, 32), '#ACB9CC')
                finally:
                    painter.end()
                self.assertTrue(ICONS[(path.stem, '#ACB9CC')].isValid())
                self.assertTrue(any(image.pixelColor(x,y).alpha() for y in range(32) for x in range(32)))
            gc.collect()

    def test_motion_tracks_late_fields_without_application_global_filter(self):
        from PySide6.QtWidgets import QWidget, QLineEdit, QVBoxLayout
        from PySide6.QtCore import QEvent, QChildEvent
        from PySide6.QtGui import QFocusEvent
        from ui.design.motion import MotionFilter, FocusRing
        window = QWidget()
        layout = QVBoxLayout(window)
        controller = MotionFilter(window)
        controller.watch(window)
        field = QLineEdit(window)
        layout.addWidget(field)
        self.app.sendEvent(window, QChildEvent(QEvent.ChildPolished, field))
        self.app.sendEvent(field, QFocusEvent(QEvent.FocusIn))
        self.assertIsInstance(field._focus_ring, FocusRing)
        self.assertEqual(field._focus_ring.animation.endValue(), 1.0)
        self.app.sendEvent(field, QFocusEvent(QEvent.FocusOut))
        self.assertEqual(field._focus_ring.animation.endValue(), 0.0)
        window.close()
