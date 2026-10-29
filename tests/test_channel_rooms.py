"""Room isolation across control requests, persisted history, presence and UDP."""
import unittest
from test_voice_authorization import VoiceFixture


class ChannelRoomsTests(VoiceFixture,unittest.TestCase):
    def request(self,actor,action,**data):
        return self.server.handle_request(dict(action=action,token=self.tokens[actor],channel_id=self.channel['id'],**data))

    def create(self,kind,name='Новый'):
        response=self.request('alice','create_channel_room',kind=kind,name=name)
        self.assertEqual(response['status'],'ok',response)
        return response['room_id']

    def test_defaults_and_management_permissions(self):
        owner=self.request('alice','get_channel_rooms')
        self.assertEqual([(r['id'],r['kind']) for r in owner['rooms']],[(0,'text'),(1,'voice')])
        self.assertTrue(owner['can_manage'])
        self.assertFalse(self.request('bob','get_channel_rooms')['can_manage'])
        self.assertEqual(self.request('bob','create_channel_room',kind='text',name='No')['status'],'error')
        self.assertEqual(self.request('bob','rename_channel_room',room_id=0,name='No')['status'],'error')
        rid=self.create('text')
        self.assertEqual(self.request('alice','rename_channel_room',room_id=rid,name='Объявления')['status'],'ok')
        self.assertEqual(self.request('alice','get_channel_rooms')['rooms'][-1]['name'],'Объявления')

    def test_histories_cursors_and_retry_are_scoped_to_room(self):
        rid=self.create('text')
        a=self.request('alice','send_channel_message',room_id=0,text='old history',client_message_id='old')
        b=self.request('alice','send_channel_message',room_id=rid,text='new history',client_message_id='new')
        self.assertEqual((a['status'],b['status']),('ok','ok'))
        old=self.request('bob','get_channel_messages',paged=True,room_id=0)
        new=self.request('bob','get_channel_messages',paged=True,room_id=rid)
        self.assertEqual([m['text'] for m in old['messages']],['old history'])
        self.assertEqual([m['text'] for m in new['messages']],['new history'])
        self.assertEqual(self.request('bob','get_channel_messages',paged=True,room_id=rid,before_id=old['messages'][0]['id'])['status'],'error')
        self.assertEqual(self.request('alice','send_channel_message',room_id=rid,text='old history',client_message_id='old')['status'],'error')
        self.assertEqual(self.request('bob','get_channel_messages',room_id=1)['status'],'error')
        self.assertEqual(self.request('bob','send_channel_message',room_id=999,text='No')['status'],'error')

    def test_create_retries_do_not_duplicate_rooms(self):
        for _ in range(2):
            result=self.request('alice','create_channel_room',kind='voice',name='Команда',request_id='room-retry')
            self.assertEqual(result['status'],'ok',result)
        self.assertEqual(len(self.request('alice','get_channel_rooms')['rooms']),3)

    def test_voice_rooms_do_not_mix_audio_and_text_room_is_rejected(self):
        rid=self.create('voice')
        room=f"channel:{self.channel['id']}:{rid}"
        self.connect('alice',room=room)
        self.assertEqual(self.audio('alice'),0)
        self.assertEqual(self.audio('bob'),0)
        self.connect('bob',room=room)
        self.assertEqual(self.audio('alice'),1)
        text=self.create('text')
        denied=self.server.handle_request(dict(action='voice_ticket',token=self.tokens['bob'],room=f"channel:{self.channel['id']}:{text}"))
        self.assertEqual(denied['status'],'error')
        self.server.remove_channel_member('alice',self.channel['id'],'bob')
        self.assertEqual(self.audio('alice'),0)

    def test_presence_belongs_to_selected_voice_room(self):
        rid=self.create('voice')
        for actor,room in [('alice',1),('bob',rid)]:
            response=self.request(actor,'set_channel_voice_presence',room_id=room,joined=True,speaking=False)
            self.assertEqual(response['status'],'ok',response)
        self.assertEqual([p['login'] for p in self.request('alice','get_channel_voice_participants',room_id=1)['participants']],['alice'])
        self.assertEqual([p['login'] for p in self.request('alice','get_channel_voice_participants',room_id=rid)['participants']],['bob'])
        self.assertEqual(self.request('alice','set_channel_voice_presence',room_id=0,joined=True)['status'],'error')

    def test_names_and_kinds_are_validated(self):
        for name in ('',' '*3,'x'*65,'bad\nname'):
            self.assertEqual(self.request('alice','create_channel_room',kind='text',name=name)['status'],'error')
        self.assertEqual(self.request('alice','create_channel_room',kind='other',name='Name')['status'],'error')
