"""Tests for the purr tool registry.

These tests run WITHOUT an Ollama server, an editor, or any macOS-only
features. They verify that the tool registry is well-formed and that
the safe (non-dangerous) tools work correctly. Dangerous tools (kill,
trash, etc.) are only smoke-tested for shape, not behavior.
"""
from __future__ import annotations

import platform
import subprocess

import pytest

from purr import tools as t


def test_registry_count():
    """We expect exactly 29 tools shipped in v0.2 (added web_fetch + web_search)."""
    assert len(t.TOOLS) == 29


def test_every_tool_has_schema():
    """Each registered tool must have a name, function, and OpenAI-style schema."""
    for name, spec in t.TOOLS.items():
        assert spec.name == name
        assert callable(spec.fn)
        assert spec.schema["type"] == "function"
        assert spec.schema["function"]["name"] == name
        assert "description" in spec.schema["function"]
        assert "parameters" in spec.schema["function"]
        # Parameters must be an object schema
        params = spec.schema["function"]["parameters"]
        assert params["type"] == "object"
        assert "properties" in params


def test_dangerous_flag_set_on_mutating_tools():
    """Tools that mutate state must be flagged dangerous=True."""
    must_be_dangerous = {
        "calendar",      # add event
        "reminders",     # add/complete
        "notes",         # add note
        "macos_run",     # arbitrary AppleScript
        "brew",          # install/update
        "file_write",
        "move_to",
        "trash",
        "desktop_cleanup",
        "download",
        "install_app",
        "kill_process",
    }
    for name in must_be_dangerous:
        assert t.TOOLS[name].dangerous, f"{name} should be marked dangerous"


def test_safe_tools_not_dangerous():
    """Read-only tools must NOT be flagged dangerous."""
    must_be_safe = {
        "shell", "file_read", "system_info", "app_launcher",
        "mkdir", "list_dir", "find_files", "disk_usage", "reveal_in_finder",
        "desktop_summary", "open_url",
        "app_status", "processes", "top_processes", "process_info",
    }
    for name in must_be_safe:
        assert not t.TOOLS[name].dangerous, f"{name} should NOT be marked dangerous"


def test_friend_has_no_tools_in_builtin():
    """Friend persona must be chat-only (zero tools) — built into the persona guard."""
    import json
    friend = json.loads((t.Path(t.__file__).parent / "agents_builtin" / "friend.json").read_text())
    assert friend["tools"] == []
    assert friend["category"] == "friend"


def test_dross_has_activity_tools():
    """Dross must have the new activity monitor tools enabled."""
    import json
    dross = json.loads((t.Path(t.__file__).parent / "agents_builtin" / "dross.json").read_text())
    must_have = {"app_status", "processes", "top_processes", "process_info", "kill_process"}
    assert must_have.issubset(set(dross["tools"])), f"Dross is missing: {must_have - set(dross['tools'])}"


# ---- safe-tool behavior ---------------------------------------------------

def test_mkdir_creates_directory(tmp_path):
    p = tmp_path / "new_dir"
    result = t.mkdir(str(p))
    assert p.exists()
    assert "created" in result.lower()


def test_mkdir_idempotent(tmp_path):
    """mkdir should not error if the directory already exists."""
    p = tmp_path / "exists"
    p.mkdir()
    result = t.mkdir(str(p))
    assert "created" in result.lower()  # either created or already there


def test_list_dir_returns_files(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")
    result = t.list_dir(str(tmp_path))
    assert "a.txt" in result
    assert "b.txt" in result
    assert "(empty)" not in result


def test_list_dir_empty(tmp_path):
    result = t.list_dir(str(tmp_path))
    assert "0 entries" in result


def test_list_dir_nonexistent():
    result = t.list_dir("/nonexistent/path/at/all")
    assert "not found" in result.lower()


def test_system_info_format():
    """system_info should be a multi-line string with key=value pairs."""
    result = t.system_info()
    for key in ("os=", "python=", "user=", "shell="):
        assert key in result, f"system_info missing {key}"


def test_human_size_format():
    """_human_size is used by many tools — make sure it formats sensibly."""
    assert "B" in t._human_size(500)
    assert "KB" in t._human_size(2000)
    assert "MB" in t._human_size(2_000_000)
    assert "GB" in t._human_size(2_000_000_000)


def test_categorize_known_extensions():
    """desktop_cleanup depends on extension → category mapping."""
    assert t._categorize(t.Path("/tmp/photo.png")) == "Images"
    assert t._categorize(t.Path("/tmp/song.mp3")) == "Audio"
    assert t._categorize(t.Path("/tmp/code.py")) == "Code"
    assert t._categorize(t.Path("/tmp/app.dmg")) == "Installers"
    assert t._categorize(t.Path("/tmp/archive.zip")) == "Archives"
    assert t._categorize(t.Path("/tmp/notes.md")) == "Documents"
    assert t._categorize(t.Path("/tmp/font.ttf")) == "Fonts"
    assert t._categorize(t.Path("/tmp/clip.mp4")) == "Videos"
    assert t._categorize(t.Path("/tmp/random.xyz")) == "Other"


def test_desktop_summary_runs():
    """Smoke test — should not raise even on this dev box."""
    result = t.desktop_summary()
    # Either shows the actual desktop or "no Desktop at <path>"
    assert "Desktop" in result or "no Desktop" in result


def test_app_status_runs():
    """Smoke test — should produce a multi-section report."""
    result = t.app_status()
    assert "load" in result.lower() or "uptime" in result.lower()


def test_shell_refuses_rm_rf():
    """The shell tool must refuse obviously destructive commands."""
    result = t.shell("rm -rf /tmp/this_should_never_run")
    assert "refused" in result.lower() or "dangerous" in result.lower()


def test_shell_refuses_sudo():
    result = t.shell("sudo echo hi")
    assert "refused" in result.lower() or "dangerous" in result.lower()


def test_shell_refuses_kill_killall():
    result = t.shell("killall -9 Something")
    assert "refused" in result.lower() or "dangerous" in result.lower()


def test_shell_runs_safe_command():
    result = t.shell("echo hello")
    assert "hello" in result


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only")
def test_macos_run_safely():
    """Smoke test that osascript can at least echo something back."""
    result = t.macos_run('return "hi"')
    assert "hi" in result or "(no output)" in result or result == "hi"


def test_kill_process_refuses_pid_zero():
    """pid 0 is rejected as 'invalid pid' (the function short-circuits before
    the pid-in-set check). Verify the kill never actually fires."""
    result = t.kill_process(0)
    assert "invalid" in result.lower()
    # Sanity: pid 0 must not be running this test
    assert "💀" not in result  # would be the success marker


def test_kill_process_refuses_negative_pid():
    result = t.kill_process(-5)
    assert "invalid" in result.lower()


def test_kill_process_refuses_self():
    """purr must not be able to kill its own process."""
    import os
    result = t.kill_process(os.getpid())
    assert "refusing" in result.lower() or "my own" in result.lower()


# ---- spec helpers ---------------------------------------------------------

def test_specs_for_filters_unknown_names():
    """specs_for should silently drop unknown tool names."""
    specs = t.specs_for(["shell", "doesnt_exist", "file_read"])
    names = [s.name for s in specs]
    assert "shell" in names
    assert "file_read" in names
    assert "doesnt_exist" not in names


def test_schemas_for_filters_unknown_names():
    schemas = t.schemas_for(["shell", "nope"])
    schema_names = [s["function"]["name"] for s in schemas]
    assert "shell" in schema_names
    assert "nope" not in schema_names


def test_is_dangerous_tool():
    assert t.is_dangerous_tool("kill_process") is True
    assert t.is_dangerous_tool("list_dir") is False
    assert t.is_dangerous_tool("doesnt_exist") is False


# ---- web tools ------------------------------------------------------------

def test_web_tools_present():
    """Both web_fetch and web_search must be in the registry."""
    assert "web_fetch" in t.TOOLS
    assert "web_search" in t.TOOLS
    # web_fetch and web_search should NOT be dangerous — they're read-only
    assert not t.TOOLS["web_fetch"].dangerous
    assert not t.TOOLS["web_search"].dangerous
    # open_url also not dangerous (it just opens a browser)
    assert not t.TOOLS["open_url"].dangerous
    # download IS dangerous (writes to disk)
    assert t.TOOLS["download"].dangerous


def test_web_fetch_refuses_bad_schemes():
    """file://, javascript:, etc. should all be refused."""
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://example.com"):
        result = t.web_fetch(bad)
        assert "refused" in result.lower() or "bad url" in result.lower(), f"failed for {bad}: {result!r}"


def test_web_fetch_smoke():
    """Pull a real URL (GitHub raw README) and verify the title shows up."""
    result = t.web_fetch("https://raw.githubusercontent.com/TheSolai/purr/main/README.md", max_chars=2000)
    assert "purr" in result.lower()
    assert "ollama" in result.lower()


def test_web_search_refuses_empty():
    assert "empty" in t.web_search("").lower()


def test_web_search_returns_results():
    """Search for something we know exists."""
    result = t.web_search("python programming language", max_results=3)
    # Either we get results OR DDG rate-limited us — both are valid
    assert "result" in result.lower() or "no results" in result.lower()


def test_ddg_redirect_unwrap():
    """DDG returns //duckduckgo.com/l/?uddg=REAL&rut=... — we should unwrap.

    The unwrap helper is defined inside web_search as a closure, so we
    re-implement it here to keep the test self-contained.
    """
    from urllib.parse import parse_qs, urlparse

    def unwrap(url):
        if "duckduckgo.com/l/" not in url and "uddg=" not in url:
            return url
        try:
            parsed = urlparse(url if url.startswith("http") else "https:" + url)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return qs["uddg"][0]
        except Exception:
            pass
        return url

    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fpaulrobello%2Fparllama&rut=abc"
    assert unwrap(wrapped) == "https://github.com/paulrobello/parllama"
    # passthrough for non-DDG URLs
    assert unwrap("https://example.com/foo") == "https://example.com/foo"
