import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'client'))
from application.call_controller import CallController
from application.polling import PollingController

class Signal:
    def connect(self, callback): self.callback = callback
    def emit(self, value): self.callback(value)

class Request:
    def __init__(self, host, port, data):
        self.data, self.finished, self.running, self.aborted = data, Signal(), False, False
    def start(self): self.running = True
    def abort(self): self.aborted = True; self.running = False
    def isRunning(self): return self.running
    def complete(self, result): self.running = False; self.finished.emit(result)

class CallControllerTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(login='alice', session_token='first')
        self.controller = CallController(lambda:self.context, request_factory=Request)
        self.states = []
        self.controller.state_changed.connect(self.states.append)
        self.state = dict(call_id='one', peer='bob', status='active', incoming=False)
    def response(self, state=None): return dict(status='ok', call_state=self.state if state is None else state, events=[{'event_id':5}])
    def test_snapshots_deduplicate_and_new_call_is_distinct(self):
        self.controller.receive(self.response());self.controller.receive(self.response())
        self.assertEqual(len(self.states),1)
        self.controller.receive(self.response(dict(self.state,call_id='two')))
        self.assertEqual(len(self.states),2)
        self.assertEqual(self.controller.cursor,5)
    def test_previous_session_response_cannot_start_call(self):
        self.controller.poll();old=self.controller.requests['poll']
        self.context.session_token='second'
        self.controller.poll()
        old.complete(self.response())
        self.assertEqual(self.states,[])
        self.assertTrue(old.aborted)
    def test_reset_fences_late_responses_and_aborts_all_requests(self):
        self.controller.poll();old=self.controller.requests['poll']
        self.controller.reset();old.complete(self.response())
        self.assertEqual(self.states,[])
        self.assertTrue(old.aborted)
    def test_action_invalidates_pre_mutation_poll(self):
        self.controller.poll();old=self.controller.requests['poll']
        self.controller.start_call('bob');action=self.controller.requests['action']
        action.complete({'status':'ok'})
        old.complete(self.response())
        self.assertEqual(self.states,[])
        self.assertTrue(old.aborted)
        self.controller.requests['poll'].complete(self.response())
        self.assertEqual(len(self.states),1)
    def test_reply_and_end_capture_call_identity(self):
        self.controller.receive(self.response(dict(self.state,status='ringing',incoming=True)))
        self.assertTrue(self.controller.respond(True))
        self.assertEqual(self.controller.requests['action'].data['call_id'],'one')
        self.assertFalse(self.controller.start_call('carol'))
        self.controller.reset();self.controller.end_call('old','bob')
        self.assertEqual(self.controller.requests['action'].data['call_id'],'old')
    def test_malformed_state_does_not_start_audio(self):
        self.controller.receive(dict(status='ok',call_state={'status':'active'},events=[]))
        self.assertEqual(self.states,[])

    def test_terminal_card_is_emitted_once_and_matches_call_identity(self):
        results=[]; self.controller.result_ready.connect(results.append)
        self.controller.receive(self.response(dict(self.state,status='ringing')))
        reply=dict(status='ok',call_state=None,events=[dict(event_id=6,type='call_declined',call_id='one',with_user='bob')])
        self.controller.receive(reply);self.controller.receive(reply)
        self.assertEqual(results,[dict(peer='bob',title='Вызов отклонён')])

    def test_old_terminal_event_cannot_label_new_call(self):
        results=[]; self.controller.result_ready.connect(results.append)
        self.controller.receive(self.response(dict(self.state,call_id='two')))
        self.controller.receive(dict(status='ok',call_state=None,events=[dict(event_id=6,type='call_declined',call_id='one',with_user='bob')]))
        self.assertEqual(results,[dict(peer='bob',title='Звонок завершён')])

    def test_busy_result_uses_server_response_without_starting_audio(self):
        results=[]; self.controller.result_ready.connect(results.append)
        self.controller.start_call('bob')
        self.controller.requests['action'].complete(dict(status='error',message='Пользователь занят'))
        self.assertEqual(results,[dict(peer='bob',title='Пользователь занят')])
        self.assertEqual(self.states,[])

    def test_cancel_pending_waits_for_identity_and_never_opens_call(self):
        pending=[];self.controller.pending_changed.connect(pending.append)
        self.assertTrue(self.controller.start_call('bob'))
        self.controller.cancel_start('bob')
        self.assertFalse(self.controller.start_call('carol'))
        self.controller.receive(self.response())
        self.assertEqual(self.states,[])
        self.controller.requests['action'].complete(dict(status='ok'))
        self.controller.requests['poll'].complete(self.response())
        self.assertEqual(self.states,[])
        self.assertEqual(self.controller.requests['action'].data['action'],'end_call')
        self.assertEqual(self.controller.requests['action'].data['call_id'],'one')
        self.controller.requests['action'].complete(dict(status='ok'))
        self.controller.requests['poll'].complete(dict(status='ok',call_state=None,events=[]))
        self.assertIsNone(self.controller.cancelled_start)
        self.assertEqual(pending[-3:],['bob',None,None])

    def test_cancel_rejected_request_suppresses_result(self):
        results=[];self.controller.result_ready.connect(results.append)
        self.controller.start_call('bob');self.controller.cancel_start('bob')
        self.controller.requests['action'].complete(dict(status='error',message='Пользователь занят'))
        self.assertEqual(results,[])
        self.assertIsNone(self.controller.cancelled_start)
        self.assertTrue(self.controller.start_call('carol'))

    def test_cancel_does_not_end_unrelated_incoming_call(self):
        self.controller.start_call('bob');self.controller.cancel_start('bob')
        self.controller.requests['action'].complete(dict(status='ok'))
        self.controller.requests['poll'].complete(self.response(dict(self.state,peer='carol',incoming=True)))
        self.assertNotIn('action',self.controller.requests)
        self.assertEqual(self.states[-1]['peer'],'carol')

    def test_reset_clears_pending_cancel_and_fences_callback(self):
        self.controller.start_call('bob');old=self.controller.requests['action']
        self.controller.cancel_start('bob');self.controller.reset()
        old.complete(dict(status='ok'))
        self.assertIsNone(self.controller.pending_peer)
        self.assertIsNone(self.controller.cancelled_start)
        self.assertEqual(self.controller.requests,{})


class PollingTests(unittest.TestCase):
    def test_navigation_and_authentication_stop_background_pages(self):
        from unittest.mock import Mock
        timer=Mock();timer.interval.return_value=0;timer.isActive.return_value=False
        pages=[(Mock(),Mock()) for _ in range(3)]
        policy=PollingController([(timer,1000,2600)],pages)
        policy.apply(True,2,True)
        pages[2][0].assert_called_once();pages[0][1].assert_called_once()
        policy.apply(False,2,True)
        timer.setInterval.assert_called_with(2600)
        pages[2][1].assert_called_once()
        policy.apply(True,0,False)
        timer.stop.assert_called_once()
