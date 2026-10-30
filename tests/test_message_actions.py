"""Message changes are scoped, author-only, versioned and visible to both peers."""
import unittest
import uuid
import test_attachments as attachment_fixtures
from test_voice_authorization import VoiceFixture


class MessageActionsTests(VoiceFixture, unittest.TestCase):
    request = attachment_fixtures.AttachmentTests.request
    upload = attachment_fixtures.AttachmentTests.upload
    # Reuse the real two-user DB/voice fixture and upload helper, not its test cases.
    def setUp(self):
        super().setUp()
        self.server.send_friend_request('alice', 'bob')
        self.server.accept_friend_request('alice', 'bob')

    def send(self, channel=False, **extra):
        fields = dict(channel_id=self.channel['id']) if channel else dict(to_user='bob')
        self.request('alice', 'send_channel_message' if channel else 'send_message', text='original', **fields, **extra)
        page = self.request('alice', 'get_channel_messages' if channel else 'get_messages', paged=True, **fields)
        return page['messages'][-1], fields

    def test_edit_delete_refresh_and_summary(self):
        row, fields = self.send()
        edit = dict(fields, message_id=row['id'], expected_revision=0, text='changed', request_id=uuid.uuid4().hex)
        result = self.request('alice', 'edit_message', **edit)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result, self.request('alice', 'edit_message', **edit))
        self.assertEqual(result['message']['revision'], 1)
        self.assertTrue(result['message']['edited_at'])
        poll = self.request('bob', 'get_messages', to_user='alice', paged=True, after_id=row['id'], visible_versions=f"{row['id']}:0")
        self.assertEqual(poll['messages'], [])
        self.assertEqual(poll['updated_messages'][0]['text'], 'changed')
        unchanged = self.request('bob', 'get_messages', to_user='alice', paged=True, after_id=row['id'], visible_versions=f"{row['id']}:1")
        self.assertEqual(unchanged['updated_messages'], [])
        self.assertEqual(self.request('alice', 'get_unread_counts')['summaries']['bob']['text'], 'changed')
        denied = self.request('alice', 'edit_message', **dict(edit, text='stale', request_id='stale'))
        self.assertEqual(denied['code'], 'message_changed')
        deleted = self.request('alice', 'delete_message', **fields, message_id=row['id'], expected_revision=1)
        self.assertEqual(deleted['status'], 'ok', deleted)
        self.assertTrue(deleted['message']['deleted_at'])
        self.assertEqual(deleted['message']['text'], '')
        self.assertEqual(self.request('bob', 'get_unread_counts')['counts'], {})
        self.assertNotIn('alice', self.request('bob', 'get_unread_counts')['summaries'])
        self.assertEqual(self.request('bob', 'get_messages', to_user='alice', paged=True, after_id=row['id'])['status'], 'ok')

    def test_deleted_rows_disappear_from_pages_but_updates_still_reach_peers(self):
        for channel in (False, True):
            first, fields = self.send(channel)
            last, _ = self.send(channel)
            action = 'get_channel_messages' if channel else 'get_messages'
            self.request('alice', 'delete_message', **fields, message_id=last['id'], expected_revision=0)
            page = self.request('alice', action, **fields, paged=True, limit=1,
                                visible_versions=f"{last['id']}:0")
            self.assertEqual([r['id'] for r in page['messages']], [first['id']])
            self.assertFalse(page['has_newer'])
            self.assertTrue(page['updated_messages'][0]['deleted_at'])
            if not channel:
                self.assertEqual(self.request('bob', 'get_unread_counts')['summaries']['alice']['text'], 'original')
            self.request('alice', 'delete_message', **fields, message_id=first['id'], expected_revision=0)
            self.assertEqual(self.request('alice', action, **fields, paged=True)['messages'], [])

    def test_author_scope_and_channel_permissions(self):
        for channel in (False, True):
            row, fields = self.send(channel)
            other = fields if channel else dict(to_user='alice')
            for action in ('edit_message', 'delete_message'):
                result = self.request('bob', action, **other, message_id=row['id'], expected_revision=0, text='stolen')
                self.assertEqual(result['status'], 'error', result)
            if channel:
                denied = self.request('alice', 'edit_message', channel_id=self.channel['id'], room_id=999, message_id=row['id'], expected_revision=0, text='wrong room')
                self.assertEqual(denied['status'], 'error')
                result = self.request('alice', 'edit_message', **fields, message_id=row['id'], expected_revision=0, text='channel edit')
                self.assertEqual(result['status'], 'ok', result)
                poll = self.request('bob', 'get_channel_messages', **fields, paged=True, visible_versions=f"{row['id']}:0")
                self.assertEqual(poll['updated_messages'][0]['text'], 'channel edit')
                self.request('bob', 'leave_channel', **fields)
                self.assertEqual(self.request('bob', 'get_channel_messages', **fields, paged=True, visible_versions=f"{row['id']}:0")['status'], 'error')
            else:
                self.server.add_user('third', 'synthetic', 'third', '')
                self.tokens['third'] = self.server.create_session('third')[0]
                poll = self.request('third', 'get_messages', to_user='alice', paged=True, visible_versions=f"{row['id']}:0")
                self.assertEqual(poll['updated_messages'], [])

    def test_delete_attachment_reclaims_storage(self):
        aid = self.upload(to_user='bob')
        row, fields = self.send(attachment_id=aid)
        result = self.request('alice', 'delete_message', **fields, message_id=row['id'], expected_revision=0)
        self.assertEqual(result['status'], 'ok', result)
        self.assertNotIn('attachment', result['message'])
        with self.server.database_connection(self.server.CHAT_DB) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM attachments').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM attachment_chunks').fetchone()[0], 0)
        self.assertEqual(self.request('bob', 'download_attachment_chunk', attachment_id=aid)['status'], 'error')

    def test_invalid_updates_empty_edit_and_deleted_cannot_resurrect(self):
        row, fields = self.send()
        for ids in ('1 OR 1=1', ',1', '0', '1,' * 240 + '1', str(2**64)):
            self.assertEqual(self.request('alice', 'get_messages', **fields, paged=True, visible_versions=ids)['status'], 'error')
        self.assertEqual(self.request('alice', 'edit_message', **fields, message_id=row['id'], expected_revision=0, text='  ')['status'], 'error')
        self.request('alice', 'delete_message', **fields, message_id=row['id'], expected_revision=0)
        self.assertEqual(self.request('alice', 'edit_message', **fields, message_id=row['id'], expected_revision=1, text='resurrect')['status'], 'error')
