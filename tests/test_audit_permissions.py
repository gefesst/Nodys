import json
import unittest
from concurrent.futures import ThreadPoolExecutor
import test_voice_authorization as fixtures


class AuditPermissions(fixtures.VoiceFixture, unittest.TestCase):
    def request(self, login, action, **data):
        return self.server.handle_request(dict(action=action,token=self.tokens[login],**data))

    def test_member_cannot_impersonate_owner_for_management(self):
        cid=self.channel['id']
        for action,fields in (
            ('update_channel_settings',dict(name='stolen',avatar='')),
            ('delete_channel',{}),('regenerate_channel_code',{}),
            ('set_channel_member_role',dict(target_login='bob',role='admin')),
            ('remove_channel_member',dict(target_login='alice'))):
            result=self.server.handle_request(
                dict(action=action,token=self.tokens['bob'],login='alice',channel_id=cid,**fields))
            self.assertEqual(result['status'],'error',action)

    def test_outsider_cannot_read_write_invite_or_join_voice(self):
        self.server.add_user('outsider','synthetic','Outside','')
        self.tokens['outsider']=self.server.create_session('outsider')[0]
        for action,fields in (('get_channel_details',{}),('get_channel_messages',{}),
                ('send_channel_message',{'text':'intrusion'}),('get_channel_voice_participants',{}),
                ('send_channel_invite',{'target_login':'alice'}),('set_channel_voice_presence',{'joined':True})):
            self.assertEqual(self.request('outsider',action,channel_id=self.channel['id'],**fields)['status'],'error',action)

    def test_password_change_requires_old_password_and_revokes_other_device(self):
        second=self.server.create_session('alice')[0]
        denied=self.request('alice','update_profile',nickname='Alice',avatar='',password='new password')
        self.assertEqual(denied['status'],'error')
        result=self.request('alice','update_profile',nickname='Alice',avatar='',password=' new password ',current_password='synthetic')
        self.assertEqual(result['status'],'ok')
        self.assertIsNone(self.server.get_session_by_token(second))
        self.assertIsNotNone(self.server.get_session_by_token(self.tokens['alice']))
        self.assertTrue(self.server.authenticate('alice',' new password '))

    def test_messages_only_between_friends_and_sender_comes_from_session(self):
        self.assertEqual(self.request('alice','send_message',to_user='bob',text='hello')['status'],'error')
        self.server.send_friend_request('alice','bob');self.server.accept_friend_request('alice','bob')
        self.assertEqual(self.request('alice','send_message',from_user='bob',to_user='bob',text='hello')['status'],'ok')
        self.assertEqual(self.server.get_messages('alice','bob')[0]['from_user'],'alice')

    def test_duplicate_message_and_changed_payload(self):
        payload=dict(channel_id=self.channel['id'],text='one',request_id='retry-message')
        with ThreadPoolExecutor(max_workers=2) as workers:
            results=list(workers.map(lambda _:self.request('alice','send_channel_message',**payload),range(2)))
        self.assertTrue(all(result['status']=='ok' for result in results))
        self.assertEqual(len(self.server.get_channel_messages(self.channel['id'])),1)
        self.assertEqual(self.request('alice','send_channel_message',**dict(payload,text='changed'))['code'],'request_conflict')
        self.server.delete_session(self.tokens['alice'])
        self.assertEqual(self.request('alice','send_channel_message',**payload)['code'],'session_invalid')

    def test_duplicate_channel_returns_same_id(self):
        first=self.request('alice','create_channel',name='one',request_id='channel-once')
        second=self.request('alice','create_channel',name='one',request_id='channel-once')
        self.assertEqual(first,second)
        self.assertEqual(len(self.server.list_user_channels('alice')),2)

    def test_admin_cannot_promote_self_or_remove_owner(self):
        cid=self.channel['id'];self.server.set_channel_member_role('alice',cid,'bob','admin')
        for target,role in (('bob','admin'),('alice','member')):
            self.assertEqual(self.request('bob','set_channel_member_role',channel_id=cid,target_login=target,role=role)['status'],'error')
        self.assertEqual(self.request('bob','remove_channel_member',channel_id=cid,target_login='alice')['status'],'error')

    def test_invitation_is_bound_to_recipient(self):
        self.server.add_user('third','synthetic','Third','')
        self.tokens['third']=self.server.create_session('third')[0]
        self.server.send_channel_invite('alice',self.channel['id'],'third')
        invite=self.server.get_incoming_channel_invites('third')[0]['invite_id']
        self.assertEqual(self.request('bob','respond_channel_invite',invite_id=invite,decision='accept')['status'],'error')
        result=self.request('third','respond_channel_invite',invite_id=invite,decision='accept',request_id='accept-once')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(self.request('third','respond_channel_invite',invite_id=invite,decision='accept',request_id='accept-once'),result)

    def test_receipt_write_failure_rolls_back_channel(self):
        from unittest.mock import patch
        from services import mutations
        original=mutations.json.dumps
        def fail_result(value,*args,**kwargs):
            if isinstance(value,dict) and value.get('status')=='ok':
                raise RuntimeError('synthetic receipt failure')
            return original(value,*args,**kwargs)
        with patch.object(mutations.json,'dumps',side_effect=fail_result):
            with self.assertRaises(RuntimeError):
                self.request('alice','create_channel',name='rollback',request_id='failure')
        self.assertEqual(len(self.server.list_user_channels('alice')),1)

    def test_delayed_close_cannot_end_new_call(self):
        self.server.send_friend_request('alice','bob');self.server.accept_friend_request('alice','bob')
        self.server.start_call('alice','bob')
        with self.server.database_connection(self.server.DB_FILE) as connection:
            old=connection.execute('SELECT created_at FROM active_call_pairs').fetchone()[0]
        self.server.end_call('alice','bob')
        self.server.start_call('alice','bob')
        self.request('alice','release_call_state',call_id=old)
        with self.server.database_connection(self.server.DB_FILE) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM active_call_pairs').fetchone()[0],1)
            current=connection.execute('SELECT created_at FROM active_call_pairs').fetchone()[0]
        self.request('alice','release_call_state',call_id=current)
        with self.server.database_connection(self.server.DB_FILE) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM active_call_pairs').fetchone()[0],0)

    def test_channel_deletion_retries_history_cleanup(self):
        from unittest.mock import patch
        cid=self.channel['id']
        self.request('alice','send_channel_message',channel_id=cid,text='retired')
        with patch.object(self.server.channel_cleanup,'drain',return_value=False):
            response=self.request('alice','delete_channel',channel_id=cid,request_id='delete-once')
        self.assertEqual(response['status'],'ok')
        self.assertIsNone(self.server.get_channel_by_id(cid))
        self.assertEqual(len(self.server.get_channel_messages(cid)),1)
        response=self.request('alice','delete_channel',channel_id=cid,request_id='delete-once')
        self.assertEqual(response['status'],'ok')
        self.assertEqual(self.server.get_channel_messages(cid),[])
        with self.server.database_connection(self.server.DB_FILE) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM channel_cleanup').fetchone()[0],0)
