"""Sound transitions without speakers or timing-dependent audio assertions."""
import sys
import unittest
import wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
from audio.ui_sounds import UISounds

class Effect:
    def __init__(self,parent):self.plays=0;self.running=False
    def setSource(self,url):self.url=url
    def setVolume(self,value):self.volume=value
    def setLoopCount(self,value):self.loops=value
    def play(self):self.plays+=1;self.running=True
    def stop(self):self.running=False

class SoundTests(unittest.TestCase):
    def test_call_lifecycle_deduplicates_and_stops_ringing(self):
        s=UISounds(effect_factory=Effect)
        state=dict(call_id='one',status='ringing',incoming=False)
        for _ in range(5):s.call_state(state)
        self.assertEqual(s.effects['outgoing'].plays,1)
        s.call_state(dict(state,status='active'))
        self.assertFalse(s.effects['outgoing'].running)
        self.assertEqual(s.effects['call_start'].plays,1)
        s.call_state(dict(state,status='active'))
        s.call_state(None);s.call_state(None)
        self.assertEqual(s.effects['call_end'].plays,1)

    def test_declined_incoming_and_shutdown(self):
        s=UISounds(effect_factory=Effect)
        s.call_state(dict(call_id='two',status='ringing',incoming=True))
        self.assertTrue(s.effects['incoming'].running)
        s.stop_ringing()
        self.assertFalse(s.effects['incoming'].running)
        s.call_state(None)
        self.assertEqual(s.effects['call_start'].plays,0)
        self.assertEqual(s.effects['call_end'].plays,0)
        s.shutdown();s.play('mic_off')
        self.assertEqual(s.effects['mic_off'].plays,0)
        self.assertFalse(any(e.running for e in s.effects.values()))
        s.reset();s.play("mic_on")
        self.assertEqual(s.effects["mic_on"].plays,1)

    def test_all_assets_are_valid_bounded_pcm(self):
        s=UISounds(effect_factory=Effect)
        self.assertEqual(set(s.effects),{'incoming','outgoing','call_start','call_end','voice_join','voice_leave','mic_on','mic_off','sound_on','sound_off'})
        for name,effect in s.effects.items():
            with wave.open(effect.url.toLocalFile()) as source:
                self.assertEqual(source.getsampwidth(),2)
                self.assertEqual(source.getnchannels(),1)
                self.assertGreater(source.getnframes(),0)
                self.assertLess(source.getnframes()/source.getframerate(),4)
            self.assertEqual(effect.loops,-2 if name in ('incoming','outgoing') else 1)
