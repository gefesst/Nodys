import json
import os
import shutil
from typing import Any, Dict


APP_NAME = "Nodys"
LEGACY_CONFIG_FILE = "config.json"  # старое расположение (cwd)


def _get_user_config_dir() -> str:
    """Папка настроек пользователя (кросс‑платформенно)."""
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
        if os.path.exists(LEGACY_CONFIG_FILE):
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def clear_config() -> None:
    # удаляем только новый конфиг; legacy оставляем (мягко)
    try:
        path = get_config_path()
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
