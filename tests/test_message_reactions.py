"""Reaction writes are authenticated, scoped, idempotent and revisioned."""
import unittest
import uuid
import test_message_actions as fixtures
from test_voice_authorization import VoiceFixture


class ReactionTests(VoiceFixture, unittest.TestCase):
    request = fixtures.MessageActionsTests.request
    send = fixtures.MessageActionsTests.send

    def setUp(self):
        super().setUp()
        self.server.send_friend_request('alice', 'bob')
        self.server.accept_friend_request('alice', 'bob')

    def test_both_scopes_add_remove_retry_refresh_and_delete(self):
        for channel in (False, True):
            row, fields = self.send(channel)
            peer = fields if channel else dict(to_user='alice')
            history = 'get_channel_messages' if channel else 'get_messages'
            data = dict(fields, message_id=row['id'], emoji='❤️', active=True, request_id=uuid.uuid4().hex)
            result = self.request('alice', 'set_message_reaction', **data)
            self.assertEqual(result['status'], 'ok', result)
            self.assertEqual(result, self.request('alice', 'set_message_reaction', **data))
            self.assertEqual(result['message']['reactions'], [dict(emoji='❤️', count=1, mine=True)])
            result = self.request('bob', history, **peer, paged=True, visible_versions=f"{row['id']}:0")
            self.assertEqual(result['messages'][-1]['reactions'], [dict(emoji='❤️', count=1, mine=False)])
            self.assertEqual(result['updated_messages'][0]['revision'], 1)
            result = self.request('bob', 'set_message_reaction', **peer, message_id=row['id'], emoji='❤️', active=True)
            self.assertEqual(result['message']['reactions'][0]['count'], 2)
            result = self.request('alice', 'set_message_reaction', **dict(data, active=False, request_id=uuid.uuid4().hex))
            self.assertEqual(result['message']['reactions'], [dict(emoji='❤️', count=1, mine=False)])
            revision = result['message']['revision']
            self.request('alice', 'delete_message', **fields, message_id=row['id'], expected_revision=revision)
            self.assertEqual(self.request('bob', 'set_message_reaction', **peer, message_id=row['id'], emoji='❤️', active=True)['status'], 'error')
            with self.server.database_connection(self.server.CHAT_DB) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM message_reactions').fetchone()[0], 0)

    def test_scope_permission_and_invalid_palette(self):
        row, fields = self.send(True)
        for extra in (dict(emoji='x', active=True), dict(emoji='👍', active='yes'), dict(emoji='👍', active=True, room_id=999)):
            self.assertEqual(self.request('bob', 'set_message_reaction', **dict(fields, message_id=row['id'], **extra))['status'], 'error')
        self.request('bob', 'leave_channel', **fields)
        self.assertEqual(self.request('bob', 'set_message_reaction', **fields, message_id=row['id'], emoji='👍', active=True)['status'], 'error')
        row, fields = self.send()
        self.assertEqual(self.request('bob', 'set_message_reaction', to_user='third', message_id=row['id'], emoji='👍', active=True)['status'], 'error')

    def test_channel_deletion_cleans_reactions(self):
        row, fields = self.send(True)
        result = self.request('alice', 'set_message_reaction', **fields, message_id=row['id'], emoji='🔥', active=True)
        self.assertEqual(result['status'], 'ok', result)
        result = self.request('alice', 'delete_channel', **fields)
        self.assertEqual(result['status'], 'ok', result)
        with self.server.database_connection(self.server.CHAT_DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM message_reactions').fetchone()[0], 0)
