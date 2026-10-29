"""Persistent manual noda preview, separate from disposable automated checks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from review_support.sandbox import Sandbox

ROOT = Path(__file__).resolve().parents[1]

def preview_directory():
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home()))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    return base / 'noda' / 'preview'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--smoke-seconds",type=float,default=0)
    args=parser.parse_args()
    data_dir=None if args.smoke_seconds else preview_directory()
    lock=None
    if data_dir is not None:
        from PySide6.QtCore import QLockFile
        data_dir.mkdir(parents=True,exist_ok=True)
        lock=QLockFile(str(data_dir/'preview.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            print('noda preview is already running.',flush=True)
            return
    lab = Sandbox(ROOT, reference_dialogs=True, data_dir=data_dir)
    try:
        path = lab.path / 'config/config.json'
        config = json.loads(path.read_text())
        config.update(login=lab.me, token=lab.tokens[lab.me])
        path.write_text(json.dumps(config));path.chmod(0o600)
        child = subprocess.Popen([sys.executable, str(ROOT/'client/main.py')], env=os.environ.copy())
        lab.children.append(child)
        print('noda: persistent local preview running', flush=True)
        if args.smoke_seconds:
            try:
                child.wait(timeout=args.smoke_seconds)
                raise RuntimeError("Preview client exited during startup smoke")
            except subprocess.TimeoutExpired:
                if any(p.poll() is not None for p in lab.children):
                    raise RuntimeError("Preview server exited during startup smoke")
                print("noda preview startup smoke passed",flush=True)
        else:
            child.wait()
    except KeyboardInterrupt:
        pass
    finally:
        lab.close()
        if lock is not None:
            lock.unlock()

if __name__ == '__main__':
    main()
