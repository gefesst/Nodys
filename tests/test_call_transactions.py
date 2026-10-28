from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
import test_voice_authorization as fixtures
from storage import events


class CallTransactionTests(fixtures.VoiceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server.send_friend_request('alice','bob')
        self.server.accept_friend_request('alice','bob')

    def state(self):
        with self.server.database_connection(self.server.DB_FILE) as connection:
            return connection.execute('SELECT status FROM active_call_pairs').fetchall()

    def test_event_failure_rolls_back_call_start(self):
        with patch.object(events,'append',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):self.server.start_call('alice','bob')
        self.assertEqual(self.state(),[])
        self.assertEqual(self.server.pop_events('bob'),[])
        self.assertTrue(self.server.start_call('alice','bob')[0])

    def test_second_event_failure_rolls_back_accept_and_first_event(self):
        self.server.start_call('alice','bob')
        with self.server.database_connection(self.server.DB_FILE) as connection:
            count=connection.execute('SELECT COUNT(*) FROM user_events').fetchone()[0]
        append=events.append
        calls=[]
        def fail_second(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('disk failure')
            append(*args)
        with patch.object(events,'append',side_effect=fail_second):
            with self.assertRaises(RuntimeError):self.server.accept_call('bob','alice')
        self.assertEqual(self.state(),[('ringing',)])
        with self.server.database_connection(self.server.DB_FILE) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM user_events').fetchone()[0],count)

    def test_caller_cannot_accept_own_outgoing_call(self):
        self.server.start_call('alice','bob')
        self.assertFalse(self.server.accept_call('alice','bob'))
        self.assertEqual(self.state(),[('ringing',)])
        self.assertTrue(self.server.accept_call('bob','alice'))
        self.assertFalse(self.server.decline_call('bob','alice'))

    def test_concurrent_calls_share_one_busy_state(self):
        self.server.add_user('carol','synthetic','Carol','')
        self.server.create_session('carol')
        self.server.send_friend_request('carol','bob');self.server.accept_friend_request('carol','bob')
        with ThreadPoolExecutor(max_workers=2) as workers:
            results=list(workers.map(lambda who:self.server.start_call(who,'bob'),('alice','carol')))
        self.assertEqual(sum(result[0] for result in results),1)
        self.assertEqual(len(self.state()),1)

    def test_restart_preserves_call_and_individual_heartbeats_expire(self):
        self.server.start_call('alice','bob');self.server.accept_call('bob','alice')
        self.server.init_db()
        self.assertEqual(self.state(),[('active',)])
        with self.server.database_connection(self.server.DB_FILE) as connection:
            connection.execute("UPDATE active_call_pairs SET seen_b='2000-01-01T00:00:00+00:00'")
        self.server.mark_call_activity('alice')
        self.server.prune_stale_calls()
        self.assertEqual(self.state(),[])
        self.assertTrue(any(event['type']=='call_ended' for event in self.server.pop_events('alice')))
