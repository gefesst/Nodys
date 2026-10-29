"""Isolated Qt sound player. Never shares the voice client's Python GIL."""
import json
import queue
import sys
import threading
from pathlib import Path


def main():
    from PySide6.QtCore import QCoreApplication, QTimer, QUrl
    from PySide6.QtMultimedia import QSoundEffect
    app=QCoreApplication([])
    commands=queue.Queue()
    effects={}
    for path in (Path(__file__).resolve().parents[1]/'assets/sounds').glob('*.wav'):
        effect=QSoundEffect(app)
        effect.setSource(QUrl.fromLocalFile(str(path)))
        effect.setVolume(.35)
        effect.setLoopCount(-2 if path.stem in ('incoming','outgoing') else 1)
        effects[path.stem]=effect
    def read():
        try:
            for line in sys.stdin:
                try:commands.put(json.loads(line))
                except ValueError:continue
        finally:commands.put(['quit',''])
    threading.Thread(target=read,daemon=True).start()
    def drain():
        while not commands.empty():
            action,name=commands.get_nowait()
            if action=='quit':
                for effect in effects.values():effect.stop()
                app.quit();return
            effect=effects.get(name)
            if effect is not None:
                if action=='play':effect.play()
                elif action=='stop':effect.stop()
    timer=QTimer();timer.timeout.connect(drain);timer.start(20)
    app.exec()

if __name__=='__main__':main()
