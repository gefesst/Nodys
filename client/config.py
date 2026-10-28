import json
import os
import shutil
from typing import Any, Dict


APP_NAME = "Nodys"
LEGACY_CONFIG_FILE = "config.json"  # старое расположение (cwd)


def _get_user_config_dir() -> str:
    """Папка настроек пользователя (кросс‑платформенно)."""
    override = os.environ.get("NODYS_CONFIG_DIR")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if not base:
            base = os.path.expanduser("~")
        return os.path.join(base, APP_NAME)

    # Linux/macOS
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return os.path.join(xdg, APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".config", APP_NAME)


def get_config_path() -> str:
    os.makedirs(_get_user_config_dir(), exist_ok=True)
    return os.path.join(_get_user_config_dir(), "config.json")


def _migrate_legacy_config_if_needed() -> None:
    """Мягкая миграция старого config.json из cwd в user-config dir."""
    if os.environ.get("NODYS_CONFIG_DIR"):
        return
    try:
        new_path = get_config_path()
        if os.path.exists(new_path):
            return
        if os.path.exists(LEGACY_CONFIG_FILE):
            # Если файл уже рядом — переносим
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.copy2(LEGACY_CONFIG_FILE, new_path)
            # старый не удаляем насильно (на всякий случай)
    except Exception:
        pass


def load_config() -> Dict[str, Any]:
    _migrate_legacy_config_if_needed()
    path = get_config_path()
    if not os.path.exists(path):
        # fallback to legacy (если по какой-то причине не мигрировалось)
        if not os.environ.get("NODYS_CONFIG_DIR") and os.path.exists(LEGACY_CONFIG_FILE):
            try:
                with open(LEGACY_CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: Dict[str, Any]) -> None:
    path = get_config_path()
    existing = load_config()
    existing.update(data)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)
    os.replace(temporary, path)


def clear_config() -> None:
    # Session removal must preserve connection preferences.
    existing = load_config()
    preferences = {key: value for key, value in existing.items()
                   if key in {"api_host", "api_port", "voice_host", "voice_port"}}
    paths = [get_config_path()]
    if not os.environ.get("NODYS_CONFIG_DIR"):
        paths.append(LEGACY_CONFIG_FILE)
    for path in paths:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    save_config(preferences)
