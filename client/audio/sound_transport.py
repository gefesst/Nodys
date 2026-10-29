"""Nonblocking commands to a disposable process, not the GUI/audio thread."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

class SoundTransport:
    def __init__(self):
        self.commands=queue.Queue()
        self.started=False

    def send(self, action, name):
        if not self.started:
            if action!='play':return
            self.started=True
            threading.Thread(target=self._run,args=(self.commands,),daemon=True,name='ui-sound-commands').start()
        self.commands.put((action,name))

    def close(self):
        if self.started:self.commands.put(("quit",""))
        self.commands=queue.Queue()
        self.started=False

    def _run(self, commands):
        process=None
        try:
            process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('sound_player.py'))],
                stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                text=True,bufsize=1)
            while True:
                action,name=commands.get()
                process.stdin.write(json.dumps([action,name])+'\n')
                process.stdin.flush()
                if action=="quit":break
        except (OSError,ValueError):
            # Audio failure must never take down the application.
            pass
        finally:
            if process is not None:
                if process.stdin:process.stdin.close()
                if process.poll() is None:process.terminate()
            if self.commands is commands:self.started=False

class RemoteEffect:
    def __init__(self,transport):self.transport=transport;self.name=''
    def setSource(self,url):self.name=Path(url.toLocalFile()).stem
    def setVolume(self,value):pass
    def setLoopCount(self,value):pass
    def play(self):self.transport.send('play',self.name)
    def stop(self):self.transport.send('stop',self.name)
