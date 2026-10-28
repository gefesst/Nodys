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
