"""Tests for the lies audit log module."""
from __future__ import annotations

import pytest

from purr import lies as liesmod
from purr import paths


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Point ~/.purr at tmp_path so we don't pollute the real log."""
    fake = tmp_path / "purr"
    fake.mkdir()
    monkeypatch.setattr(paths, "home", lambda: fake)
    # reset the module's cached log path so it picks up the new home
    liesmod._LOG_PATH = None
    yield fake
    liesmod._LOG_PATH = None


def test_record_writes_line(fake_home) -> None:
    liesmod.record(agent="dross", model="llama3-groq-tool-use:8b",
                   claim="I have saved", tab_idx=0, strikes=1)
    p = fake_home / "logs" / "lies.log"
    assert p.exists()
    content = p.read_text()
    assert "AGENT:dross" in content
    assert "MODEL:llama3-groq-tool-use:8b" in content
    assert 'CLAIM:"I have saved"' in content
    assert "TAB:0" in content
    assert "STRIKES:1" in content


def test_record_appends(fake_home) -> None:
    liesmod.record(agent="dross", model="m", claim="first", tab_idx=0, strikes=1)
    liesmod.record(agent="dross", model="m", claim="second", tab_idx=0, strikes=2)
    liesmod.record(agent="dross", model="m", claim="third", tab_idx=0, strikes=3)
    p = fake_home / "logs" / "lies.log"
    lines = p.read_text().splitlines()
    assert len(lines) == 3
    assert "first" in lines[0]
    assert "second" in lines[1]
    assert "third" in lines[2]


def test_record_truncates_long_claim(fake_home) -> None:
    long_claim = "x" * 500
    liesmod.record(agent="dross", model="m", claim=long_claim, tab_idx=0, strikes=1)
    p = fake_home / "logs" / "lies.log"
    content = p.read_text()
    # the claim is truncated to 120 chars in the log line
    assert content.count("x") == 120


def test_record_swallows_exceptions(fake_home, monkeypatch) -> None:
    """Logging must never crash the session — even on disk errors."""
    def _boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("builtins.open", _boom)
    # should not raise
    liesmod.record(agent="dross", model="m", claim="x", tab_idx=0, strikes=1)


def test_tail_empty_log(fake_home) -> None:
    assert "no lies" in liesmod.tail(20).lower()


def test_tail_returns_recent(fake_home) -> None:
    for i in range(25):
        liesmod.record(agent="dross", model="m", claim=f"lie {i}", tab_idx=0, strikes=i)
    out = liesmod.tail(5)
    lines = out.splitlines()
    assert len(lines) == 5
    # tail returns the LAST 5 — lie 20, 21, 22, 23, 24
    assert "lie 20" in lines[0]
    assert "lie 24" in lines[-1]


def test_tail_clamps_to_log_size(fake_home) -> None:
    for i in range(3):
        liesmod.record(agent="dross", model="m", claim=f"lie {i}", tab_idx=0, strikes=i)
    out = liesmod.tail(50)  # asked for 50, only 3 in log
    assert out.count("lie") == 3
