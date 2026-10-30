"""Replies cannot cross conversation boundaries; quotes and navigation stay current."""
import unittest
import uuid
import test_message_actions as fixtures
from test_voice_authorization import VoiceFixture


class ReplyTests(VoiceFixture, unittest.TestCase):
    request = fixtures.MessageActionsTests.request
    send = fixtures.MessageActionsTests.send
    upload = fixtures.MessageActionsTests.upload

    def setUp(self):
        super().setUp()
        self.server.send_friend_request('alice', 'bob')
        self.server.accept_friend_request('alice', 'bob')

    def test_replies_update_after_original_edit_and_delete_in_both_scopes(self):
        for channel in (False, True):
            original, fields = self.send(channel)
            other = fields if channel else dict(to_user='alice')
            action = 'send_channel_message' if channel else 'send_message'
            history = 'get_channel_messages' if channel else 'get_messages'
            result = self.request('bob', action, **other, text='answer', reply_to_id=original['id'])
            self.assertEqual(result['status'], 'ok', result)
            rows = self.request('bob', history, **other, paged=True)['messages']
            answer = rows[-1]
            self.assertEqual(answer['reply']['author'], 'alice')
            self.assertEqual(answer['reply']['text'], 'original')
            self.request('alice', 'edit_message', **fields, message_id=original['id'], expected_revision=0, text='changed')
            updates = self.request('bob', history, **other, paged=True, after_id=answer['id'], visible_versions=f"{answer['id']}:0")['updated_messages']
            self.assertEqual(updates[0]['reply']['text'], 'changed')
            self.request('alice', 'delete_message', **fields, message_id=original['id'], expected_revision=1)
            answer = self.request('bob', history, **other, paged=True)['messages'][-1]
            self.assertEqual(answer['text'], 'answer')
            self.assertTrue(answer['reply']['deleted'])
            self.assertEqual(answer['reply']['text'], 'Сообщение удалено')
            rejected = self.request('bob', action, **other, text='new answer', reply_to_id=original['id'])
            self.assertEqual(rejected['status'], 'error')
            anchor = self.request('bob', history, **other, paged=True, around_id=original['id'])
            self.assertEqual(anchor['status'], 'ok')
            self.assertTrue(anchor['messages'][0]['deleted_at'])

    def test_reply_scope_cannot_leak_other_peer_or_room(self):
        original, _ = self.send()
        self.server.add_user('third', 'synthetic', 'Third', '')
        self.tokens['third'] = self.server.create_session('third')[0]
        self.server.send_friend_request('alice', 'third')
        self.server.accept_friend_request('alice', 'third')
        for action in ('send_message', 'get_messages'):
            fields = dict(text='leak', reply_to_id=original['id']) if action == 'send_message' else dict(paged=True, around_id=original['id'])
            result = self.request('alice', action, to_user='third', **fields)
            self.assertEqual(result['status'], 'error')
        original, scope = self.send(True)
        room = self.request('alice', 'create_channel_room', **scope, kind='text', name='separate')['room_id']
        self.assertEqual(self.request('alice', 'send_channel_message', **scope, room_id=room, text='leak', reply_to_id=original['id'])['status'], 'error')
        self.assertEqual(self.request('alice', 'get_channel_messages', **scope, room_id=room, paged=True, around_id=original['id'])['status'], 'error')
        self.request('bob', 'leave_channel', **scope)
        self.assertEqual(self.request('bob', 'get_channel_messages', **scope, paged=True, around_id=original['id'])['status'], 'error')

    def test_old_original_navigation_and_idempotency(self):
        original, fields = self.send()
        for number in range(165):
            self.request('alice', 'send_message', **fields, text=str(number))
        request = dict(fields, text='answer', reply_to_id=original['id'], client_message_id=uuid.uuid4().hex)
        first = self.request('alice', 'send_message', **request)
        self.assertEqual(first, self.request('alice', 'send_message', **request))
        self.assertEqual(self.request('alice', 'send_message', **dict(request, reply_to_id=original['id']+1))['status'], 'error')
        newest = self.request('alice', 'get_messages', **fields, paged=True)
        self.assertNotIn(original['id'], [r['id'] for r in newest['messages']])
        self.assertEqual(newest['messages'][-1]['reply']['id'], original['id'])
        around = self.request('alice', 'get_messages', **fields, paged=True, around_id=original['id'])
        self.assertEqual(around['messages'][0]['id'], original['id'])
        self.assertTrue(around['has_newer'])
        self.assertFalse(around['has_older'])
        self.assertLessEqual(len(around['messages']), 80)
        self.assertEqual(self.request('alice', 'get_messages', **fields, paged=True, around_id=original['id'], before_id=original['id'])['status'], 'error')

    def test_attachment_quote_and_bounded_plain_text(self):
        aid = self.upload(to_user='bob')
        self.request('alice', 'send_message', to_user='bob', text='', attachment_id=aid)
        original = self.request('alice', 'get_messages', to_user='bob', paged=True)['messages'][-1]
        self.request('bob', 'send_message', to_user='alice', text='file reply', reply_to_id=original['id'])
        quote = self.request('bob', 'get_messages', to_user='alice', paged=True)['messages'][-1]['reply']
        self.assertTrue(quote['text'].startswith('📎 '))
        self.request('alice', 'edit_message', to_user='bob', message_id=original['id'], expected_revision=0, text='<b>'+('x'*2000))
        quote = self.request('bob', 'get_messages', to_user='alice', paged=True)['messages'][-1]['reply']
        self.assertEqual(len(quote['text']), 200)
        self.assertTrue(quote['text'].startswith('<b>'))
        for bad in (True, 0, -1, '1', 2**63):
            self.assertEqual(self.request('bob', 'send_message', to_user='alice', text='bad', reply_to_id=bad)['status'], 'error')
