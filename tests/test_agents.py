"""Tests for the agent manager + builtin personas."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from purr.agents import Agent, AgentManager


def test_builtin_personas_present():
    """All 5 built-in personas must exist on disk after first seed."""
    mgr = AgentManager()
    names = {a.name for a in mgr.all()}
    assert {"dross", "assistant", "friend", "planner", "sysadmin"}.issubset(names)


def test_builtin_personas_have_required_fields():
    mgr = AgentManager()
    for a in mgr.all():
        assert a.name
        assert a.role
        assert a.glyph
        assert a.system_prompt
        assert isinstance(a.tools, list)
        assert a.category in {"friend", "assistant", "planner", "sysadmin", "general"}


def test_friend_is_chat_only():
    """Friend must be enforced chat-only."""
    mgr = AgentManager()
    friend = mgr.get("friend")
    assert friend is not None
    assert friend.tools == []
    assert friend.category == "friend"


def test_dross_is_main_man():
    """Dross must have the activity monitor tools + the openclaw voice."""
    mgr = AgentManager()
    dross = mgr.get("dross")
    assert dross is not None
    # Dross has the new activity monitor tools
    must_have = {"app_status", "processes", "kill_process", "desktop_summary"}
    assert must_have.issubset(set(dross.tools))


def test_category_label():
    a = Agent(
        name="test", role="r", glyph="(·_·)", system_prompt="x",
        category="friend", tools=[],
    )
    assert a.category_label == "friend"
    # Unknown names get title-cased (this is intentional behavior)
    assert a.title == "Test"


def test_known_titles():
    """dross, assistant, friend, planner, sysadmin have fixed titles."""
    for name, expected in [("dross", "Dross"), ("assistant", "Assistant"),
                            ("friend", "Friend"), ("planner", "Mac Planner"),
                            ("sysadmin", "Sysadmin")]:
        a = Agent(name=name, role="r", glyph="x", system_prompt="x", tools=[])
        assert a.title == expected


def test_to_from_json_roundtrip():
    a = Agent(
        name="roundtrip", role="tester", glyph="(x_x)",
        system_prompt="hello", tools=["shell"], temperature=0.5,
        category="assistant", builtin=False,
    )
    roundtripped = Agent.from_json(a.to_json())
    assert roundtripped.name == a.name
    assert roundtripped.role == a.role
    assert roundtripped.glyph == a.glyph
    assert roundtripped.system_prompt == a.system_prompt
    assert roundtripped.tools == a.tools
    assert roundtripped.temperature == a.temperature
    assert roundtripped.category == a.category


def test_from_json_backfills_category():
    """Older JSON without a `category` field should still parse."""
    data = json.dumps({
        "name": "legacy", "role": "x", "glyph": "(·_·)",
        "system_prompt": "x", "tools": [],
    })
    a = Agent.from_json(data)
    assert a.category == "general"  # default


def test_new_agent_then_get_then_delete(tmp_path, monkeypatch):
    """Round-trip: new → save → get → delete."""
    # Patch the agents dir to a temp location
    import purr.paths as paths_mod
    monkeypatch.setattr(paths_mod, "agents_dir", lambda: tmp_path)
    mgr = AgentManager()
    name = "test-new"
    a = mgr.new(name, role="test role")
    assert mgr.get(name) is not None
    assert mgr.get(name).role == "test role"
    assert mgr.delete(name) is True
    assert mgr.get(name) is None


def test_new_duplicate_name_raises():
    mgr = AgentManager()
    try:
        mgr.new("test-dup", role="first")
        with pytest.raises(ValueError):
            mgr.new("test-dup", role="second")
    finally:
        mgr.delete("test-dup")


def test_builtin_names():
    mgr = AgentManager()
    builtins = set(mgr.builtin_names())
    assert builtins == {"dross", "assistant", "friend", "planner", "sysadmin"}


def test_delete_nonexistent_returns_false():
    mgr = AgentManager()
    assert mgr.delete("this-does-not-exist") is False


def test_get_nonexistent_returns_none():
    mgr = AgentManager()
    assert mgr.get("this-does-not-exist") is None
