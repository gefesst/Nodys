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

    def test_reordering_and_short_loss_concealment(self):
        mixer=PcmMixer()
        mixer.push('alice',self.frame(2000),sequence=1,stream_id=b'a')
        mixer.push('alice',self.frame(1000),sequence=0,stream_id=b'a')
        self.assertFalse(mixer.push('alice',self.frame(9000),sequence=1,stream_id=b'a'))
        for _ in range(2): self.assertTrue(np.all(mixer.mix()==0))
        for value in (1000,2000,1000,500,0):
            self.assertTrue(np.all(mixer.mix()==value))
        self.assertFalse(mixer.push('alice',self.frame(1000),sequence=0,stream_id=b'a'))

    def test_key_rotation_rejects_old_stream_and_resets_sequence(self):
        mixer=PcmMixer(prebuffer=0)
        mixer.push('alice',self.frame(1),sequence=100,stream_id=b'a')
        mixer.mix()
        self.assertTrue(mixer.push('alice',self.frame(2),sequence=0,stream_id=b'b'))
        self.assertFalse(mixer.push('alice',self.frame(9),sequence=101,stream_id=b'a'))
        self.assertTrue(np.all(mixer.mix()==2))

    def test_long_gap_and_backlog_are_bounded(self):
        mixer=PcmMixer(prebuffer=0,max_frames=3)
        for sequence in range(50):
            mixer.push('alice',self.frame(sequence),sequence=sequence,stream_id=b'a')
        self.assertEqual(mixer.queued_frames(),3)
        self.assertTrue(np.all(mixer.mix()==47))
        for _ in range(8): mixer.mix()
        self.assertTrue(mixer.push('alice',self.frame(100),sequence=100,stream_id=b'a'))
        self.assertTrue(np.all(mixer.mix()==100))
