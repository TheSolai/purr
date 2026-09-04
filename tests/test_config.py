"""Tests for the config loader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from purr import config as cfg_mod
from purr.config import Config


def test_default_values():
    c = Config()
    assert c.ollama_host == "http://localhost:11434"
    assert c.default_model  # some non-empty default
    assert c.theme == "catppuccin-mocha"
    assert c.confirm_dangerous_tools is True
    assert c.max_history_messages == 50
    assert 0.0 <= c.temperature <= 2.0


def test_save_and_reload(tmp_path, monkeypatch):
    """Round-trip: write a config, read it back, verify equality."""
    monkeypatch.setattr(cfg_mod.paths, "config_path", lambda: tmp_path / "config.toml")
    cfg = Config(
        ollama_host="http://example:9999",
        default_model="some-model:7b",
        theme="dracula",
        confirm_dangerous_tools=False,
        max_history_messages=100,
        temperature=0.3,
    )
    cfg.save()
    reloaded = Config.load()
    assert reloaded.ollama_host == "http://example:9999"
    assert reloaded.default_model == "some-model:7b"
    assert reloaded.theme == "dracula"
    assert reloaded.confirm_dangerous_tools is False
    assert reloaded.max_history_messages == 100
    assert reloaded.temperature == 0.3


def test_load_missing_returns_defaults(tmp_path, monkeypatch):
    """If the config file doesn't exist, Config.load() should return defaults
    AND write them out so the user can edit."""
    monkeypatch.setattr(cfg_mod.paths, "config_path", lambda: tmp_path / "config.toml")
    c = Config.load()
    assert c.ollama_host == "http://localhost:11434"
    # And it should have written the defaults
    assert (tmp_path / "config.toml").exists()


def test_load_malformed_falls_back_to_defaults(tmp_path, monkeypatch):
    """If the config file is broken, we should NOT crash — fall back to defaults."""
    bad = tmp_path / "config.toml"
    bad.write_text("this is = not valid toml = at all ===")
    monkeypatch.setattr(cfg_mod.paths, "config_path", lambda: bad)
    c = Config.load()
    assert c.ollama_host == "http://localhost:11434"  # default
