"""Read-only local Steam detection. No credentials, network calls or process injection."""
import re
import sys
from itertools import islice
from pathlib import Path

import psutil


def read_vdf(path):
    """Bounded parser for Steam's quoted KeyValues files (including escaped paths)."""
    with Path(path).open('r', encoding='utf-8-sig', errors='replace') as stream:
        text = stream.read(2_000_001)
    if len(text) > 2_000_000:
        raise ValueError('Steam metadata too large')
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])|(//[^\n]*)', text)
    values = []
    for quoted, brace, comment in tokens:
        if not comment:
            values.append(('brace', brace) if brace else ('text', re.sub(r'\\([\\"])', r'\1', quoted)))

    def parse(index, depth=0):
        if depth > 16:
            raise ValueError('Steam metadata nested too deeply')
        result = {}
        while index < len(values):
            kind, key = values[index]; index += 1
            if kind == 'brace' and key == '}' and depth:
                return result, index
            if kind != 'text' or index == len(values):
                raise ValueError('Incomplete Steam metadata')
            kind, value = values[index]; index += 1
            if kind == 'brace':
                if value != '{':
                    raise ValueError('Incomplete Steam metadata')
                value, index = parse(index, depth+1)
            result[key.casefold()] = value
        if depth:
            raise ValueError('Incomplete Steam metadata')
        return result, index
    return parse(0)[0]


def roots(platform=sys.platform, home=None):
    home = Path(home or Path.home())
    if platform == 'darwin':
        return [home/'Library/Application Support/Steam']
    if platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                return [Path(winreg.QueryValueEx(key, 'SteamPath')[0])]
        except OSError:
            return []
    return []


def active_account(platform=sys.platform):
    if platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam\ActiveProcess') as key:
                account = int(winreg.QueryValueEx(key, 'ActiveUser')[0])
                return str(76561197960265728 + account) if account else ''
        except OSError:
            return ''
    return None  # macOS has no supported registry equivalent; use unique MostRecent.


def process_snapshot():
    current = psutil.Process().username()
    return [p.info for p in psutil.process_iter(['name', 'exe', 'username'])
            if p.info.get('username') == current]


def detect(root_paths=None, processes=None, account=None, platform=None):
    platform = platform or sys.platform
    if platform not in ('win32', 'darwin'):
        return {}
    processes = process_snapshot() if processes is None else processes
    steam = [p for p in processes if str(p.get('name', '')).casefold() in ('steam', 'steam.exe', 'steam_osx')]
    if not steam:
        return {}
    executables = []
    for process in processes:
        exe = process.get('exe')
        name = str(process.get('name') or '').casefold()
        if exe and not any(part in name for part in ('helper', 'crash', 'launcher', 'uninstall', 'setup', 'reporter')):
            try:
                executables.append(Path(exe).resolve())
            except (OSError, ValueError):
                continue
    root_paths = roots(platform) if root_paths is None else root_paths
    if account is None:
        account = active_account(platform)
    for root in root_paths:
        root = Path(root)
        try:
            users = read_vdf(root/'config/loginusers.vdf').get('users', {})
            local_login = ''
            if platform == 'darwin':
                try:
                    registry = read_vdf(root/'registry.vdf')
                    for key in ('registry', 'hkcu', 'software', 'valve', 'steam'):
                        registry = registry.get(key, {})
                    local_login = registry.get('autologinuser', '')
                except (OSError, ValueError, AttributeError):
                    pass
            candidates = [v for k, v in users.items() if isinstance(v, dict)
                          and ((k == account) if account is not None else
                               (v.get('accountname') == local_login if local_login else v.get('mostrecent') == '1'))]
            if len(candidates) != 1:
                continue
            nickname = candidates[0].get('personaname', '')
            if not isinstance(nickname, str) or not nickname.strip():
                continue
            result = dict(steam_nickname=nickname.strip()[:128], steam_game='', steam_app_id='')
            libraries = {root}
            try:
                entries = read_vdf(root/'steamapps/libraryfolders.vdf').get('libraryfolders', {})
                for value in entries.values():
                    path = value.get('path') if isinstance(value, dict) else value
                    if isinstance(path, str) and Path(path).is_absolute():
                        libraries.add(Path(path))
            except (OSError, ValueError):
                pass
            games = {}
            for library in sorted(libraries):
                for manifest in islice((library/'steamapps').glob('appmanifest_*.acf'), 2000):
                    try:
                        app = read_vdf(manifest).get('appstate', {})
                        appid, name, folder = app.get('appid', ''), app.get('name', ''), app.get('installdir', '')
                        if not appid.isdecimal() or not name or not folder or '/' in folder or '\\' in folder or folder in ('.', '..'):
                            continue
                        base = (library/'steamapps/common'/folder).resolve()
                        if any(exe.is_relative_to(base) for exe in executables):
                            games[appid] = name[:128]
                    except (OSError, ValueError, TypeError, AttributeError):
                        continue
            if len(games) == 1:
                result['steam_app_id'], result['steam_game'] = next(iter(games.items()))
            return result
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return {}
