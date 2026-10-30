import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_foundation import load, ROOT


class HistoryStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.server = load("history_server", "server/server.py")
        self.server.DB_FILE = str(Path(self.folder.name) / "users.db")
        self.server.CHAT_DB = str(Path(self.folder.name) / "chat.db")
        self.server.init_db()
        self.server.init_chat_db()
        self.repo = self.server._messages_service()

    def test_read_receipt_does_not_mark_messages_arriving_after_displayed_tail(self):
        validate=load("read_receipt_requests", "server/protocol/requests.py").validate
        validate({"action":"mark_chat_read","friend_login":"bob","through_id":1})
        shown=self.repo.save_message("bob","alice","shown")
        self.repo.save_message("bob","alice","arrived later")
        self.repo.mark_chat_read("alice","bob",shown)
        self.assertEqual(self.repo.get_unread_counts("alice"),{"bob":1})
        self.assertEqual([r["is_read"] for r in self.repo.get_messages("alice","bob")],[1,0])

    def test_dialog_summaries_are_scoped_and_include_latest_direction(self):
        self.repo.save_message('alice', 'bob', 'old')
        self.repo.save_message('bob', 'alice', 'new reply')
        self.repo.save_message('alice', 'carol', 'x' * 500)
        self.repo.save_message('dave', 'eve', 'foreign private message')
        rows = self.repo.get_dialog_summaries('alice')
        self.assertEqual(set(rows), {'bob', 'carol'})
        self.assertEqual(rows['bob']['text'], 'new reply')
        self.assertFalse(rows['bob']['outgoing'])
        self.assertTrue(rows['carol']['outgoing'])
        self.assertEqual(len(rows['carol']['text']), 160)
        self.assertEqual(self.repo.get_dialog_summaries('nobody'), {})

    def test_equal_timestamps_all_pages_both_directions_and_foreign_cursor(self):
        from storage.database import connect

        with connect(self.server.CHAT_DB) as conn:
            for i in range(501):
                conn.execute(
                    "INSERT INTO messages(from_user,to_user,text,timestamp) VALUES('alice','bob',?,'2026-10-28 12:00:00')",
                    (str(i),),
                )
            foreign = conn.execute(
                "INSERT INTO messages(from_user,to_user,text) VALUES('carol','dave','private')"
            ).lastrowid
        latest = self.repo.get_page("alice", "bob", 80)
        seen = list(latest["messages"])
        page = latest
        while page["has_older"]:
            page = self.repo.get_page(
                "alice", "bob", 80, before_id=page["messages"][0]["id"]
            )
            seen = page["messages"] + seen
        self.assertEqual([r["text"] for r in seen], list(map(str, range(501))))
        forward = self.repo.get_page("alice", "bob", 80, after_id=seen[0]["id"])
        self.assertEqual(forward["messages"][0]["id"], seen[1]["id"])
        with self.assertRaises(ValueError):
            self.repo.get_page("alice", "bob", before_id=foreign)

    def test_retry_identity_survives_new_request_and_rejects_changed_payload(self):
        first = self.repo.save_message("alice", "bob", "hello", "stable-client-id")
        self.assertEqual(
            self.repo.save_message("alice", "bob", "hello", "stable-client-id"), first
        )
        with self.assertRaises(ValueError):
            self.repo.save_message("alice", "carol", "hello", "stable-client-id")
        self.assertEqual(len(self.repo.get_messages("alice", "bob")), 1)

    def test_new_messages_do_not_shift_older_page(self):
        for i in range(200):
            self.repo.save_message("alice", "bob", str(i))
        tail = self.repo.get_page("alice", "bob", 80)
        for i in range(200, 210):
            self.repo.save_message("bob", "alice", str(i))
        older = self.repo.get_page(
            "alice", "bob", 80, before_id=tail["messages"][0]["id"]
        )
        newer = self.repo.get_page(
            "alice", "bob", 80, after_id=tail["messages"][-1]["id"]
        )
        self.assertEqual(
            [r["text"] for r in older["messages"]], list(map(str, range(40, 120)))
        )
        self.assertEqual(
            [r["text"] for r in newer["messages"]], list(map(str, range(200, 210)))
        )
        self.assertEqual(len(self.repo.get_messages("alice", "bob", 500)), 210)


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, str(ROOT / "client"))
        from application.qt_runtime import prepare_platform_plugins
        from PySide6.QtWidgets import QApplication

        prepare_platform_plugins()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PySide6.QtWidgets import QWidget
        from ui.design.conversation import Conversation

        self.owner = QWidget()
        self.owner.ctx = SimpleNamespace(login="alice")
        self.requests = []
        self.owner.start_request = lambda data, callback: self.requests.append(
            (data, callback)
        )
        self.chat = Conversation(self.owner)
        self.addCleanup(self.owner.close)

    @staticmethod
    def response(peer="bob", count=2, start=1):
        return dict(
            status="ok",
            messages=[
                dict(
                    id=i,
                    from_user=peer,
                    text=f"message {i}",
                    created_at="2026-10-28 12:00:00",
                )
                for i in range(start, start + count)
            ],
            has_older=False,
            has_newer=False,
        )

    def select(self, peer):
        self.chat.select(peer, peer.title())
        self.requests[-1][1](self.response(peer))

    def test_picked_image_preview_and_remove_are_scoped_to_dialog(self):
        import tempfile
        from PySide6.QtGui import QImage, QColor
        self.select('bob')
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'preview.png')
            image = QImage(80, 60, QImage.Format_RGB32)
            image.fill(QColor('#89AAFF'))
            self.assertTrue(image.save(path))
            with patch('ui.design.conversation.QFileDialog.getOpenFileName', return_value=(path, '')):
                self.chat.choose_attachment()
            self.assertFalse(self.chat.attachment_strip.isHidden())
            self.assertFalse(self.chat.attachment_preview.pixmap().isNull())
            self.select('carol')
            self.assertTrue(self.chat.attachment_strip.isHidden())
            self.select('bob')
            self.assertFalse(self.chat.attachment_strip.isHidden())
            self.chat.remove_attachment()
            self.assertTrue(self.chat.attachment_strip.isHidden())

    def test_inline_image_load_preserves_geometry_and_opens_viewer_without_save_dialog(self):
        from PySide6.QtGui import QImage, QColor
        self.owner.resize(1280, 800)
        self.owner.show()
        self.chat.resize(800, 600)
        self.chat.show()
        self.chat.select('bob', 'Bob')
        response = self.response(count=1)
        meta = dict(id='d'*32, name='photo.png', size=300, sha256='e'*64)
        response['messages'][0]['attachment'] = meta
        self.requests[-1][1](response)
        message = self.chat.model.rows[0]
        before = self.chat.delegate.geometry(message, 800)
        image = QImage(640, 360, QImage.Format_RGB32)
        image.fill(QColor('#89AAFF'))
        self.chat.image_cache.images[meta['id']] = image
        after = self.chat.delegate.geometry(message, 800)
        self.assertEqual(before[1:], after[1:])
        self.assertEqual(self.chat.compose_frame.layout().contentsMargins().left(),
                         self.chat.compose_frame.layout().contentsMargins().right())
        with patch('ui.design.conversation.QFileDialog.getSaveFileName') as save:
            self.chat.open_attachment(self.chat.model.index(0))
            self.app.processEvents()
            self.assertTrue(self.chat.image_viewer.isVisible())
            self.assertIs(self.chat.image_viewer.canvas.image, image)
            self.owner.resize(1120, 620)
            self.app.processEvents()
            self.assertLessEqual(self.chat.image_viewer.width(), self.owner.width())
            self.chat.image_viewer.reject()
            save.assert_not_called()

    def test_attachment_only_send_keeps_target_and_draft_on_failure(self):
        self.select('bob')
        self.chat.attachment_drafts['bob'] = dict(id='a'*32, name='test.png', size=3)
        self.chat.send()
        request, done = self.requests[-1]
        self.assertEqual(request['to_user'], 'bob')
        self.assertEqual(request['attachment_id'], 'a'*32)
        self.assertEqual(request['text'], '')
        self.select('carol')
        done(dict(status='error', message='offline'))
        self.assertIn('bob', self.chat.attachment_drafts)
        self.select('bob')
        self.chat.send()
        retry, done = self.requests[-1]
        self.assertEqual(request['client_message_id'], retry['client_message_id'])
        done(dict(status='ok', message_id=99))
        self.assertNotIn('bob', self.chat.attachment_drafts)

    def test_attachment_metadata_survives_render_and_permission_disables_picker(self):
        self.chat.select('bob', 'Bob')
        response = self.response()
        response['messages'][0]['text'] = ''
        response['messages'][0]['attachment'] = dict(id='b'*32, name='image.png', size=200, sha256='c'*64)
        self.requests[-1][1](response)
        self.assertEqual(self.chat.model.rows[0].attachment['name'], 'image.png')
        self.assertEqual(self.chat.model.rows[0].text, 'image.png')
        self.chat.can_send = False
        self.chat.update_controls()
        self.assertFalse(self.chat.attach_button.isEnabled())

    def test_network_recovery_preserves_draft_and_is_scoped_to_dialog(self):
        self.select('bob')
        self.chat.editor.setPlainText('unsent draft')
        self.chat.load('latest')
        self.requests[-1][1](dict(status='error',code='network_error',message='Offline'))
        self.assertTrue(self.chat.offline_note.text())
        self.chat.load('latest');self.requests[-1][1](self.response())
        self.assertFalse(self.chat.offline_note.text())
        self.assertFalse(self.chat.connection_restored.isHidden())
        self.assertEqual(self.chat.editor.toPlainText(),'unsent draft')
        self.chat.select('carol')
        self.assertTrue(self.chat.connection_restored.isHidden())
        self.requests[-1][1](dict(status='error',message='Permission denied'))
        self.assertFalse(self.chat.offline_note.text())

    def test_message_identity_uses_current_peer_and_channel_profiles(self):
        self.owner.active_friend = dict(login="bob", nickname="Bob Updated", avatar="peer-avatar")
        self.select("bob")
        self.assertEqual(self.chat.model.rows[0].avatar, "peer-avatar")
        self.assertEqual(self.chat.model.rows[0].name, "Bob Updated")
        self.owner.ctx.avatar = "own-avatar"
        self.chat.apply(self.response("alice")["messages"], "latest", {})
        self.assertEqual(self.chat.model.rows[0].avatar, "own-avatar")
        self.assertEqual(self.chat.model.rows[0].name, "Вы")
        self.owner.active_friend = None
        self.owner._channel_details = dict(members=[dict(login="bob", nickname="Channel Bob", avatar="channel-avatar")])
        self.chat.channel = 1
        self.chat.rows = []
        self.chat.apply(self.response()["messages"], "latest", {})
        self.assertEqual(self.chat.model.rows[0].avatar, "channel-avatar")
        self.assertEqual(self.chat.model.rows[0].name, "Channel Bob")

    def test_prefetch_is_bounded_does_not_mark_read_and_populates_first_open(self):
        self.chat.prefetch(["bob","carol","dan"])
        self.assertEqual(len(self.requests),2)
        self.assertTrue(all(r[0]["action"]=="get_messages" for r in self.requests))
        self.requests[0][1](self.response("bob"))
        self.assertEqual(len(self.requests),3)
        self.assertIsNone(self.chat.identity)
        self.chat.select("bob")
        self.assertEqual(len(self.chat.model.rows),2)
        self.assertTrue(self.chat.history_loaded)
        self.assertIs(self.chat.history_stack.currentWidget(),self.chat.view)
        self.assertEqual(self.requests[-1][0]["after_id"],2)
        stale=self.requests[1][1]
        self.chat.reset()
        stale(self.response("carol"))
        self.assertFalse(self.chat.prefetched)

    def test_channel_prefetch_uses_channel_scope_and_first_open_cache(self):
        self.chat.channel=True
        self.chat.prefetch([41,42,43])
        self.assertEqual(len(self.requests),2)
        self.assertEqual(self.requests[0][0]['action'],'get_channel_messages')
        self.assertEqual(self.requests[0][0]['channel_id'],41)
        self.assertNotIn('to_user',self.requests[0][0])
        self.requests[0][1](self.response())
        self.chat.select(41)
        self.assertTrue(self.chat.history_loaded)
        self.assertEqual(len(self.chat.model.rows),2)
        self.assertEqual(self.requests[-1][0]['channel_id'],41)
        self.assertEqual(self.requests[-1][0]['after_id'],2)

    def test_first_open_keeps_composer_and_history_in_place_until_reply(self):
        self.chat.select("bob")
        self.assertTrue(self.chat.loading)
        self.assertIs(self.chat.history_stack.currentWidget(),self.chat.view)
        self.assertFalse(self.chat.editor.isReadOnly())
        self.chat.editor.setPlainText("Draft while fetching")
        self.requests[-1][1](self.response())
        self.assertIs(self.chat.history_stack.currentWidget(),self.chat.view)
        self.assertEqual(self.chat.editor.toPlainText(),"Draft while fetching")

    def test_revisited_chat_renders_cache_before_network_reply_and_reset_clears_it(self):
        self.select("bob")
        original=list(self.chat.model.rows)
        self.chat.select("carol")
        stale=self.requests[-1][1]
        self.chat.select("bob")
        self.assertEqual(self.chat.model.rows,original)
        self.assertIs(self.chat.history_stack.currentWidget(),self.chat.view)
        self.assertTrue(self.chat.loading)
        stale(self.response("carol"))
        self.assertEqual(self.chat.model.rows,original)
        self.requests[-1][1](self.response("bob",count=1,start=3))
        self.assertEqual([m.id for m in self.chat.model.rows],[1,2,3])
        self.chat.reset()
        self.assertFalse(self.chat.history_cache)
        self.assertFalse(self.chat.model.rows)

    def test_reopen_preserves_reading_position_after_layout_and_background_reply(self):
        from PySide6.QtTest import QTest
        self.chat.resize(800, 560)
        self.owner.show()
        self.chat.show()
        self.chat.select("bob")
        self.requests[-1][1](self.response(count=80))
        QTest.qWait(150)
        bar = self.chat.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        saved = self.chat.anchor()
        self.assertIsNotNone(saved)
        self.chat.select("carol")
        self.requests[-1][1](self.response("carol", count=80))
        # Queue the resize restoration belonging to the other conversation.
        self.chat.resize(760, 560)
        self.app.processEvents()
        self.chat.select("bob")
        self.requests[-1][1](self.response(count=1, start=81))
        QTest.qWait(150)
        self.assertEqual(self.chat.anchor(), saved)

    def test_first_open_and_reopened_tail_stay_at_latest_after_resize_timer(self):
        from PySide6.QtTest import QTest
        self.chat.resize(800, 560)
        self.owner.show()
        self.chat.show()
        self.chat.select("bob")
        self.requests[-1][1](self.response(count=80))
        QTest.qWait(150)
        bar = self.chat.view.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        self.assertEqual(bar.value(), bar.maximum())
        self.chat.select("carol")
        self.requests[-1][1](self.response("carol", count=0))
        self.chat.select("bob")
        self.requests[-1][1](self.response(count=1, start=81))
        QTest.qWait(150)
        self.assertEqual(bar.value(), bar.maximum())
        # Closing and reopening without a reply must also retain the position.
        bar.setValue(bar.maximum() // 3)
        saved = self.chat.anchor()
        self.chat.select(None)
        self.chat.select("bob")
        QTest.qWait(150)
        self.assertEqual(self.chat.anchor(), saved)

    def test_history_cache_is_bounded_and_remembers_empty_chats(self):
        for i in range(25):
            self.chat.select(str(i))
            self.requests[-1][1]({"status":"ok","messages":[]})
        self.chat.select("23")
        self.assertLessEqual(len(self.chat.history_cache),20)
        self.assertIs(self.chat.history_stack.currentWidget(),self.chat.empty_state)
        self.assertTrue(self.chat.loading)

    def test_empty_private_and_channel_poll_keeps_empty_surface(self):
        for channel in (False, True):
            self.chat.channel = channel
            self.chat.select("bob")
            self.requests[-1][1]({"status":"ok","messages":[]})
            self.assertIs(self.chat.history_stack.currentWidget(),self.chat.empty_state)
            with patch.object(self.chat.view,"doItemsLayout") as layout:
                for _ in range(3):
                    self.chat.load("poll")
                    self.assertIs(self.chat.history_stack.currentWidget(),self.chat.empty_state)
                    self.requests[-1][1]({"status":"ok","messages":[]})
                    self.assertIs(self.chat.history_stack.currentWidget(),self.chat.empty_state)
                layout.assert_not_called()

    def test_background_poll_does_not_move_history_or_composer(self):
        from PySide6.QtTest import QTest
        self.owner.ctx.nickname = "Alice"
        self.owner.resize(800, 650)
        self.chat.resize(800, 650)
        self.owner.show()
        self.chat.show()
        self.select("bob")
        self.assertLessEqual(self.chat.editor.height(), max(44, self.chat.editor.fontMetrics().lineSpacing() + 24))
        QTest.qWait(50)
        before = (self.chat.history_stack.geometry(), self.chat.compose_frame.geometry())
        self.chat.load("poll")
        self.app.processEvents()
        self.assertEqual(before, (self.chat.history_stack.geometry(), self.chat.compose_frame.geometry()))
        self.requests[-1][1](self.response())
        self.app.processEvents()
        self.assertEqual(before, (self.chat.history_stack.geometry(), self.chat.compose_frame.geometry()))

    def test_unread_boundary_survives_receipts_and_resets_between_dialogs(self):
        self.chat.select('bob')
        response=self.response(count=3)
        response['messages'][0]['is_read']=True
        self.requests[-1][1](response)
        self.assertEqual([(m.id,m.unread_count) for m in self.chat.model.rows],[(1,0),(2,2),(3,0)])
        self.chat.apply([dict(row,is_read=True) for row in response['messages']], 'latest',response)
        self.assertEqual(self.chat.model.rows[1].unread_count,2)
        self.chat.select('carol')
        self.requests[-1][1](dict(status='ok',messages=[],has_older=False,has_newer=False))
        self.assertIsNone(self.chat.unread_boundary)
        self.chat.apply(self.response('carol',1)['messages'],'poll',{})
        self.assertEqual(self.chat.model.rows[0].unread_count,0)

    def test_rapid_switch_discards_old_results_and_loading_state(self):
        for peer in ("bob", "carol", "dave"):
            self.chat.select(peer, peer)
        self.requests[0][1](self.response("bob"))
        self.assertTrue(self.chat.loading)
        self.requests[2][1](self.response("dave"))
        self.requests[1][1](dict(status="error", message="old error"))
        self.assertEqual(self.chat.identity, "dave")
        self.assertEqual({r["from_user"] for r in self.chat.rows}, {"dave"})
        self.assertFalse(self.chat.loading)

    def test_failed_empty_history_can_retry_without_losing_draft(self):
        self.chat.select('bob')
        self.assertIs(self.chat.history_stack.currentWidget(), self.chat.view)
        self.chat.editor.setPlainText('Draft while offline')
        self.requests[-1][1]({'status':'error','message':'Offline'})
        self.assertIs(self.chat.history_stack.currentWidget(), self.chat.error_state)
        from PySide6.QtWidgets import QPushButton
        self.chat.error_state.findChild(QPushButton).click()
        self.requests[-1][1](self.response(count=0))
        self.assertIs(self.chat.history_stack.currentWidget(), self.chat.empty_state)
        self.assertEqual(self.chat.editor.toPlainText(),'Draft while offline')
        self.chat.load()
        self.requests[-1][1](self.response())
        self.assertIs(self.chat.history_stack.currentWidget(), self.chat.view)

    def test_successful_send_supersedes_an_offline_poll(self):
        self.select("bob")
        self.chat.offline_note.setText("Нет соединения")
        self.chat.load("poll")
        old_poll = self.requests[-1][1]
        self.chat.editor.setPlainText("retry")
        self.chat.send()
        self.requests[-1][1](dict(status="ok"))
        latest = self.requests[-1][1]
        self.assertTrue(self.chat.loading)
        self.assertFalse(self.chat.offline_note.text())
        old_poll(dict(status="error", code="network_error", message="Offline"))
        self.assertFalse(self.chat.offline_note.text())
        self.assertTrue(self.chat.loading)
        latest(self.response())
        self.assertFalse(self.chat.loading)
        self.assertFalse(self.chat.history_error)

    def test_send_keeps_editor_focus_and_late_ack_does_not_steal_it(self):
        from PySide6.QtWidgets import QVBoxLayout,QPushButton
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        layout=QVBoxLayout(self.owner);layout.addWidget(self.chat)
        other=QPushButton('+');layout.addWidget(other)
        self.owner.show();self.owner.activateWindow();self.app.processEvents()
        notices=[];self.chat.notice.connect(notices.append)
        for channel in (False,True):
            self.chat.channel=channel
            self.chat.select((1,0) if channel else 'bob','Test')
            self.requests[-1][1](self.response())
            self.chat.editor.setPlainText('send by button')
            self.chat.send_button.setFocus();self.app.processEvents()
            self.chat.send_button.click()
            self.assertTrue(self.chat.editor.hasFocus())
            callback=self.requests[-1][1]
            callback(dict(status='ok'))
            self.requests[-1][1](self.response())
            self.app.processEvents()
            self.assertTrue(self.chat.editor.hasFocus())
            self.assertEqual(notices,[])
            self.chat.editor.setPlainText('send by enter')
            QTest.keyClick(self.chat.editor,Qt.Key_Return)
            callback=self.requests[-1][1]
            self.assertTrue(self.chat.editor.hasFocus())
            other.setFocus();self.app.processEvents()
            callback(dict(status='ok'))
            self.requests[-1][1](self.response())
            self.app.processEvents()
            self.assertTrue(other.hasFocus())
            self.assertEqual(notices,[])
            # Polling must preserve an intentionally chosen focus as well.
            self.chat.load('poll');self.requests[-1][1](self.response())
            self.assertTrue(other.hasFocus())

    def test_pending_send_preserves_composer_geometry_and_updates_summary_on_ack(self):
        from unittest.mock import Mock
        self.select("bob")
        self.chat.show();self.app.processEvents()
        self.chat.owner.message_sent=Mock()
        self.chat.editor.setPlainText("steady message")
        self.app.processEvents()
        before=self.chat.compose_frame.geometry()
        self.chat.send();self.app.processEvents()
        self.assertTrue(self.chat.send_button.isEnabled())
        requests_before=len(self.requests)
        self.chat.send()
        self.assertEqual(len(self.requests),requests_before)
        self.assertEqual(self.chat.compose_frame.geometry(),before)
        self.assertTrue(self.chat.send_status.isHidden())
        self.chat.owner.message_sent.assert_not_called()
        self.requests[-1][1](dict(status="ok"))
        self.app.processEvents()
        self.assertEqual(self.chat.compose_frame.geometry(),before)
        self.assertEqual(self.chat.owner.message_sent.call_args.args[:2],("bob","steady message"))

    def test_failed_send_retains_draft_and_reuses_identity(self):
        self.select("bob")
        self.chat.editor.setPlainText("first\nsecond")
        self.chat.send()
        first, callback = self.requests[-1]
        callback(dict(status="error", message="Connection lost after commit"))
        self.assertEqual(self.chat.editor.toPlainText(), "first\nsecond")
        self.chat.send()
        self.assertEqual(
            self.requests[-1][0]["client_message_id"], first["client_message_id"]
        )

    def test_ack_does_not_clear_new_text_or_other_dialog(self):
        self.select("bob")
        self.chat.editor.setPlainText("old")
        self.chat.send()
        callback = self.requests[-1][1]
        self.chat.editor.setPlainText("new")
        self.select("carol")
        self.chat.editor.setPlainText("carol draft")
        callback(dict(status="ok"))
        self.assertEqual(self.chat.editor.toPlainText(), "carol draft")
        self.select("bob")
        self.assertEqual(self.chat.editor.toPlainText(), "new")

    def test_ack_does_not_clear_retyped_identical_text(self):
        self.select("bob")
        self.chat.editor.setPlainText("same")
        self.chat.send()
        callback = self.requests[-1][1]
        self.chat.editor.clear()
        self.chat.editor.setPlainText("same")
        callback(dict(status="ok"))
        self.assertEqual(self.chat.editor.toPlainText(), "same")

    def test_window_is_bounded_but_old_history_is_navigable(self):
        self.select("bob")
        self.chat.apply(
            self.response(count=80, start=401)["messages"],
            "latest",
            dict(has_older=True, has_newer=False),
        )
        for start in (321, 241, 161):
            self.chat.apply(
                self.response(count=80, start=start)["messages"],
                "older",
                dict(has_older=True, has_newer=True),
            )
        self.assertEqual(len(self.chat.rows), 240)
        self.assertEqual(self.chat.rows[0]["id"], 161)
        self.assertTrue(self.chat.newer)
        self.chat.apply(
            self.response(count=80, start=401)["messages"],
            "newer",
            dict(has_newer=False),
        )
        self.assertEqual(len(self.chat.rows), 240)
        self.assertEqual(self.chat.rows[-1]["id"], 480)

    def test_session_reset_drops_late_send_callback(self):
        self.select("bob")
        self.chat.editor.setPlainText("old")
        self.chat.send()
        callback = self.requests[-1][1]
        self.chat.reset()
        self.select("bob")
        self.chat.editor.setPlainText("another account")
        callback(dict(status="ok"))
        self.assertEqual(self.chat.editor.toPlainText(), "another account")
