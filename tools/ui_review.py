"""Capture the normal client/main.py in an isolated, real localhost environment.

No fixture is imported by the normal application. Snapshots exercise real pages
and handlers. Run with --output <folder>; --synthetic-voice replaces devices only.
"""

import argparse, json, os, runpy, sys, time, traceback
import faulthandler
faulthandler.enable()
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = (
    "offscreen"  # Never interrupt the desktop during automated review.
)
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "client"), str(ROOT / "tools")]
from application.qt_runtime import prepare_platform_plugins
from review_support.sandbox import Sandbox


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--synthetic-voice", action="store_true")
    parser.add_argument("--relogin-cycles", type=int, default=1)
    parser.add_argument("--resize-all", action="store_true")
    parser.add_argument("--visual-only", action="store_true")
    parser.add_argument("--section",choices=("all","profile","voice","channels","calls","messages"),default="all")
    args = parser.parse_args()
    output=Path(args.output)
    if output.exists() and any(output.iterdir()):
        parser.error('Use a new empty output directory; existing evidence must not be mixed with another run.')
    lab = Sandbox(ROOT, reference_dialogs=args.section == 'messages')
    # Auth must be tested through the ordinary application, not by setting UserContext.
    from config import save_config

    save_config(lab.config)
    if args.synthetic_voice:
        from review_support import audio
    import app_window
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPainter

    original = app_window.AppWindow.__init__

    class Review:
        def __init__(self, w):
            self.w = w
            self.path = Path(args.output)
            self.path.mkdir(parents=True, exist_ok=True)
            import hashlib, subprocess
            self.source_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
            digest=hashlib.sha256()
            for source in sorted(path for folder in ('client','server') for path in (ROOT/folder).rglob('*') if path.suffix in ('.py','.qss','.svg')):
                digest.update(str(source.relative_to(ROOT)).encode());digest.update(source.read_bytes())
            self.source_tree_sha256=digest.hexdigest()
            self.log = []
            self.visual_fixtures = []
            self.workflow_checks = []
            if args.section == 'messages':
                self.visual_fixtures.append('Reference dialog seed: six named contacts, distinct previews and read states; dates relative to current local day in disposable database')
            self.error = None
            self.deadline = time.monotonic() + 300
            self.until = 0
            self.predicate = None
            self.steps = self.scenario()
            self.timer = QTimer(w)
            self.timer.setInterval(80)
            self.timer.timeout.connect(self.advance)
            self.timer.start()

        def wait(self, seconds=0.4, predicate=None, timeout=15):
            self.until = time.monotonic() + seconds
            self.predicate = predicate
            self.wait_deadline=time.monotonic()+max(timeout,seconds+2)

        def advance(self):
            if getattr(self,"capturing",False):
                return
            try:
                if time.monotonic() > self.deadline:
                    raise TimeoutError("Review timed out")
                if self.predicate and time.monotonic()>self.wait_deadline:
                    raise TimeoutError("UI state did not settle before its deadline")
                if time.monotonic() < self.until or (
                    self.predicate and not self.predicate()
                ):
                    return
                self.predicate = None
                next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.error = traceback.format_exc()
                self.finish()

        def shot(self, name, widget=None):
            from PySide6.QtTest import QTest
            target = widget or self.w
            self.capturing=True
            original_size=self.w.size()
            try:
                # Transitions last at most 160 ms. A snapshot must contain the
                # settled page, not the outgoing page's temporary fade overlay.
                QTest.qWait(220)
                target.grab().save(str(self.path / (name + ".png")))
                if args.resize_all:
                    folder=self.path/'sizes';folder.mkdir(exist_ok=True)
                    for width,height in ((1120,620),(1280,780),(1440,900)):
                        self.w.resize(width,height)
                        QTest.qWait(220)
                        assert self.w.width()==width and self.w.height()==height, (name,self.w.size(),width,height)
                        self.w.grab().save(str(folder/f'{name}-{width}.png'))
            finally:
                self.w.resize(original_size)
                QApplication.processEvents()
                self.capturing=False
            self.log.append(name)
            print("Captured", name, flush=True)

        def messages_review(self,m):
            from PySide6.QtWidgets import QPushButton
            m.show_friends()
            self.wait(predicate=lambda:bool(m.friends_page._friends_data));yield
            more=m.friends_page.findChild(QPushButton,'FriendMoreButton')
            more.click();self.shot('43g-friends-menu');m.friends_page._actions_menu.close()
            m.show_chats();page=m.chats_page
            self.wait(predicate=lambda:bool(page.dialog_model.rows));yield
            peer=lab.people[0][0]
            page.open_chat(next(row for row in page.dialog_model.rows if row['login']==peer))
            c=page.conversation
            self.wait(predicate=lambda:bool(c.rows) and not c.loading);yield
            assert any(message.unread_count for message in c.model.rows)
            self.shot('43-chat-unread')
            first=c.view.visualRect(c.model.index(0)).center()
            c.context_menu(first)
            self.shot('43h-chat-menu');c._menu.close()
            page.search.setText('Алексей')
            assert len(page.dialog_model.rows)==1
            self.shot('43b-chat-search')
            page.search.clear()
            assert lab.request(lab.me,'mark_chat_read',friend_login=peer)['status']=='ok'
            c.select(None);c.select(peer,lab.people[0][1])
            self.wait(predicate=lambda:not c.loading);yield
            assert not any(message.unread_count for message in c.model.rows)
            self.shot('43i-chat-read')
            self.wait(predicate=lambda:not page._loading_friends);yield
            from PIL import Image
            from io import BytesIO
            import base64
            avatar_image=Image.new('RGB',(64,64),'#A35C7B')
            avatar_image.paste('#91ADFF',(24,0,40,64))
            avatar_data=BytesIO();avatar_image.save(avatar_data,format='PNG')
            avatar_payload='data:image/png;base64,'+base64.b64encode(avatar_data.getvalue()).decode()
            assert lab.request(peer,'update_profile',nickname=lab.people[0][1],avatar=avatar_payload)['status']=='ok'
            page.load_friends(force=True);self.wait(predicate=lambda:not page._loading_friends);yield
            self.wait(predicate=lambda:not c.loading);yield
            c.load('poll');self.wait(predicate=lambda:not c.loading);yield
            assert all(message.avatar for message in c.model.rows if message.author==peer)
            self.shot('43j-chat-uploaded-avatar')
            assert c.delegate._avatars, 'Uploaded avatar must be painted, not just stored in the model'
            self.visual_fixtures.append('43j-chat-uploaded-avatar: generated PNG saved through real update_profile; no user profile changed')
            long_name='Александра Константинопольская-Рождественская'
            assert lab.request(peer,'update_profile',nickname=long_name,avatar='')['status']=='ok'
            # A timer may already be fetching the old profile. Wait for that
            # request before explicitly fetching the new server state.
            self.wait(predicate=lambda:not page._loading_friends);yield
            page.load_friends(force=True);self.wait(predicate=lambda:not page._loading_friends);yield
            assert page.chat_header.toolTip()==long_name, (page.chat_header.toolTip(),page.active_friend)
            text='Длинное сообщение: '+('Проверяем перенос строк, ширину пузыря и прокрутку. '*30)+'\n'+('https://example.test/very-long-path-'*15)
            c.editor.setPlainText(text);c.send()
            self.wait(predicate=lambda:peer not in c.pending);yield
            assert not c.editor.toPlainText()
            c.load('latest');self.wait(predicate=lambda:not c.loading);yield
            assert any(row['text']==text for row in c.rows)
            self.shot('43c-chat-long-text')
            assert c.view.horizontalScrollBar().maximum()==0
            page.msg_timer.stop();page.friends_timer.stop()
            self.wait(predicate=lambda:not c.loading);yield
            bar=c.view.verticalScrollBar();bar.setValue(max(25,bar.maximum()//2))
            assert lab.request(peer,'send_message',to_user=lab.me,text='Новое сообщение во время чтения')['status']=='ok'
            c.load('poll');self.wait(predicate=lambda:not c.loading);yield
            assert c.new_messages_button.isVisible() and bar.value()<bar.maximum()-20, (c.unseen_new,c.newer,bar.value(),bar.maximum(),c.rows[-1]["text"])
            self.shot('43d-chat-new-messages')
            c.new_messages_button.click();self.wait(predicate=lambda:not c.loading);yield
            assert not c.new_messages_button.isVisible()
            from config import save_config
            draft='Буду через десять минут. Не начинайте без меня.'
            c.editor.setPlainText(draft)
            save_config({'api_port':lab.free_port()})
            c.load('latest');self.wait(predicate=lambda:not c.loading);yield
            assert c.offline_note.text() and c.editor.toPlainText()==draft
            self.shot('43e-chat-offline-draft')
            save_config(lab.config)
            c.load('latest');self.wait(predicate=lambda:not c.loading);yield
            assert c.connection_restored.isVisible() and not c.offline_note.text()
            assert c.editor.toPlainText()==draft
            self.shot('43f-chat-reconnected')

        def calls_review(self,m):
            from server import server
            from config import save_config
            peer=lab.people[0][0];other=lab.people[1][0]
            m.show_friends()
            self.wait(1);yield
            # Hold only the presentation for a stable resize capture; cancellation
            # and response races are exercised by CallController regression tests.
            m._show_pending_call(peer)
            self.shot('41-call-connecting')
            m._clear_pending_call()
            self.visual_fixtures.append('41-call-connecting: pending presentation held without a network request')
            server.send_friend_request(peer,other);server.accept_friend_request(peer,other)
            assert lab.request(peer,'heartbeat')['status']=='ok'
            assert lab.request(other,'heartbeat')['status']=='ok'
            assert lab.request(peer,'call_user',to_user=other)['status']=='ok'
            m.start_outgoing_call(peer)
            self.wait(predicate=lambda:bool(getattr(m,'call_result_window',None)));yield
            assert m.call_result_window.heading.text()=='Пользователь занят'
            self.shot('41b-call-busy');m._close_call_result()
            busy_state=lab.request(peer,'poll_events',after_event_id=0)['call_state']
            assert lab.request(peer,'end_call',with_user=other,call_id=busy_state['call_id'])['status']=='ok'
            self.wait(predicate=lambda:'action' not in m.calls.requests);yield
            assert lab.request(peer,'heartbeat')['status']=='ok'
            m.start_outgoing_call(peer)
            self.wait(predicate=lambda:bool(m.calls.state) or bool(getattr(m,'call_result_window',None)));yield
            assert m.calls.state, 'Call did not start: '+m.call_result_window.heading.text()
            print('Awaiting actual ringing expiry',flush=True)
            # Stop peer heartbeats; the real server expires its ringing call.
            self.wait(predicate=lambda:m.calls.state is None and bool(getattr(m,'call_result_window',None)),timeout=40);yield
            assert m.call_result_window.heading.text()=='Нет ответа'
            self.shot('41c-call-timeout');m._close_call_result()
            self.wait(predicate=lambda:'action' not in m.calls.requests);yield
            save_config({'api_port':lab.free_port()})
            m.start_outgoing_call(peer)
            self.wait(predicate=lambda:bool(getattr(m,'call_result_window',None)));yield
            assert m.call_result_window.heading.text()=='Не удалось начать звонок'
            self.shot('41d-call-error')
            save_config(lab.config);m._close_call_result()

        def channel_states_review(self,m):
            from unittest.mock import patch
            m.show_channels();ch=m.channels_page
            self.wait(predicate=lambda:bool(ch.channels) and not ch._loading_channels);yield
            ch.stop_auto_update()
            saved_channels=list(ch.channels)
            with patch.object(ch,'load_channels'),patch.object(ch,'load_channel_invites'):
                ch.active_channel=None;ch.main_stack.setCurrentWidget(ch.placeholder_page)
                ch.channels=[];ch.render_channels(force=True);ch._set_channel_list_state('empty')
                self.shot('40-channels-empty')
                ch._show_channels_skeleton();self.shot('40b-channels-loading')
                ch._set_channel_list_state('error');self.shot('40c-channels-error')
                ch.channels=saved_channels;ch.render_channels(force=True);ch._set_channel_list_state('list')
                ch._invites=[];ch._render_invites(force=True);ch._set_invites_dropdown_open(True)
                self.shot('40d-channel-invites-empty')
            self.visual_fixtures.extend(['40-channels-empty: empty local channel cache','40b-channels-loading: pending list renderer','40c-channels-error: failed list renderer','40d-channel-invites-empty: empty invites cache'])
            ch.open_join_page();ch.join_code_input.setText('INVALID-CODE')
            ch.join_channel();self.wait(predicate=lambda:not ch._joining_channel);yield
            assert ch.main_stack.currentWidget() is ch.join_page and ch.join_feedback.text()
            self.shot('40e-channel-join-error')
            ch.open_channel(saved_channels[0])
            self.wait(predicate=lambda:not ch._loading_channel_details and not ch.conversation.loading);yield
            ch.stop_auto_update()
            c=ch.conversation
            with patch.object(ch,'load_channel_messages'),patch.object(c,'load'):
                c.scope.invalidate();c.rows=[];c.model.replace([]);c.loading=False;c.history_error=False;c.update_controls()
                self.shot('42-channel-text-empty')
                c.history_error=True;c.update_controls();self.shot('42b-channel-text-error')
                c.history_error=False;c.update_controls()
                original_permissions=dict(ch._settings_permissions)
                ch._settings_permissions=dict(original_permissions,can_send_text=False,text_min_role='moderator')
                ch._apply_channel_permissions_ui();self.shot('42c-channel-text-denied')
                ch._settings_permissions=dict(original_permissions,can_join_voice=False,voice_min_role='moderator')
                ch.switch_to_voice_tab();ch._apply_channel_permissions_ui()
                self.shot('42d-channel-voice-denied')
                ch._settings_permissions=original_permissions;ch._apply_channel_permissions_ui()
                ch.voice_quality_lbl.setText('Связь нестабильна · задержка 180 мс · возможны перерывы звука')
                ch.voice_quality_lbl.show();self.shot('42e-channel-voice-quality');ch.voice_quality_lbl.hide()
            self.visual_fixtures.extend(['42-channel-text-empty: empty history cache','42b-channel-text-error: failed history renderer','42c-channel-text-denied: permission renderer; server ACL tested separately','42d-channel-voice-denied: permission renderer; server ACL tested separately','42e-channel-voice-quality: simulated quality warning'])
            ch.open_channel_settings()
            self.wait(predicate=lambda:not ch._loading_channel_details);yield
            ch.save_channel_settings()
            self.wait(predicate=lambda:not ch._saving_channel_settings);yield
            assert ch.settings_feedback.text()=='Настройки канала сохранены'
            self.shot('42f-channel-settings-saved')
            ch.ask_delete_channel()
            self.shot('17c-channel-delete-confirm')
            ch.hide_settings_confirm()
            from server import server
            guest_channel=server.create_channel(lab.people[0][0],'Общий канал')
            server.join_channel_by_code(lab.me,guest_channel['code'])
            ch.load_channels(force_refresh=True)
            self.wait(predicate=lambda:not ch._loading_channels);yield
            ch.open_channel(next(row for row in ch.channels if row['id']==guest_channel['id']))
            ch.open_channel_settings()
            self.wait(predicate=lambda:not ch._loading_channel_details);yield
            ch.ask_leave_channel()
            self.shot('42g-channel-leave-confirm');ch.hide_settings_confirm()


        def voice_review(self,m):
            from unittest.mock import patch
            ch=m.channels_page
            m.show_channels()
            self.wait(predicate=lambda:bool(ch.channels));yield
            ch.open_channel(ch.channels[0]);ch.switch_to_voice_tab()
            self.wait(predicate=lambda:not ch._loading_channel_details);yield
            remotes=[]
            try:
                if args.synthetic_voice:
                    from review_support.audio import SyntheticVoiceClient
                    for peer,_ in lab.people[:2]:
                        assert lab.request(peer,'join_channel',code=lab.channel['code'])['status']=='ok' or peer==lab.people[0][0]
                        remote=SyntheticVoiceClient(login=peer,token=lab.tokens[peer],host='127.0.0.1',port=lab.voice_port)
                        remote.start(room_id=ch._voice_room_id());remotes.append((peer,remote))
                        assert lab.request(peer,'set_channel_voice_presence',channel_id=lab.channel['id'],joined=True,speaking=False,sequence=time.time_ns())['status']=='ok'
                    ch.load_voice_participants(force=True)
                    self.wait(predicate=lambda:len(ch._voice_participants)>=2);yield
                    self.shot('44-channel-voice-present')
                m.show_settings();self.wait();yield
                yield from self.microphone_review(m)
                if args.synthetic_voice:
                    ch.toggle_voice_join();self.wait(predicate=lambda:ch._voice_joined);yield
                    ch.sync_voice_presence(force_pull=True)
                    self.wait(predicate=lambda:len(ch._voice_participants)>=3);yield
                    self.wait(2);yield
                    self.shot('44b-channel-voice-active')
                    ch.toggle_voice_mute();self.shot('44c-channel-voice-muted')
                    with patch.object(ch._voice_client,'get_activity',return_value=dict(quality='Нестабильное',latency_ms=180,jitter_ms=80)):
                        ch.update_voice_status();self.shot('44d-channel-voice-quality')
                    self.visual_fixtures.append('44d-channel-voice-quality: injected quality counters; encrypted transport uses synthetic PCM')
            finally:
                ch.stop_voice_session()
                for peer,remote in remotes:
                    remote.stop()
                    lab.request(peer,'leave_channel_voice',channel_id=lab.channel['id'],sequence=time.time_ns())

        def microphone_review(self,m):
            m.settings_page.check_microphone()
            mic=m.settings_page.microphone_check
            mic.listening()
            for level in (10,25,45,70,95,65,40,25,15,10):
                mic.level=level;mic.update_meter()
            self.shot('29f-microphone-level')
            mic.level=0;mic.last_signal=time.monotonic()-4;mic.update_meter()
            self.shot('29g-microphone-silent')
            mic.failed('Permission denied');self.shot('29h-microphone-permission')
            mic.close()
            self.visual_fixtures.extend(['29f-microphone-level: injected level; no audio device','29g-microphone-silent: injected silence; no audio device','29h-microphone-permission: injected permission error; no OS permission changed'])
            yield

        def profile_review(self,m):
            m.show_profile()
            self.wait()
            yield
            self.shot("19-profile")
            m.profile_page.show_section("edit")
            self.wait()
            yield
            self.shot("20-profile-edit")
            m.profile_page.save_changes()
            self.shot('20b-profile-saving')
            self.wait(predicate=lambda:not m.profile_page._saving);yield
            assert m.profile_page.feedback.text() == 'Профиль обновлён.'
            self.shot('20c-profile-saved')
            from unittest.mock import patch
            p=m.profile_page
            p.confirm_logout();self.shot('20d-profile-logout');p._confirmation.reject()
            avatar_file=lab.path/'avatar-review.png'
            p.avatar_label.grab().save(str(avatar_file))
            before=p.avatar_path
            with patch('ui.profile_page.QFileDialog.getOpenFileName',return_value=(str(avatar_file),'PNG')):
                p.choose_avatar()
            self.shot('20e-profile-avatar');p._confirmation.reject()
            assert p.avatar_path==before
            self.visual_fixtures.append('20e-profile-avatar: file picker supplied a generated test avatar; confirmation uses normal encoder')
            from config import save_config
            save_config({'api_port':lab.free_port()})
            p.save_changes();self.wait(predicate=lambda:not p._saving);yield
            self.shot('20f-profile-save-error')
            assert p.feedback.text() and p.nickname_edit.text()
            save_config(lab.config)
            m.profile_page.show_section("password")
            self.wait()
            yield
            self.shot("21-profile-password")

        def scenario(self):
            w = self.w
            self.wait(0.6)
            yield
            self.shot("01-auth-login")
            w.show_register()
            self.wait()
            yield
            self.shot("02-auth-register")
            w.register_page.login.setText(lab.me)
            w.register_page.password.setText("duplicate-test")
            w.register_page.nickname.setText("Duplicate")
            w.register_page.register_user()
            self.shot("02b-auth-register-loading")
            self.wait(predicate=lambda: w.register_page.btn_register.isEnabled())
            yield
            self.shot("03-auth-register-error")
            w.register_page.login.setText("review_new_user")
            w.register_page.password.setText("review-new-password")
            w.register_page.nickname.setText("Новый участник")
            w.register_page.register_user()
            self.wait(predicate=lambda: w.register_page.btn_register.isEnabled())
            yield
            assert not w.register_page.login.text()
            self.shot("03b-registered")
            w.show_auth()
            # Test fixture has a random password; establish a real known test-only password.
            from server import server
            from server.domain.passwords import hash_password
            from server.storage.database import connect

            with connect(server.DB_FILE) as conn:
                conn.execute(
                    "UPDATE users SET password=? WHERE login=?",
                    (hash_password("review-password"), lab.me),
                )
            w.auth_page.login.setText(lab.me)
            w.auth_page.password.setText("incorrect-test-password")
            w.auth_page.login_user()
            self.wait(predicate=lambda:w.auth_page.btn_login.isEnabled());yield
            self.shot('03c-auth-login-error')
            w.auth_page.password.setText("review-password")
            w.auth_page.login_user()
            self.shot('03d-auth-login-loading')
            self.wait(
                predicate=lambda: (
                    w.main_page is not None and w.stack.currentWidget() == w.main_page
                )
            )
            yield
            m = w.main_page
            lab.tokens[lab.me] = m.ctx.session_token
            if args.section=="messages":
                w.resize(1440,900)
                yield from self.messages_review(m)
                return
            if args.section=="calls":
                w.resize(1440,900)
                yield from self.calls_review(m)
                return
            if args.section=="profile":
                w.resize(1440,900)
                yield from self.profile_review(m)
                return
            if args.section=="channels":
                w.resize(1440,900)
                yield from self.channel_states_review(m)
                return
            if args.section=="voice":
                w.resize(1440,900)
                yield from self.voice_review(m)
                return
            self.wait(1)
            yield
            for size in ((1120, 620), (1280, 780), (1440, 900)):
                w.resize(*size)
                self.wait()
                yield
                self.shot(f"04-friends-{size[0]}")
            self.shot("04-friends-all")
            friends=m.friends_page
            saved_friends=list(friends._friends_data)
            friends._friends_data=[];friends._render_if_needed(force=True)
            self.shot('04b-friends-empty')
            friends._show_skeleton(count=6)
            self.shot('04c-friends-loading')
            friends._friends_data=saved_friends;friends._render_if_needed(force=True)
            self.visual_fixtures.extend(['04b-friends-empty: empty local friend cache','04c-friends-loading: loading renderer'])

            m.friends_page.set_view("online")
            self.wait()
            yield
            self.shot("05-friends-online")
            m.friends_page.set_view("requests")
            self.wait()
            yield
            self.shot("06-friends-requests")
            saved_requests=list(m.friends_page._requests_data)
            m.friends_page._requests_data=[];m.friends_page._render_if_needed(force=True)
            self.shot('06a-friends-requests-empty')
            m.friends_page._requests_data=saved_requests;m.friends_page._render_if_needed(force=True)
            self.visual_fixtures.append('06a-friends-requests-empty: empty local requests cache')

            m.friends_page.set_view("all")
            m.friends_page.filter_input.setText("no-such-friend")
            self.wait();yield
            self.shot("06b-friends-search-empty")
            m.friends_page.filter_input.clear()
            from config import save_config
            m.friends_page.set_polling_enabled(False)
            self.wait(predicate=lambda:not m.friends_page._loading_friends);yield
            save_config({'api_port':lab.free_port()})
            m.friends_page.load_friends()
            self.wait(predicate=lambda:not m.friends_page._loading_friends);yield
            self.shot("06c-friends-network-error")
            save_config(lab.config)
            m.friends_page.load_friends()
            self.wait(predicate=lambda:not m.friends_page._loading_friends);yield
            assert any(f["login"]==lab.people[0][0] for f in m.friends_page._friends_data), "Friend list did not recover after network restoration"
            m.friends_page.set_polling_enabled(True)
            m.friends_page.confirm_and_remove_friend(lab.people[0][0])
            self.wait();yield
            self.shot("06d-friend-remove-confirm")
            m.friends_page._confirmation.reject()
            m.friends_page.hide_inline_delete_confirm()
            m.friends_page.set_view("add")
            m.friends_page.login_input.setText(lab.people[0][0])
            m.friends_page.find_user_inline()
            self.wait(0.6)
            yield
            self.shot("07-friends-add-search")
            m.friends_page.show_mini_profile(lab.people[0][0])
            self.wait()
            yield
            self.shot("08-mini-profile", m.friends_page._mini_profile)
            m.friends_page._mini_profile.close()
            m.show_chats()
            self.wait(predicate=lambda: len(m.chats_page.dialog_model.rows) > 0)
            yield
            self.shot("08b-chat-none")
            m.chats_page.open_chat(m.chats_page.dialog_model.rows[0])
            self.wait(predicate=lambda: len(m.chats_page.conversation.rows) > 0)
            yield
            self.shot("09-private-chat")
            c=m.chats_page.conversation
            saved_rows=c.rows
            c.scope.invalidate()
            from unittest.mock import patch
            with patch.object(c,"load"):
                c.rows=[]
                c.loading=False;c.history_error=False;c.update_controls()
                self.shot('09b-chat-empty')
                assert c.history_stack.currentWidget() is c.empty_state
                c.loading=True;c.update_controls();self.shot('09c-chat-loading')
                assert c.history_stack.currentWidget() is not c.loading_state
                c.loading=False;c.history_error=True;c.update_controls();self.shot('09d-chat-error')
                assert c.history_stack.currentWidget() is c.error_state
                c.rows=saved_rows;c.history_error=False;c.update_controls()
                self.visual_fixtures.extend(['09b-chat-empty: empty local history','09c-chat-loading: pending history','09d-chat-error: failed initial history'])

            c = m.chats_page.conversation
            c.editor.setPlainText("Проверка настоящего приложения\nВторая строка")
            self.shot("10-chat-multiline")
            c.send()
            self.wait(predicate=lambda: not c.pending and not c.loading)
            yield
            self.shot("11-chat-sent")
            m.show_channels()
            self.wait(predicate=lambda: bool(m.channels_page.channels))
            yield
            ch = m.channels_page
            self.shot("11a-channel-list")
            ch._set_invites_dropdown_open(True)
            self.wait();yield
            self.shot('11b-channel-invites')
            ch.open_channel(ch.channels[0])
            ch.switch_to_text_tab()
            self.wait(0.6)
            yield
            self.shot("12-channel-text")
            ch.channel_msg_input.setPlainText("Сообщение через новый компонент канала")
            ch.send_channel_message()
            self.wait(
                predicate=lambda: (
                    not ch.conversation.pending and not ch.conversation.loading
                )
            )
            yield
            self.shot("13-channel-message-sent")
            ch.switch_to_voice_tab()
            self.wait()
            yield
            self.shot("14-channel-voice")
            ch.open_create_page()
            self.wait()
            yield
            ch.create_name_input.setText("Свои люди")
            self.shot("15-channel-create")
            ch.open_join_page()
            self.wait()
            yield
            ch.join_code_input.setText("A1B2C3D4")
            self.shot("16-channel-join")
            ch.open_channel(ch.channels[0])
            ch.open_channel_settings()
            self.shot("16b-channel-settings-loading")
            self.wait(0.6)
            yield
            self.shot("17-channel-settings")
            save_config({'api_port':lab.free_port()})
            ch.load_channel_details(silent=False)
            self.wait(predicate=lambda:not ch._loading_channel_details);yield
            self.shot('17a-channel-settings-error')
            save_config(lab.config)
            ch.load_channel_details(silent=False)
            self.wait(predicate=lambda:not ch._loading_channel_details);yield
            old_code = ch.settings_code_lbl.text()
            ch.ask_regenerate_channel_code()
            self.wait(); yield
            self.shot("17b-channel-regenerate-confirm")
            ch._confirmation.reject()
            assert ch.settings_code_lbl.text() == old_code
            ch.ask_delete_channel()
            self.wait(); yield
            self.shot("17c-channel-delete-confirm")
            ch.hide_settings_confirm()
            ch.settings_scroll.verticalScrollBar().setValue(
                ch.settings_scroll.verticalScrollBar().maximum()
            )
            self.wait()
            yield
            self.shot("18-channel-settings-bottom")
            ch.show_settings_section("access")
            self.wait()
            yield
            self.shot("18b-channel-permissions")
            ch.show_settings_section("members")
            self.wait()
            yield
            self.shot("18c-channel-members-roles")
            yield from self.profile_review(m)
            m.show_settings()
            self.wait()
            yield
            self.shot("22-settings")
            m.settings_page.select_section("Активность")
            for width, height in ((1080, 620), (1440, 900)):
                w.resize(width, height)
                self.wait();yield
                self.shot(f"22-steam-settings-{width}")
            if not args.visual_only:
                peer = lab.people[0][0]
                assert lab.request(peer, "heartbeat", activity_sequence=1,
                    steam_nickname="Steam Player", steam_game="Counter-Strike 2", steam_app_id="730")["status"] == "ok"
                m.show_friends();m.friends_page.set_view('all');m.friends_page.load_friends()
                self.wait(predicate=lambda: any(f.get('steam_activity') for f in m.friends_page._friends_data));yield
                from ui.friends_page import FriendItem
                activity_card = next(item for item in m.friends_page.findChildren(FriendItem) if item.login == peer and item.isVisible())
                assert 'Counter-Strike 2' in activity_card.activity_label.full_text
                self.shot("22-steam-friend-activity")
                assert lab.request(peer, "heartbeat", activity_sequence=2,
                    steam_nickname="", steam_game="", steam_app_id="")["status"] == "ok"
                m.friends_page.load_friends()
                self.wait(predicate=lambda: not any(f.get('steam_activity') for f in m.friends_page._friends_data));yield
                assert activity_card.activity_label.full_text == ''
                self.workflow_checks.append('steam_activity_visible_to_friend_and_cleared')
            m.show_settings();m.settings_page.select_section("Внешний вид")

            if args.visual_only:
                return
            m.settings_page.check_microphone();self.wait();yield
            self.shot("22b-microphone-check-not-started",m.settings_page.microphone_check)
            m.settings_page.microphone_check.close()
            m.open_quick_switch();self.wait();yield
            self.shot("22c-quick-switch",m.quick_switch)
            m.quick_switch.query.setText('no-such-contact');self.wait();yield
            self.shot("22d-quick-switch-empty",m.quick_switch);m.quick_switch.close()
            m.show_chats()
            w.resize(1120, 620)
            self.wait()
            yield
            self.shot("23-chat-1120")
            w.resize(1440, 900)
            if args.synthetic_voice:
                peer = lab.people[0][0]
                assert lab.request(peer,"heartbeat")["status"] == "ok"
                m.start_outgoing_call(peer)
                self.wait(predicate=lambda: bool(m.calls.state) or bool(getattr(m,"call_result_window",None)))
                yield
                assert m.calls.state, "Outgoing call did not reach ringing"
                self.shot("24-outgoing-call", m.outgoing_window)
                state = lab.request(peer, "poll_events", after_event_id=0)["call_state"]
                assert (
                    lab.request(
                        peer, "accept_call", from_user=lab.me, call_id=state["call_id"]
                    )["status"]
                    == "ok"
                )
                m.calls.poll()
                self.wait(
                    predicate=lambda: (
                        m.call_window is not None and m.voice_client is not None
                    )
                )
                yield
                from review_support.audio import SyntheticVoiceClient

                remote = SyntheticVoiceClient(
                    login=peer,
                    token=lab.tokens[peer],
                    host="127.0.0.1",
                    port=lab.voice_port,
                )
                remote.start(peer_login=lab.me)
                self.wait(2)
                yield
                self.shot("25-active-call", m.call_window)
                m.show_chats();m.refresh_voice_dock()
                self.shot("25b-voice-dock")
                m.open_voice_surface()
                m.call_window._mic_clicked();m.call_window._sound_clicked()
                self.shot("26-call-muted", m.call_window)
                m.call_window._mic_clicked();m.call_window._sound_clicked()
                provider=m.call_window.activity_provider
                m.call_window.activity_provider=lambda:dict(quality='Нестабильное',quality_score=20,latency_ms=180,jitter_ms=80)
                m.call_window._update_activity()
                self.visual_fixtures.append('26a-call-quality')
                self.shot('26a-call-quality',m.call_window)
                m.call_window.activity_provider=provider
                m.call_window._update_activity()
                self.wait(2)
                yield
                # Reset only diagnostic counters after screenshots/warmup. No devices involved.
                from audio.diagnostics import AudioDiagnostics

                local = m.voice_client._core
                for core in (local, remote):
                    core.diagnostics = AudioDiagnostics()
                self.wait(2)
                yield
                for size in ((1120, 620), (1440, 900), (1280, 780)) * 3:
                    w.resize(*size)
                    m.show_chats()
                    self.wait(0.25)
                    yield
                self.wait(4)
                yield
                self.audio_results = [
                    dict(metrics=core.metrics(), diagnostics=core.get_diagnostics())
                    for core in (local, remote)
                ]
                remote.stop()
                m.call_window._end_clicked()
                self.wait(predicate=lambda: m.calls.state is None)
                yield
                if getattr(m,"call_result_window",None):
                    self.shot("26b-call-result")
                    m._close_call_result()
                assert lab.request(peer, "call_user", to_user=lab.me)["status"] == "ok"
                m.calls.poll()
                self.wait(
                    predicate=lambda: bool(
                        m.calls.state and m.calls.state.get("incoming")
                    )
                )
                yield
                self.shot("27-incoming-call")
                m._decline_incoming_inline()
                self.wait(predicate=lambda: m.calls.state is None)
                yield
                self.shot("27b-call-declined")
                m._close_call_result()
                # A repeated accepted incoming call exercises lifecycle reuse.
                assert lab.request(peer, "call_user", to_user=lab.me)["status"] == "ok"
                m.calls.poll()
                self.wait(
                    predicate=lambda: bool(
                        m.calls.state and m.calls.state.get("incoming")
                    )
                )
                yield
                m._accept_incoming_inline()
                self.wait(predicate=lambda: m.call_window is not None)
                yield
                self.wait(1)
                yield
                self.shot("28-repeated-call", m.call_window)
                m.call_window._end_clicked()
                self.wait(predicate=lambda: m.calls.state is None)
                yield
            if args.synthetic_voice:
                m._close_call_result()
                m.show_channels();ch.open_channel(lab.channel);ch.switch_to_voice_tab()
                self.wait(predicate=lambda:not ch._loading_channel_details);yield
                ch.toggle_voice_join()
                self.wait(predicate=lambda:ch._voice_joined);yield
                remote= SyntheticVoiceClient(login=peer,token=lab.tokens[peer],host='127.0.0.1',port=lab.voice_port)
                remote.start(room_id=ch._voice_room_id())
                assert lab.request(peer,'set_channel_voice_presence',channel_id=lab.channel['id'],joined=True,speaking=False,sequence=time.time_ns())['status']=='ok'
                ch.sync_voice_presence(force_pull=True)
                self.wait(1);yield
                ch.load_voice_participants(force=True)
                self.wait(predicate=lambda:len(ch._voice_participants)>=2);yield
                self.shot('29-channel-voice-active')
                ch.toggle_voice_mute();self.shot('29b-channel-voice-muted');ch.toggle_voice_mute()
                m.show_chats();m.refresh_voice_dock();self.shot('29c-channel-voice-dock')
                with patch.object(ch._voice_client,'get_activity',return_value={'quality':'Переподключение'}):
                    m.refresh_voice_dock();self.shot('29e-channel-voice-reconnecting')
                self.visual_fixtures.append('29e-channel-voice-reconnecting: transport reconnecting status renderer')
                m.open_voice_surface()
                ch.stop_voice_session()
                remote.stop()
                lab.request(peer,'leave_channel_voice',channel_id=lab.channel['id'],sequence=time.time_ns())
                self.wait(.5);yield
                ch.load_voice_participants(force=True)
                self.wait(predicate=lambda:not ch._voice_participants_loading);yield
                assert not ch._voice_joined and not any(p['login']==lab.me for p in ch._voice_participants)
                self.shot('29d-channel-voice-left')
                yield from self.microphone_review(m)
            w.resize(1440, 900)
            m.show_profile()
            p = m.profile_page
            p.show_section("edit")
            p.nickname_edit.setText("Андрей · проверено")
            p.save_changes()
            self.wait(predicate=lambda: not p._saving)
            yield
            assert p.nickname == "Андрей · проверено"
            self.shot("30-profile-saved")
            # Accept a real request; fixture preparation does not fake the UI response.
            assert server.send_friend_request("review_new_user", lab.me)
            m.show_friends()
            f = m.friends_page
            f.set_view("requests")
            f.load_requests()
            self.wait(predicate=lambda: "review_new_user" in f._requests_data)
            yield
            self.shot("31-friend-request")
            f.accept_request("review_new_user")
            self.wait(predicate=lambda: "review_new_user" not in f._requests_data)
            yield
            m.show_channels()
            ch.open_create_page()
            ch.create_name_input.setText("Проверка создания")
            ch.create_channel()
            self.wait(predicate=lambda: not ch._creating_channel)
            yield
            assert ch.active_channel["name"] == "Проверка создания"
            self.shot("32-channel-created")
            peer = lab.people[1][0]
            external = lab.request(
                peer, "create_channel", name="Приглашение в команду"
            )["channel"]
            assert (
                lab.request(
                    peer,
                    "send_channel_invite",
                    channel_id=external["id"],
                    to_user=lab.me,
                )["status"]
                == "ok"
            )
            ch.load_channel_invites(force=True)
            self.wait(predicate=lambda: bool(ch._invites))
            yield
            ch._set_invites_dropdown_open(True)
            self.wait()
            yield
            self.shot("33-channel-invite")
            ch.accept_channel_invite(ch._invites[0]["invite_id"])
            self.wait(predicate=lambda: not ch._responding_channel_invite)
            yield
            assert any(
                row["id"] == external["id"]
                for row in lab.request(lab.me, "get_my_channels")["channels"]
            )
            ch.open_join_page()
            ch.join_code_input.setText(external["code"])
            ch.join_channel()
            self.wait(predicate=lambda: not ch._joining_channel)
            yield
            self.shot("34-channel-joined")
            ch.open_channel(lab.channel)
            ch.open_channel_settings()
            self.wait(
                predicate=lambda: bool(ch._settings_permissions.get("manage_channel"))
            )
            yield
            ch.show_settings_section("access")
            ch.settings_text_perm_combo.setCurrentIndex(2)
            ch._mark_settings_edited()
            ch.save_channel_settings()
            self.wait(predicate=lambda: not ch._saving_channel_settings)
            yield
            denied = lab.request(
                lab.people[0][0],
                "send_channel_message",
                channel_id=lab.channel["id"],
                text="must not be saved",
            )
            assert denied["status"] == "error"
            self.shot("35-permissions-saved")
            ch.settings_text_perm_combo.setCurrentIndex(0)
            ch._mark_settings_edited()
            ch.save_channel_settings()
            self.wait(predicate=lambda: not ch._saving_channel_settings)
            yield
            self.workflow_checks += [
                "registration",
                "friend_request_accept",
                "create_channel",
                "channel_invite_accept",
                "join_channel",
                "profile_save",
                "text_permission_denial",
                "permission_restore",
                "outgoing_call",
                "incoming_decline",
                "incoming_accept_repeat",
            ]
            m.show_chats();c=m.chats_page.conversation;c.select(lab.people[0][0], 'Алексей')
            self.wait(predicate=lambda:not c.loading);yield
            from config import save_config
            save_config({'api_port':lab.free_port()})
            c.editor.setPlainText('Черновик при недоступной сети');c.send()
            self.wait(predicate=lambda:not c.pending);yield
            assert c.editor.toPlainText()=='Черновик при недоступной сети'
            self.shot('36-network-error-draft')
            save_config(lab.config);c.send()
            self.wait(predicate=lambda:not c.pending and not c.loading);yield
            assert not c.editor.toPlainText()
            assert not c.offline_note.text(), 'Successful retry must clear the offline warning'
            self.shot('37-network-retry-success')
            self.workflow_checks.extend(['real_connection_refusal_preserves_draft','retry_after_network_restore'])
            # Same 10,000-row database as the prototype; bounded live view.
            from server.storage.database import connect

            with connect(server.CHAT_DB) as conn:
                conn.executemany(
                    "INSERT INTO messages(from_user,to_user,text) VALUES(?,?,?)",
                    [
                        (
                            lab.people[0][0],
                            lab.me,
                            (
                                "Длинная история "
                                + str(i)
                                + " — проверка переноса строк. "
                            )
                            * (1 + i % 8),
                        )
                        for i in range(10000)
                    ],
                )
            m.show_chats()
            c = m.chats_page.conversation
            self.history_trace = []
            original_request = c.request
            def history_request(data, callback):
                def completed(response):
                    callback(response)
                    entry = dict(before_id=data.get('before_id'), after_id=data.get('after_id'),
                                 status=response.get('status'), message=response.get('message'),
                                 returned=len(response.get('messages', [])), loaded=len(c.rows),
                                 older=c.older, newer=c.newer, loading=c.loading)
                    self.history_trace.append(entry)
                    print('History:', entry, flush=True)
                original_request(data, completed)
            c.request = history_request
            c.select(lab.people[0][0], "Алексей Морозов")
            self.wait(predicate=lambda: not c.loading);yield
            c.load("latest")
            self.wait(predicate=lambda: not c.loading and len(c.rows) == 80)
            yield
            for _ in range(2):
                c.load("older")
                self.wait(predicate=lambda: not c.loading)
                yield
            assert len(c.rows) == 240, self.history_trace
            gaps = []
            last = [time.perf_counter()]
            timer = QTimer(w)
            timer.setInterval(10)

            def tick():
                now = time.perf_counter()
                gaps.append((now - last[0]) * 1000)
                last[0] = now

            timer.timeout.connect(tick)
            timer.start()
            for size in ((1120, 620), (1440, 900), (1280, 780)) * 3:
                w.resize(*size)
                self.wait(0.4)
                yield
            timer.stop()
            import numpy as np

            self.performance = dict(
                database_rows=10000,
                loaded_rows=len(c.rows),
                timer_interval_ms=10,
                timer_gap_p95_ms=float(np.percentile(gaps, 95)),
                timer_gap_max_ms=max(gaps),
                samples=len(gaps),
                prototype_reported_max_ms=675,
            )
            self.shot("29-long-history")
            # Short screen recording of actual navigation, with no active audio.
            frames = []
            frame_times = []
            recording_started = time.perf_counter()
            for view in (
                m.show_friends,
                m.show_chats,
                m.show_channels,
                m.show_profile,
                m.show_settings,
            ):
                view()
                for _ in range(16):
                    self.wait(0.02)
                    yield
                    from PIL import Image

                    image = (
                        w.grab()
                        .toImage()
                        .convertToFormat(
                            __import__(
                                "PySide6.QtGui", fromlist=["QImage"]
                            ).QImage.Format_RGBA8888
                        )
                    )
                    frame = Image.frombytes(
                        "RGBA", (image.width(), image.height()), bytes(image.bits())
                    )
                    frame.thumbnail((960, 960))
                    frames.append(frame)
                    frame_times.append(time.perf_counter() - recording_started)
            durations = [max(10, round((b-a)*1000/10)*10)
                         for a,b in zip(frame_times,frame_times[1:])]
            durations.append(durations[-1])
            frames[0].save(
                self.path / "interaction.gif",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=0,
            )
            self.recording = dict(file='interaction.gif', platform='offscreen',
                frame_times_seconds=frame_times, encoded_durations_ms=durations,
                frame_size=frames[0].size,
                note='Window captures with measured timestamps; capture cadence is not render FPS or native desktop evidence.')
            for cycle in range(max(1, args.relogin_cycles)):
                previous_token = m.ctx.session_token
                c.editor.setPlainText('Private draft before logout')
                m.perform_logout()
                self.wait(predicate=lambda: w.stack.currentWidget() == w.auth_page)
                yield
                self.shot('38-logged-out')
                assert not m.ctx.session_token
                w.auth_page.login.setText(lab.me)
                w.auth_page.password.setText('review-password')
                w.auth_page.login_user()
                # Authentication completes before the initial-data barrier opens
                # the main page. Wait for the same readiness users observe.
                self.wait(predicate=lambda: w.stack.currentWidget() == w.main_page
                          and bool(m.ctx.session_token), timeout=35)
                yield
                assert w.stack.currentWidget() == w.main_page and m.ctx.session_token, w.auth_page.status_label.text()
                assert m.ctx.session_token != previous_token
                assert not m.chats_page.conversation.drafts
                assert not m.chats_page.conversation.editor.toPlainText()
                self.workflow_checks.append('logout_relogin_clears_private_drafts')
                self.shot('39-relogged-in')

        def finish(self):
            self.timer.stop()
            (self.path / "review.json").write_text(
                json.dumps(
                    dict(
                        source_revision=self.source_revision,
                        source_tree_sha256=self.source_tree_sha256,
                        screens=self.log,
                        visual_fixtures=self.visual_fixtures,
                        error=self.error,
                        performance=getattr(self, "performance", None),
                        recording=getattr(self, "recording", None),
                        audio=getattr(self, "audio_results", None),
                        backdrop=getattr(self.w, "backdrop_description", None),
                        workflow_checks=getattr(self, "workflow_checks", []),
                        history_trace=getattr(self, "history_trace", []),
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print(self.error or f"Captured {len(self.log)} screens", flush=True)
            self.w.close()

    instances = []

    def init(w):
        instances.append(w)
        from PySide6.QtGui import QFont, QRawFont
        font = QRawFont.fromFont(QFont('Arial'))
        if not font.isValid() or not all(font.supportsCharacter(ord(c)) for c in 'NodusДрузья'):
            raise RuntimeError('UI review requires Latin and Cyrillic glyphs; refusing unreadable screenshots')
        original(w)
        w._review = Review(w)

    app_window.AppWindow.__init__ = init
    try:
        runpy.run_path(str(ROOT / "client/main.py"), run_name="__main__")
    except SystemExit:
        if instances and instances[0]._review.error:
            raise SystemExit(1)
        raise
    finally:
        lab.close()


if __name__ == "__main__":
    main()
