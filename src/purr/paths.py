"""Filesystem locations for purr state, config, agents, chats."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "purr"
ENV_HOME = "PURR_HOME"


def home() -> Path:
    """Return the purr home directory (~/.purr by default)."""
    override = os.environ.get(ENV_HOME)
    if override:
        p = Path(override).expanduser().resolve()
    else:
        p = Path.home() / f".{APP_NAME}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return home() / "config.toml"


def agents_dir() -> Path:
    p = home() / "agents"
    p.mkdir(parents=True, exist_ok=True)
    return p


def chats_dir() -> Path:
    p = home() / "chats"
    p.mkdir(parents=True, exist_ok=True)
    return p


def builtin_agents_dir() -> Path:
    """Where the 4 default personas live inside the package."""
    return Path(__file__).parent / "agents_builtin"
