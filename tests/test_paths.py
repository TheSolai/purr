"""Tests for path resolution and the PURR_HOME override."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from purr import paths


def test_default_home_is_dot_purr(monkeypatch):
    """By default, PURR home is ~/.purr (or %USERPROFILE%/.purr on Windows)."""
    # Ensure no override is set from the test environment
    monkeypatch.delenv("PURR_HOME", raising=False)
    h = paths.home()
    assert h.name == ".purr"
    assert h.exists()  # mkdir(parents=True, exist_ok=True)


def test_purr_home_override(monkeypatch, tmp_path):
    """PURR_HOME env var should redirect everything."""
    monkeypatch.setenv("PURR_HOME", str(tmp_path))
    h = paths.home()
    assert h == tmp_path.resolve()
    assert paths.config_path() == tmp_path / "config.toml"
    assert paths.agents_dir() == tmp_path / "agents"
    assert paths.chats_dir() == tmp_path / "chats"


def test_subdirs_created(tmp_path, monkeypatch):
    monkeypatch.setenv("PURR_HOME", str(tmp_path))
    paths.agents_dir()
    paths.chats_dir()
    assert (tmp_path / "agents").exists()
    assert (tmp_path / "chats").exists()
