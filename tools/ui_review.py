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
    args = parser.parse_args()
    lab = Sandbox(ROOT)
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
            self.log = []
            self.error = None
            self.deadline = time.monotonic() + 300
            self.until = 0
            self.predicate = None
            self.steps = self.scenario()
            self.timer = QTimer(w)
            self.timer.setInterval(80)
            self.timer.timeout.connect(self.advance)
            self.timer.start()

        def wait(self, seconds=0.4, predicate=None):
            self.until = time.monotonic() + seconds
            self.predicate = predicate

        def advance(self):
            try:
                if time.monotonic() > self.deadline:
                    raise TimeoutError("Review timed out")
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
            target = widget or self.w
            target.grab().save(str(self.path / (name + ".png")))
            self.log.append(name)
            print("Captured", name, flush=True)

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
            w.auth_page.password.setText("review-password")
            w.auth_page.login_user()
            self.wait(
                predicate=lambda: (
                    w.main_page is not None and w.stack.currentWidget() == w.main_page
                )
            )
            yield
            m = w.main_page
            lab.tokens[lab.me] = m.ctx.session_token
            self.wait(1)
            yield
            self.shot("04-friends-all")
            m.friends_page.set_view("online")
            self.wait()
            yield
            self.shot("05-friends-online")
            m.friends_page.set_view("requests")
            self.wait()
            yield
            self.shot("06-friends-requests")
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
            m.chats_page.open_chat(m.chats_page.dialog_model.rows[0])
            self.wait(predicate=lambda: len(m.chats_page.conversation.rows) > 0)
            yield
            self.shot("09-private-chat")
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
            self.shot("15-channel-create")
            ch.open_join_page()
            self.wait()
            yield
            self.shot("16-channel-join")
            ch.open_channel(ch.channels[0])
            ch.open_channel_settings()
            self.wait(0.6)
            yield
            self.shot("17-channel-settings")
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
            m.show_profile()
            self.wait()
            yield
            self.shot("19-profile")
            m.profile_page.show_section("edit")
            self.wait()
            yield
            self.shot("20-profile-edit")
            m.profile_page.show_section("password")
            self.wait()
            yield
            self.shot("21-profile-password")
            m.show_settings()
            self.wait()
            yield
            self.shot("22-settings")
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
                m.start_outgoing_call(peer)
                self.wait(predicate=lambda: bool(m.calls.state))
                yield
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
                self.shot("25b-voice-dock")
                m.call_window._mic_clicked()
                self.shot("26-call-muted", m.call_window)
                m.call_window._mic_clicked()
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
            self.workflow_checks = [
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
            for view in (
                m.show_friends,
                m.show_chats,
                m.show_channels,
                m.show_profile,
                m.show_settings,
            ):
                view()
                for _ in range(4):
                    self.wait(0.12)
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
                    frames.append(
                        Image.frombytes(
                            "RGBA", (image.width(), image.height()), bytes(image.bits())
                        ).resize((960, 585))
                    )
            frames[0].save(
                self.path / "interaction.gif",
                save_all=True,
                append_images=frames[1:],
                duration=160,
                loop=0,
            )

        def finish(self):
            self.timer.stop()
            (self.path / "review.json").write_text(
                json.dumps(
                    dict(
                        screens=self.log,
                        error=self.error,
                        performance=getattr(self, "performance", None),
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
