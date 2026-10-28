"""Deterministic UI checks; optional when desktop dependencies are unavailable."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'client'))

@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Install desktop requirements for UI tests')
class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from application.qt_runtime import prepare_platform_plugins
        prepare_platform_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = patch.dict(os.environ, NODYS_CONFIG_DIR=self.folder.name)
        self.env.start(); self.addCleanup(self.env.stop)
        self.network = patch('network.NetworkThread.start')
        self.network.start(); self.addCleanup(self.network.stop)
        from user_context import UserContext
        UserContext().set_user(login='alice', nickname='Alice', avatar='',session_token='synthetic')
        from ui.channels_page import ChannelsPage
        self.page = ChannelsPage()
        self.addCleanup(self.page.close)

    def test_forms_survive_empty_poll(self):
        p = self.page
        p.start_request = lambda data, callback, **kw: callback({'status':'ok','channels':[]})
        for form, open_form in ((p.create_page,p.open_create_page),(p.join_page,p.open_join_page)):
            open_form(); p.load_channels(force_refresh=True)
            self.assertIs(p.main_stack.currentWidget(),form)

    def test_settings_are_scrollable(self):
        from PySide6.QtWidgets import QScrollArea
        node = self.page.settings_name_input
        while node is not None and not isinstance(node,QScrollArea):
            node = node.parentWidget()
        self.assertIsNotNone(node)

    def test_registration_error_inline(self):
        from register_window import RegisterWindow
        window = RegisterWindow()
        self.addCleanup(window.close)
        with patch('register_window.QMessageBox.warning') as modal:
            window.handle_register_response({'status':'error','message':'Логин уже существует'})
            modal.assert_not_called()
        self.assertEqual(window.status_label.text(),'Логин уже существует')

    def test_late_channel_response_is_ignored(self):
        pending = []
        with patch('utils.thread_safe_mixin.ThreadSafeMixin.start_request',
                   side_effect=lambda data, callback, *args: pending.append((data,callback))):
            self.page.open_channel({'id':1,'name':'First'})
            old = [callback for data, callback in pending if data['action']=='get_channel_details'][0]
            self.page.open_channel({'id':2,'name':'Second'})
            old({'status':'ok','channel':{'id':1,'name':'Wrong'}})
        self.assertEqual(self.page.active_channel['id'],2)
        self.assertEqual(self.page.active_channel['name'],'Second')

    def test_empty_chat_shows_hint(self):
        from PySide6.QtWidgets import QLabel
        self.page.start_request = lambda data, cb, **kw: cb({'status':'ok','messages':[]}) if data['action']=='get_channel_messages' else None
        self.page.open_channel({'id':1,'name':'Empty'})
        self.assertTrue(self.page.findChildren(QLabel,'ChannelTextEmptyHint'))

    def test_details_response_preserves_new_draft(self):
        pending = []
        self.page.active_channel = {'id':1,'name':'Old'}
        self.page.start_request = lambda data, cb, **kw: pending.append(cb)
        self.page.load_channel_details()
        self.page.settings_name_input.setText('Draft')
        self.page._mark_settings_edited()
        pending[0]({'status':'ok','channel':{'id':1,'name':'Server'}})
        self.assertEqual(self.page.settings_name_input.text(),'Draft')

    def test_avatar_survives_source_file_removal(self):
        from PySide6.QtGui import QImage, QColor
        from application.avatars import encode_avatar
        from ui.avatar_widget import AvatarLabel
        from domain.avatars import normalize_avatar
        source = Path(self.folder.name)/'image.png'
        image = QImage(64,64,QImage.Format_RGBA8888)
        image.fill(QColor('red'))
        image.save(str(source))
        payload = normalize_avatar(encode_avatar(str(source)))
        source.unlink()
        widget = AvatarLabel()
        self.addCleanup(widget.close)
        self.assertFalse(widget._load_pixmap(payload,'remote').isNull())

    def test_call_snapshot_does_not_restart_audio(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from ui.main_window import MainWindow
        window = SimpleNamespace(ctx=SimpleNamespace(session_token='test'),current_call_user=None,
            voice_client=None,call_window=None,_hide_incoming_inline=Mock(),
            _show_incoming_inline=Mock(),_start_voice_for_peer=Mock(),_open_call_window=Mock(),
            _close_call_window=Mock())
        state={'peer':'bob','status':'active','incoming':False,'call_id':'1'}
        MainWindow._reconcile_call_state(window,state)
        MainWindow._reconcile_call_state(window,state)
        window._start_voice_for_peer.assert_called_once_with('bob')
        MainWindow._reconcile_call_state(window,None)
        self.assertIsNone(window.current_call_user)
        MainWindow._reconcile_call_state(window,dict(state,call_id='2'))
        self.assertEqual(window._start_voice_for_peer.call_count,2)
