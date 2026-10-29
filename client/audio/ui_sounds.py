"""One UI-thread sound owner; snapshots never restart an existing ringtone."""
from pathlib import Path
from PySide6.QtCore import QObject, QUrl

class UISounds(QObject):
    def __init__(self, parent=None, effect_factory=None):
        super().__init__(parent)
        if effect_factory is None:
            from PySide6.QtMultimedia import QSoundEffect
            effect_factory=QSoundEffect
        self.effects={}
        self.call_key=None
        self.active_call=None
        self.closed=False
        for path in sorted((Path(__file__).resolve().parents[1]/'assets/sounds').glob('*.wav')):
            effect=effect_factory(self)
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setVolume(.35)
            effect.setLoopCount(-2 if path.stem in ('incoming','outgoing') else 1)
            self.effects[path.stem]=effect

    def play(self, name):
        if not self.closed and name in self.effects:
            self.effects[name].stop()
            self.effects[name].play()

    def stop_ringing(self):
        for name in ('incoming','outgoing'):
            if name in self.effects:self.effects[name].stop()

    def call_state(self, state):
        key=None if not state else (state.get('call_id'),state.get('status'),bool(state.get('incoming')))
        if key==self.call_key:return
        self.call_key=key
        self.stop_ringing()
        identity=state.get('call_id') if state else None
        active=bool(state and state.get('status')=='active')
        if self.active_call and (not active or self.active_call!=identity):
            self.play('call_end')
            self.active_call=None
        if active:
            if self.active_call!=identity:self.play('call_start')
            self.active_call=identity
        elif state and state.get('status')=='ringing':
            self.play('incoming' if state.get('incoming') else 'outgoing')

    def reset(self):
        self.shutdown()
        self.closed=False

    def shutdown(self):
        self.closed=True
        self.call_key=None
        self.active_call=None
        for effect in self.effects.values():effect.stop()
