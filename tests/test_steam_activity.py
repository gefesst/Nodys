import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from concurrent.futures import Future
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'client'))
from integrations.steam import detect, read_vdf
from test_voice_authorization import VoiceFixture


class SteamDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'Steam'
        (self.root/'config').mkdir(parents=True)
        (self.root/'steamapps/common/Game').mkdir(parents=True)
        self.users = self.root/'config/loginusers.vdf'
        self.users.write_text('"users" { "76561197960265729" { "PersonaName" "Игрок" "MostRecent" "1" } }', encoding='utf-8')
        (self.root/'steamapps/appmanifest_570.acf').write_text('"AppState" {"appid" "570" "name" "Dota 2" "installdir" "Game"}')
        self.processes = [dict(name='steam', exe=str(self.root/'steam')), dict(name='game.exe', exe=str(self.root/'steamapps/common/Game/game.exe'))]

    def scan(self, platform='darwin', account=None):
        return detect([self.root], self.processes, account=account, platform=platform)

    def test_windows_and_macos_nickname_and_running_game(self):
        for platform in ('darwin', 'win32'):
            result = self.scan(platform, '76561197960265729')
            self.assertEqual(result, dict(steam_nickname='Игрок', steam_game='Dota 2', steam_app_id='570'))

    def test_game_exit_steam_exit_and_ambiguous_account_clear(self):
        self.processes.pop()
        self.assertEqual(self.scan()['steam_game'], '')
        self.processes.clear()
        self.assertEqual(self.scan(), {})
        self.processes.append(dict(name='steam'))
        self.users.write_text('"users" { "1" { "PersonaName" "A" "MostRecent" "1" } "2" { "PersonaName" "B" "MostRecent" "1" } }')
        self.assertEqual(self.scan(), {})

    def test_account_switch_and_windows_logged_out_do_not_reuse_old_nick(self):
        self.assertEqual(self.scan('win32', ''), {})
        self.assertEqual(self.scan('win32', '76561197960265730'), {})
        self.users.write_text('"users" { "76561197960265730" { "PersonaName" "New" "MostRecent" "1" } }')
        self.assertEqual(self.scan('win32', '76561197960265730')['steam_nickname'], 'New')

    def test_macos_registry_identity_without_mostrecent(self):
        self.users.write_text('"users" { "1" { "PersonaName" "Current" "AccountName" "account" "AutoLogin" "1" } }')
        (self.root/'registry.vdf').write_text('"Registry" { "HKCU" { "Software" { "Valve" { "Steam" { "AutoLoginUser" "account" } } } } }')
        self.assertEqual(self.scan()['steam_nickname'], 'Current')
        (self.root/'registry.vdf').write_text('"Registry" { "HKCU" { "Software" { "Valve" { "Steam" { "AutoLoginUser" "different" } } } } }')
        self.assertEqual(self.scan(), {})

    def test_windows_registry_provider(self):
        from contextlib import nullcontext
        from integrations.steam import roots, active_account
        registry = SimpleNamespace(HKEY_CURRENT_USER=1,
            OpenKey=lambda *_:nullcontext('key'),
            QueryValueEx=lambda _key, name: (str(self.root) if name == 'SteamPath' else 1, 0))
        with patch.dict(sys.modules, winreg=registry):
            self.assertEqual(roots('win32'), [self.root])
            self.assertEqual(active_account('win32'), '76561197960265729')
        registry.OpenKey=lambda *_: (_ for _ in ()).throw(PermissionError())
        with patch.dict(sys.modules, winreg=registry):
            self.assertEqual(roots('win32'), [])
            self.assertEqual(active_account('win32'), '')

    def test_helpers_and_neighbor_paths_are_not_games(self):
        self.processes[-1]['name'] = 'crashhandler.exe'
        self.assertEqual(self.scan()['steam_game'], '')
        self.processes[-1] = dict(name='game', exe=str(self.root/'steamapps/common/GameOther/game'))
        self.assertEqual(self.scan()['steam_game'], '')

    def test_additional_library_and_macos_app_bundle(self):
        extra = Path(self.temp.name)/'Other Library'
        (extra/'steamapps/common/Second/Second.app/Contents/MacOS').mkdir(parents=True)
        escaped = str(extra).replace('\\', '\\\\')
        (self.root/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "'+escaped+'" } }')
        (extra/'steamapps/appmanifest_123.acf').write_text('"AppState" {"appid" "123" "name" "Second Game" "installdir" "Second"}')
        self.processes[-1] = dict(name='Second', exe=str(extra/'steamapps/common/Second/Second.app/Contents/MacOS/Second'))
        self.assertEqual(self.scan()['steam_app_id'], '123')

    def test_metadata_comments_escapes_partial_writes_and_bound(self):
        self.users.write_text('// comment\n"users" { "1" {"PersonaName" "A\\"B" "empty" ""} }')
        self.assertEqual(read_vdf(self.users)['users']['1']['personaname'], 'A"B')
        self.users.write_text('"users" {')
        self.assertEqual(self.scan(), {})
        self.users.write_text('x'*2_000_001)
        with self.assertRaises(ValueError):
            read_vdf(self.users)


class SteamServerTests(VoiceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server.send_friend_request('alice','bob')
        self.server.accept_friend_request('alice','bob')

    def publish(self, sequence=1, **extra):
        data = dict(action='heartbeat', token=self.tokens['alice'], activity_sequence=sequence,
                    steam_nickname='Steam Alice', steam_game='Game', steam_app_id='570')
        data.update(extra)
        return self.server.handle_request(data)

    def friends(self):
        return self.server.handle_request(dict(action='get_friends',token=self.tokens['bob']))['friends'][0]['steam_activity']

    def test_publish_friend_visibility_and_no_ownership_claim(self):
        self.assertEqual(self.publish()['status'], 'ok')
        self.assertEqual(self.friends()['nickname'], 'Steam Alice')
        result=self.server.handle_request(dict(action='find_user',token=self.tokens['bob'],target_login='alice'))
        self.assertNotIn('steam_activity', result)

    def test_disable_stale_updates_and_ttl(self):
        from storage.database import connect
        self.publish(2)
        self.publish(3, steam_nickname='',steam_game='',steam_app_id='')
        self.publish(2)
        self.assertIsNone(self.friends())
        self.publish(4)
        with connect(self.server.DB_FILE) as c:
            c.execute('UPDATE steam_activity SET updated_at=0')
        self.assertIsNone(self.friends())

    def test_session_revocation_and_offline_clear(self):
        self.publish()
        self.server.handle_request(dict(action='presence_offline',token=self.tokens['alice']))
        self.assertIsNone(self.friends())
        self.publish(2)
        self.assertIsNone(self.friends())  # delayed earlier update cannot undo close
        self.server.delete_session(self.tokens['alice'])
        self.assertEqual(self.publish(3)['status'], 'error')
        self.assertIsNone(self.friends())

    def test_validation_and_authenticated_sender(self):
        self.assertEqual(self.publish(steam_nickname=['bad'])['status'], 'error')
        self.assertEqual(self.publish(steam_app_id='x')['status'], 'error')
        self.assertEqual(self.publish(steam_game='<b>Game</b>\n')['status'], 'error')
        self.assertEqual(self.publish(token='bad')['status'], 'error')
        self.assertEqual(self.publish(login='bob')['status'], 'ok')
        self.assertEqual(self.friends()['nickname'], 'Steam Alice')

    def test_channel_member_visibility_and_acl(self):
        self.publish()
        self.server.handle_request(dict(action='set_channel_voice_presence',token=self.tokens['alice'],channel_id=self.channel['id'],joined=True))
        result=self.server.handle_request(dict(action='get_channel_rooms',token=self.tokens['bob'],channel_id=self.channel['id']))
        people=[p for r in result['rooms'] for p in r['participants']]
        self.assertEqual(people[0]['steam_activity']['game'], 'Game')
        self.server.add_user('outside','synthetic','Outside','')
        token=self.server.create_session('outside')[0]
        self.assertEqual(self.server.handle_request(dict(action='get_channel_rooms',token=token,channel_id=self.channel['id']))['status'], 'error')


class SteamMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_disable_discards_inflight_detection_and_publishes_clear(self):
        from PySide6.QtWidgets import QWidget
        from application.steam_presence import SteamPresence
        class Request:
            def __init__(self, *_args):
                self.data=_args[-1]
                self.finished=SimpleNamespace(connect=lambda cb:None)
            def start(self): pass
        window=QWidget()
        window.ctx=SimpleNamespace(session_token='test')
        window.is_logging_out=window._is_closing=False
        with patch('application.steam_presence.load_config',return_value={}), patch('application.steam_presence.save_config'), patch('application.steam_presence.NetworkThread',Request):
            monitor=SteamPresence(window)
            monitor.token='test'
            future=Future();monitor.future=future;monitor.scan_generation=monitor.generation
            monitor.set_enabled(False)
            self.assertEqual(monitor.request.data['steam_nickname'], '')
            future.set_result(dict(steam_nickname='Must not leak',steam_game='Game',steam_app_id='1'))
            monitor.tick()
            self.assertEqual(monitor.activity,{})
            monitor.timer.stop()
        window.close()

    def test_disabled_preference_survives_logout_and_restart(self):
        from config import save_config, load_config, clear_config
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, NODYS_CONFIG_DIR=folder):
            save_config({'share_steam_activity': False, 'token': 'private'})
            clear_config()
            self.assertFalse(load_config()['share_steam_activity'])
            self.assertNotIn('token', load_config())
