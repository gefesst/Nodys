import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
from audio.mixer import PcmMixer

class MixerTests(unittest.TestCase):
    def frame(self, value): return np.full(320,value,dtype='<i2').tobytes()
    def test_simultaneous_speakers_are_added(self):
        mixer=PcmMixer()
        mixer.push('alice',self.frame(1000));mixer.push('bob',self.frame(2000))
        self.assertTrue(np.all(mixer.mix()==3000))
        self.assertTrue(np.all(mixer.mix()==0))
    def test_saturation_prevents_integer_wraparound(self):
        mixer=PcmMixer()
        mixer.push('alice',self.frame(30000));mixer.push('bob',self.frame(30000))
        self.assertTrue(np.all(mixer.mix()==32767))
    def test_queues_and_speakers_are_bounded(self):
        mixer=PcmMixer(max_speakers=2,max_frames=3)
        for _ in range(50): mixer.push('alice',self.frame(1))
        mixer.push('bob',self.frame(2))
        self.assertFalse(mixer.push('third',self.frame(3)))
        self.assertLessEqual(mixer.queued_frames(),6)
        self.assertFalse(mixer.push('alice',b'bad'))

    def test_remote_voice_fails_before_sending_credentials(self):
        from voice_client import VoiceClient
        client=VoiceClient('alice',token='synthetic',host='203.0.113.1')
        with self.assertRaises(ValueError):client.start(peer_login='bob')
        self.assertFalse(client.running)
        self.assertIsNone(client.sock)
