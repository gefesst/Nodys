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

    def test_history_cache_is_bounded_and_remembers_empty_chats(self):
        for i in range(25):
            self.chat.select(str(i))
            self.requests[-1][1]({"status":"ok","messages":[]})
        self.chat.select("23")
        self.assertLessEqual(len(self.chat.history_cache),20)
        self.assertIs(self.chat.history_stack.currentWidget(),self.chat.empty_state)
        self.assertTrue(self.chat.loading)

    def test_empty_private_and_channel_poll_keeps_empty_surface(self):
        from unittest.mock import patch
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
