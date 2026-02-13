"""Centralized runtime settings.

All values are overridable via config.json saved in the user's config directory.
"""

from __future__ import annotations

from typing import Tuple

from config import load_config


DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 5555
DEFAULT_VOICE_HOST = "127.0.0.1"
DEFAULT_VOICE_PORT = 5556


def get_api_endpoint() -> Tuple[str, int]:
    cfg = load_config()
    host = cfg.get("api_host", DEFAULT_API_HOST)
    port = int(cfg.get("api_port", DEFAULT_API_PORT))
    return host, port


def get_voice_endpoint() -> Tuple[str, int]:
    cfg = load_config()
    host = cfg.get("voice_host", DEFAULT_VOICE_HOST)
    port = int(cfg.get("voice_port", DEFAULT_VOICE_PORT))
    return host, port
