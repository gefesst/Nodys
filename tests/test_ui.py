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

    def test_channel_initial_failure_has_retry_and_keeps_open_form(self):
        from PySide6.QtWidgets import QPushButton
        p = self.page
        p.start_request = lambda data, callback, **kw: callback({'status':'error','message':'Offline'})
        p.open_create_page()
        p.load_channels(force_refresh=True)
        self.assertFalse(p._channels_skeleton_visible)
        self.assertIs(p.main_stack.currentWidget(),p.create_page)
        retry=p.channel_state_stack.currentWidget().findChild(QPushButton)
        self.assertEqual(retry.text(),'Повторить')
        p.start_request = lambda data, callback, **kw: callback({'status':'ok','channels':[]})
        retry.click()
        self.assertEqual(p.channel_state_stack.currentWidget().findChild(QPushButton).text(),'Создать канал')

    def test_call_audio_starts_before_settings_page_has_been_opened(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from ui.main_window import MainWindow
        state=SimpleNamespace(current_call_user='bob',voice_client=None,
            channels_page=SimpleNamespace(stop_voice_session=Mock()),
            ctx=SimpleNamespace(login='alice',session_token='synthetic'),_show_call_notice=Mock())
        with patch('ui.main_window.VoiceSession') as session, patch('ui.main_window.get_voice_endpoint',return_value=('127.0.0.1',12345)):
            MainWindow._start_voice_for_peer(state,'bob')
            session.return_value.start.assert_called_once_with(peer_login='bob')
            state._show_call_notice.assert_not_called()

    def test_audio_waiting_for_microphone_does_not_resume_an_old_call(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from ui.main_window import MainWindow
        retry=Mock()
        state=SimpleNamespace(current_call_user='bob',
            settings_page=SimpleNamespace(stop_microphone_check=lambda:False),
            calls=SimpleNamespace(state={'call_id':'old'}),
            ctx=SimpleNamespace(session_token='synthetic'),_start_voice_for_peer=retry)
        with patch('ui.main_window.QTimer.singleShot') as timer:
            MainWindow._start_voice_for_peer(state,'bob')
            callback=timer.call_args.args[1]
        state.calls.state={'call_id':'new'}
        callback()
        retry.assert_not_called()

    def test_muted_local_voice_card_ignores_stale_speaking_presence(self):
        from ui.channels_page import VoiceParticipantItem
        from PySide6.QtWidgets import QLabel
        p=self.page
        p._voice_joined=True;p._voice_muted=True
        p._voice_participants=[{'login':p.ctx.login,'nickname':'Alice','speaking':True}]
        p._render_voice_participants()
        row=p.voice_members_container.findChild(VoiceParticipantItem)
        self.assertFalse(row.property('speaking'))
        self.assertIn('Микрофон выключен',[label.text() for label in row.findChildren(QLabel)])
        self.assertEqual(row.width(),290)

    def test_cancelled_channel_join_does_not_resume_after_microphone_stops(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        p=self.page
        p.active_channel={'id':1,'name':'Channel'}
        p._main_window=SimpleNamespace(settings_page=SimpleNamespace(stop_microphone_check=lambda:False))
        with patch('ui.channels_page.QTimer.singleShot') as timer:
            p.toggle_voice_join()
            callback=timer.call_args.args[1]
        p.stop_voice_session()
        with patch.object(p,'toggle_voice_join') as resume:
            callback()
            resume.assert_not_called()

    def test_removed_channel_rows_hide_before_deferred_destruction(self):
        from ui.channels_page import ChannelListItem
        p=self.page
        p.channels=[{'id':1,'name':'Old'}];p.render_channels(force=True)
        old=p.channels_container.findChild(ChannelListItem)
        old.show()
        p.channels=[];p.render_channels(force=True)
        self.assertTrue(old.isHidden())

    def test_channel_join_error_stays_in_form_and_retry_clears_it(self):
        p=self.page;pending=[]
        p.start_request=lambda data,callback:pending.append(callback)
        p.open_join_page();p.join_code_input.setText('bad-code');p.join_channel()
        self.assertFalse(p.join_confirm_btn.isEnabled())
        pending.pop()({'status':'error','message':'Недействительный код'})
        self.assertEqual(p.join_feedback.text(),'Недействительный код')
        self.assertIs(p.main_stack.currentWidget(),p.join_page)
        self.assertTrue(p.join_confirm_btn.isEnabled())
        p.join_channel()
        self.assertEqual(p.join_feedback.text(),'')
        pending.pop()({'status':'error','message':'Повторная ошибка'})

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
        sys.path.append(str(Path(__file__).resolve().parents[1] / "server"))
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
            _close_call_window=Mock(),_close_call_result=Mock())
        state={'peer':'bob','status':'active','incoming':False,'call_id':'1'}
        MainWindow._reconcile_call_state(window,state)
        MainWindow._reconcile_call_state(window,state)
        window._start_voice_for_peer.assert_called_once_with('bob')
        MainWindow._reconcile_call_state(window,None)
        self.assertIsNone(window.current_call_user)
        MainWindow._reconcile_call_state(window,dict(state,call_id='2'))
        self.assertEqual(window._start_voice_for_peer.call_count,2)

    def test_channel_switch_cancels_pending_voice_start(self):
        from PySide6.QtCore import QObject, Signal
        from unittest.mock import Mock
        class PendingVoice(QObject):
            ready=Signal()
            failed=Signal(str)
            def __init__(self):
                super().__init__()
                self.start=Mock()
                self.stop=Mock()
        voice=PendingVoice()
        self.page.active_channel={'id':1,'name':'First'}
        with patch('ui.channels_page.VoiceSession',return_value=voice):
            self.page.toggle_voice_join()
        self.assertTrue(self.page._voice_transitioning)
        self.page.open_channel({'id':2,'name':'Second'})
        voice.ready.emit()
        voice.stop.assert_called_once()
        self.assertFalse(self.page._voice_joined)
        self.assertFalse(self.page._voice_transitioning)

    def test_changed_friend_search_cannot_display_or_send_stale_result(self):
        from ui.friends_page import FriendsPage
        page = FriendsPage(); self.addCleanup(page.close)
        callbacks=[]
        page.start_request=lambda data,callback: callbacks.append(callback)
        page.login_input.setText('bob');page.find_user_inline()
        page.login_input.setText('carol')
        callbacks.pop()(dict(status='ok',login='bob',nickname='Bob'))
        self.assertIsNone(page._found_user)
        self.assertFalse(page.send_request_btn.isEnabled())
        self.assertTrue(page.found_card.isHidden())
        page.find_user_inline()
        callbacks.pop()(dict(status='ok',login='carol',nickname='Carol'))
        self.assertEqual(page._found_user['login'],'carol')
        self.assertTrue(page.send_request_btn.isEnabled())
        page.login_input.setText('dave')
        self.assertFalse(page.send_request_btn.isEnabled())

    def test_accessible_channel_tab_and_radio_change_content_and_policy(self):
        self.page.settings_sections['access'].setChecked(True)
        self.assertEqual(self.page._settings_section,'access')
        self.assertFalse(self.page.settings_access_card.isHidden())
        self.page.settings_text_radios[2].setChecked(True)
        self.assertEqual(self.page.settings_text_perm_combo.currentData(),'admin')
        self.assertGreater(self.page._settings_revision,0)
        self.page.settings_text_perm_combo.setCurrentIndex(0)
        self.assertTrue(self.page.settings_text_radios[0].isChecked())

    def test_friends_navigation_keeps_active_call(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from ui.main_window import MainWindow
        voice=Mock()
        window=SimpleNamespace(btn_friends=object(),friends_page=object(),stack=Mock(),
            set_active_nav=Mock(),_apply_polling_policy=Mock(),voice_client=voice,
            _sync_release_call_state=Mock(),_close_call_window=Mock(),_current_call_peer=lambda:'bob')
        MainWindow.show_friends(window)
        voice.stop.assert_not_called()
        window._sync_release_call_state.assert_not_called()

    def test_resume_cancel_ignores_late_success(self):
        from app_window import AppWindow
        from config import save_config,load_config
        save_config({'token':'old-token','login':'alice'})
        window=AppWindow()
        self.addCleanup(window.deleteLater)
        self.assertIs(window.stack.currentWidget(),window.resume_page)
        window._cancel_resume()
        window._handle_resume_response({'status':'ok','login':'unexpected','nickname':'Wrong'})
        self.assertIs(window.stack.currentWidget(),window.auth_page)
        self.assertIsNone(window.main_page)
        self.assertEqual(load_config()['token'],'old-token')

    def test_resume_cannot_overwrite_new_credentials(self):
        from app_window import AppWindow
        from config import save_config,load_config
        save_config({'token':'old-token'})
        window=AppWindow();self.addCleanup(window.deleteLater)
        save_config({'token':'new-token','login':'bob'})
        window._handle_resume_response({'status':'ok','login':'alice'})
        self.assertEqual(load_config()['token'],'new-token')
        self.assertIsNone(window.main_page)

    def test_resume_failure_preserves_token_except_invalid_session(self):
        from app_window import AppWindow
        from config import save_config,load_config
        for response,expected in (({'status':'error','message':'timeout'},'saved'),
                                  ({'status':'error','code':'session_invalid'},None)):
            save_config({'token':'saved'})
            window=AppWindow();self.addCleanup(window.deleteLater)
            window._handle_resume_response(response)
            self.assertEqual(load_config().get('token'),expected)
            self.assertIs(window.stack.currentWidget(),window.auth_page)

    def test_login_error_is_inline(self):
        from auth_window import AuthWindow
        window=AuthWindow();self.addCleanup(window.close)
        with patch('auth_window.QMessageBox.warning') as modal:
            window.handle_login_response({'status':'error','message':'Слишком много попыток'})
            modal.assert_not_called()
        self.assertEqual(window.status_label.text(),'Слишком много попыток')
        self.assertTrue(window.btn_login.isEnabled())

    def test_shutdown_requests_with_zero_budget_never_waits(self):
        from utils.thread_safe_mixin import ThreadSafeMixin
        from types import SimpleNamespace
        from unittest.mock import Mock
        request=Mock();request.isRunning.return_value=True
        page=SimpleNamespace(_threads=[request])
        ThreadSafeMixin.shutdown_requests(page,wait_ms=0)
        request.abort.assert_called_once()
        request.wait.assert_not_called()

    def test_logout_captures_identity_before_local_transition(self):
        from ui.main_window import MainWindow
        from types import SimpleNamespace
        from unittest.mock import Mock
        window=SimpleNamespace(is_logging_out=False,_queue_session_cleanup=Mock(),_do_logout_transition=Mock())
        MainWindow.perform_logout(window)
        window._queue_session_cleanup.assert_called_once_with('logout')
        window._do_logout_transition.assert_called_once()

    def test_voice_dock_leaves_dialog_rows_scrollable_above_it(self):
        from ui.main_window import MainWindow
        from unittest.mock import Mock
        from PySide6.QtCore import QPoint
        with patch('ui.main_window.submit_session_cleanup'):
            window=MainWindow()
            self.addCleanup(window.deleteLater)
            self.addCleanup(window.prepare_to_close_app)
            window.voice_client=Mock(get_activity=lambda:{'quality':'Хорошее'})
            window.current_call_user='bob'
            window.show_chats()
            window.show()
            for width,height in ((1120,578),(1440,858)):
                window.resize(width,height)
                window.refresh_voice_dock()
                window.voice_dock.animation.setCurrentTime(180)
                self.app.processEvents()
                view=window.chats_page.dialogs
                bottom=view.mapTo(window,QPoint(0,view.height())).y()
                self.assertLessEqual(bottom,window.voice_dock.y())
            window.voice_client=None
            window.refresh_voice_dock()
            window.voice_dock.animation.setCurrentTime(180)
            self.assertTrue(window.chats_page.voice_dock_space.isHidden())
            window.close()

    def test_main_window_navigation_and_cleanup_are_repeatable(self):
        from ui.main_window import MainWindow
        with patch('ui.main_window.submit_session_cleanup'):
            window=MainWindow()
            self.addCleanup(window.deleteLater)
            window.show_channels();window.show_chats();window.show_friends();window.show_profile()
            window.prepare_to_close_app();window.prepare_to_close_app()
            self.assertFalse(window.call_events_timer.isActive())
            self.assertFalse(window.heartbeat_timer.isActive())
            self.assertEqual(window.calls.requests,{})
            window.reload_from_context(full_reset=True)
            self.assertTrue(window.heartbeat_timer.isActive())
            window.prepare_to_close_app()
