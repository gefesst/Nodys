import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "server"))
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class FoundationTests(unittest.TestCase):
    def test_endpoint_survives_session_save(self):
        config = load('config_test', 'client/config.py')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, NODYS_CONFIG_DIR=folder):
            config.save_config({'api_port':15555})
            config.save_config({'token':'synthetic'})
            self.assertEqual(config.load_config()['api_port'],15555)

    def test_logout_preserves_endpoint_and_removes_token(self):
        config = load('logout_config', 'client/config.py')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, NODYS_CONFIG_DIR=folder):
            config.save_config({'api_port':15555, 'token':'synthetic', 'login':'alice'})
            config.clear_config()
            self.assertEqual(config.load_config(), {'api_port':15555})

    def test_fresh_session_goes_offline(self):
        server = load('server_test', 'server/server.py')
        with tempfile.TemporaryDirectory() as folder:
            server.DB_FILE = str(Path(folder)/'users.db')
            server.init_db()
            token, _ = server.create_session('synthetic')
            server.set_session_offline(token)
            self.assertFalse(server.is_online('synthetic'))

    def test_old_udp_address_is_removed(self):
        voice = load('voice_test', 'server/voice_server.py')
        voice._mark_seen('synthetic',('127.0.0.1',1))
        voice._mark_seen('synthetic',('127.0.0.1',2))
        self.assertNotIn(('127.0.0.1',1),voice.addr_to_login)

if __name__ == '__main__':
    unittest.main()
