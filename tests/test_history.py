"""Tests for the history list/load helpers (used by /history and /resume)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from purr import history as histmod
from purr import paths


@pytest.fixture()
def fake_chats_dir(tmp_path, monkeypatch):
    """Point ~/.purr/chats at tmp_path so we don't pollute the real one."""
    fake = tmp_path / "chats"
    fake.mkdir()
    monkeypatch.setattr(paths, "chats_dir", lambda: fake)
    return fake


def _write_session(d: Path, agent: str, session: str, messages: list[dict]) -> Path:
    p = d / f"{agent}__{session}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return p


def test_list_sessions_empty(fake_chats_dir) -> None:
    assert histmod.list_sessions() == []


def test_list_sessions_returns_all(fake_chats_dir) -> None:
    _write_session(fake_chats_dir, "dross", "sess1", [
        {"ts": "2026-09-04T10:00:00", "role": "user", "content": "hi"},
        {"ts": "2026-09-04T10:00:01", "role": "assistant", "content": "hello!"},
    ])
    _write_session(fake_chats_dir, "coder", "sess2", [
        {"ts": "2026-09-04T11:00:00", "role": "user", "content": "fix the bug"},
    ])
    out = histmod.list_sessions()
    assert len(out) == 2
    names = {s["agent"] for s in out}
    assert names == {"dross", "coder"}


def test_list_sessions_filter_by_agent(fake_chats_dir) -> None:
    _write_session(fake_chats_dir, "dross", "s1", [{"ts": "t", "role": "user", "content": "x"}])
    _write_session(fake_chats_dir, "coder", "s2", [{"ts": "t", "role": "user", "content": "y"}])
    only_dross = histmod.list_sessions(agent="dross")
    assert len(only_dross) == 1
    assert only_dross[0]["agent"] == "dross"


def test_list_sessions_extracts_title(fake_chats_dir) -> None:
    _write_session(fake_chats_dir, "dross", "s1", [
        {"ts": "t", "role": "user", "content": "first user message"},
        {"ts": "t", "role": "assistant", "content": "hi"},
    ])
    out = histmod.list_sessions()
    assert out[0]["title"] == "first user message"
    assert out[0]["message_count"] == 2


def test_list_sessions_sorts_newest_first(fake_chats_dir) -> None:
    import time
    p1 = _write_session(fake_chats_dir, "dross", "older", [{"ts": "t", "role": "user", "content": "old"}])
    time.sleep(0.05)  # ensure distinct mtime
    p2 = _write_session(fake_chats_dir, "dross", "newer", [{"ts": "t", "role": "user", "content": "new"}])
    out = histmod.list_sessions()
    assert out[0]["session_id"] == "newer"
    assert out[1]["session_id"] == "older"


def test_list_sessions_truncates_long_title(fake_chats_dir) -> None:
    long = "x" * 500
    _write_session(fake_chats_dir, "dross", "s1", [{"ts": "t", "role": "user", "content": long}])
    out = histmod.list_sessions()
    assert len(out[0]["title"]) <= 80


def test_list_sessions_ignores_garbage_files(fake_chats_dir) -> None:
    (fake_chats_dir / "weird_file_no_separator.jsonl").write_text("noise\n")
    (fake_chats_dir / "another__with__double__sep.jsonl").write_text("noise\n")
    out = histmod.list_sessions()
    # `another__with__double__sep` will be parsed with `with` as session_id;
    # the first one is skipped because no `__` exists.
    assert all("path" in s for s in out)


def test_load_session_round_trip(fake_chats_dir) -> None:
    msgs = [
        {"ts": "t1", "role": "user", "content": "hello"},
        {"ts": "t2", "role": "assistant", "content": "hi back", "tool_calls": [{"function": {"name": "x"}}]},
        {"ts": "t3", "role": "tool", "content": "result", "tool_name": "x"},
    ]
    p = _write_session(fake_chats_dir, "dross", "round", msgs)
    agent, loaded = histmod.load_session(str(p))
    assert agent == "dross"
    assert len(loaded) == 3
    assert loaded[0].content == "hello"
    assert loaded[1].tool_calls == [{"function": {"name": "x"}}]
    assert loaded[2].tool_name == "x"


def test_load_session_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        histmod.load_session(str(tmp_path / "nope.jsonl"))


def test_load_session_bad_filename_raises(fake_chats_dir) -> None:
    p = fake_chats_dir / "no_separator.jsonl"
    p.write_text("noise\n")
    with pytest.raises(ValueError):
        histmod.load_session(str(p))
