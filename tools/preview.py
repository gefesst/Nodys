"""Start an isolated local server and one or two Nodys clients."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clients', type=int, choices=(1, 2), default=2)
    parser.add_argument("--smoke-seconds", type=float, default=0)
    args = parser.parse_args()
    children = []
    with tempfile.TemporaryDirectory(prefix='nodys-preview-') as directory:
        data = Path(directory)
        server.DB_FILE = str(data / 'users.db')
        server.CHAT_DB = str(data / 'chat.db')
        server.init_db()
        server.init_chat_db()
        tokens = {}
        for login in ('alice', 'bob'):
            server.add_user(login, 'preview-only', login.title(), '')
            tokens[login] = server.create_session(login)[0]
        server.send_friend_request('alice', 'bob')
        server.accept_friend_request('alice', 'bob')
        channel = server.create_channel('alice', 'Тестовый канал')
        server.join_channel_by_code('bob', channel['code'])
        env = dict(os.environ, PYTHONFAULTHANDLER="1", NODYS_DB_FILE=server.DB_FILE, NODYS_CHAT_DB=server.CHAT_DB)
        try:
            children.append(subprocess.Popen([sys.executable, '-u', '-c', "import server; server.start_server('127.0.0.1',15555)"], cwd=ROOT/'server', env=env))
            children.append(subprocess.Popen([sys.executable, '-u', '-c', "import voice_server as v; v.HOST='127.0.0.1'; v.PORT=15556; v.main()"], cwd=ROOT/'server', env=env))
            time.sleep(0.5)
            if any(p.poll() is not None for p in children):
                raise RuntimeError('Preview server failed; check ports 15555/15556')
            for login in ('alice', 'bob')[:args.clients]:
                config_dir = data / login
                config_dir.mkdir()
                (config_dir/'config.json').write_text(json.dumps({'login':login,'token':tokens[login], 'api_host':'127.0.0.1','api_port':15555,'voice_host':'127.0.0.1','voice_port':15556}))
                children.append(subprocess.Popen([sys.executable, str(ROOT/'client/main.py')], env=dict(env,NODYS_CONFIG_DIR=str(config_dir))))
            print('Preview: Alice owns the channel, Bob is a member. Close clients or press Ctrl+C to stop.', flush=True)
            started = time.monotonic()
            while any(p.poll() is None for p in children[2:]):
                if args.smoke_seconds:
                    if any(p.poll() is not None for p in children):
                        raise RuntimeError(f'A preview process exited unexpectedly: {[p.poll() for p in children]}')
                    if time.monotonic() - started >= args.smoke_seconds:
                        print('Preview process smoke passed', flush=True)
                        break
                time.sleep(0.3)
            if args.smoke_seconds and any(p.poll() is not None for p in children):
                raise RuntimeError('Preview exited before smoke completed')
        finally:
            for process in children:
                if process.poll() is None:
                    process.terminate()
            for process in children:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
