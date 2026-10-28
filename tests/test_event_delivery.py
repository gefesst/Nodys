import unittest
import test_voice_authorization as fixtures

class EventDeliveryTests(fixtures.VoiceFixture, unittest.TestCase):

    def poll(self, login='bob', after=0):
        return self.server.handle_request({'action':'poll_events','token':self.tokens[login], 'after_event_id':after})

    def test_dropped_response_replays_and_cursor_acknowledges(self):
        self.server.push_event('bob',{'type':'test'})
        first = self.poll()
        self.assertEqual(first['events'], self.poll()['events'])
        self.assertEqual(self.poll(after=first['events'][-1]['event_id'])['events'],[])
        self.assertEqual(self.poll('alice')['events'],[])

    def test_independent_readers_do_not_consume_each_others_events(self):
        self.server.push_event('bob',{'type':'test'})
        self.assertEqual(self.poll()['events'],self.poll()['events'])

    def test_snapshot_heals_missed_call_end(self):
        self.server.send_friend_request('alice','bob');self.server.accept_friend_request('alice','bob')
        self.server.start_call('alice','bob')
        state = self.poll()['call_state']
        self.assertEqual((state['peer'],state['status'],state['incoming']),('alice','ringing',True))
        self.assertTrue(state['call_id'])
        self.server.accept_call('bob','alice')
        self.assertEqual(self.poll()['call_state']['status'],'active')
        self.server.end_call('alice','bob')
        self.assertIsNone(self.poll()['call_state'])

    def test_events_survive_service_reinitialization(self):
        self.server.push_event('bob',{'type':'test'})
        first=self.poll()['events']
        self.server.init_db()
        self.assertEqual(self.poll()['events'],first)
