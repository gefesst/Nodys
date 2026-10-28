"""Bounded per-speaker jitter queues with reordering and short loss concealment."""
import threading
import time
import numpy as np


class PcmMixer:
    def __init__(self, frame_samples=320, max_speakers=32, max_frames=8, prebuffer=2):
        self.frame_samples=frame_samples
        self.max_speakers=max_speakers
        self.max_frames=max_frames
        self.prebuffer=prebuffer
        self.streams={}
        self.lock=threading.Lock()

    def push(self, speaker, pcm, sequence=None, stream_id=None):
        if not speaker or len(pcm)!=self.frame_samples*2:
            return False
        now=time.monotonic()
        with self.lock:
            for name in list(self.streams):
                if now-self.streams[name]['seen']>5:
                    del self.streams[name]
            state=self.streams.get(speaker)
            if state is None:
                if len(self.streams)>=self.max_speakers:return False
                state=dict(frames={},seen=now,stream=stream_id,retired=[],expected=None,
                           last_played=-1,auto=0,delay=0,last=None,lost=0,started=False)
                self.streams[speaker]=state
            if state['stream']!=stream_id:
                if stream_id in state['retired']:return False
                retired=(state['retired']+[state['stream']])[-8:]
                state.update(frames={},stream=stream_id,retired=retired,expected=None,
                             last_played=-1,last=None,lost=0,started=False)
            state['conceal'] = sequence is not None
            if sequence is None:
                sequence=state['auto'];state['auto']+=1
                delay=0
            else:
                if type(sequence) is not int or sequence<0:return False
                delay=self.prebuffer
            if sequence<=state['last_played'] or sequence in state['frames']:
                return False
            if state['expected'] is None:
                state['expected']=sequence
                state['delay']=delay
            elif not state['started']:
                state['expected']=min(state['expected'],sequence)
            elif sequence<state['expected']:
                return False
            state['seen']=now
            state['frames'][sequence]=bytes(pcm)
            # Drop oldest backlog rather than allowing latency to grow unbounded.
            floor=max(state['expected'],sequence-self.max_frames+1)
            state['frames']={key:value for key,value in state['frames'].items() if key>=floor}
            state['expected']=floor
            return True

    def mix(self):
        combined=np.zeros(self.frame_samples,dtype=np.int32)
        with self.lock:
            for state in self.streams.values():
                if state['expected'] is None:continue
                if state['delay']>0:
                    state['delay']-=1
                    continue
                state['started']=True
                sequence=state['expected']
                state['expected']+=1
                frame=state['frames'].pop(sequence,None)
                if frame is not None:
                    sample=np.frombuffer(frame,dtype='<i2').astype(np.int32)
                    state.update(last=sample,last_played=sequence,lost=0)
                    combined+=sample
                else:
                    state['lost']+=1
                    if state['conceal'] and state['last'] is not None and state['lost']<=2:
                        combined+=(state['last']*(0.5**state['lost'])).astype(np.int32)
                    if state['lost']>=self.max_frames and not state['frames']:
                        state.update(expected=None,started=False,last=None)
        return np.clip(combined,-32768,32767).astype(np.int16)

    def clear(self):
        with self.lock:self.streams.clear()

    def queued_frames(self):
        with self.lock:return sum(len(state['frames']) for state in self.streams.values())
