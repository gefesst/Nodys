import sys
from pathlib import Path
import unittest
import test_voice_authorization as fixtures
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
from application.request_scope import RequestScope

class RequestScopeTests(unittest.TestCase):
    def test_old_screen_and_session_cannot_apply(self):
        scope = RequestScope()
        ticket = scope.capture('details',('token',1))
        self.assertFalse(scope.accepts(ticket,('token',2)))
        self.assertFalse(scope.accepts(ticket,('other',1)))
        scope.invalidate()
        self.assertFalse(scope.accepts(ticket,('token',1)))

    def test_latest_response_wins(self):
        scope = RequestScope()
        old = scope.capture('details',1)
        new = scope.capture('details',1)
        self.assertFalse(scope.accepts(old,1))
        self.assertTrue(scope.accepts(new,1))

class PresenceOrderTests(unittest.TestCase):
    setUp = fixtures.VoiceAuthorizationTests.setUp
    packet = fixtures.VoiceAuthorizationTests.packet
    def test_late_join_does_not_undo_leave(self):
        cid = self.channel['id']; token = self.tokens['bob']
        self.server.set_channel_voice_presence('bob',cid,token=token,sequence=10)
        self.server.leave_channel_voice('bob',cid,token=token,sequence=12)
        self.server.set_channel_voice_presence('bob',cid,token=token,sequence=11)
        self.assertEqual(self.server.get_channel_voice_participants(cid,'alice')[2],[])
        self.server.set_channel_voice_presence('bob',cid,token=token,sequence=13)
        self.assertEqual(len(self.server.get_channel_voice_participants(cid,'alice')[2]),1)

    def test_late_leave_does_not_undo_new_join(self):
        cid = self.channel['id']; token = self.tokens['bob']
        self.server.set_channel_voice_presence('bob',cid,token=token,sequence=20)
        self.server.leave_channel_voice('bob',cid,token=token,sequence=19)
        self.assertEqual(len(self.server.get_channel_voice_participants(cid,'alice')[2]),1)

class SequenceClockTests(unittest.TestCase):
    def test_restart_with_clock_rollback(self):
        from unittest.mock import patch
        from application.sequence import SequenceClock
        saved = {}
        with patch('application.sequence.load_config',side_effect=lambda:dict(saved)), patch('application.sequence.save_config',side_effect=saved.update), patch('application.sequence.time.time_ns',return_value=100):
            first = SequenceClock().next()
            second = SequenceClock().next()
        self.assertGreater(second,first)
