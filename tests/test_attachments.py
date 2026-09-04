"""Tests for @file expansion in user messages."""
from __future__ import annotations

import pytest

from purr.attachments import AttachmentError, expand_attachments


def test_no_at_sign_unchanged() -> None:
    assert expand_attachments("just a normal message") == "just a normal message"


def test_single_bare_path(tmp_path) -> None:
    f = tmp_path / "foo.py"
    f.write_text("print('hi')\n")
    out = expand_attachments(f"see @{f}", base_dir=str(tmp_path.parent))
    assert "print('hi')" in out
    assert f"@{f}" not in out
    assert "```python" in out
    assert str(f) in out


def test_tilde_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    f = tmp_path / "tail.md"
    f.write_text("the cat coded at dawn\n")
    out = expand_attachments("check @~/tail.md")
    assert "the cat coded at dawn" in out
    assert "@~/" not in out


def test_relative_path(tmp_path) -> None:
    f = tmp_path / "notes.md"
    f.write_text("notes here\n")
    out = expand_attachments("look at @./notes.md", base_dir=str(tmp_path))
    assert "notes here" in out


def test_quoted_path_with_spaces(tmp_path) -> None:
    d = tmp_path / "my docs"
    d.mkdir()
    f = d / "notes.md"
    f.write_text("spaced out\n")
    out = expand_attachments(f"read @'{f}'")
    assert "spaced out" in out


def test_multiple_attachments(tmp_path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("a_contents\n")
    b.write_text("b_contents\n")
    out = expand_attachments(f"diff @{a} and @{b}", base_dir=str(tmp_path.parent))
    assert "a_contents" in out
    assert "b_contents" in out


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(AttachmentError) as ei:
        expand_attachments(f"see @{tmp_path / 'nope.md'}")
    assert "not found" in str(ei.value).lower()


def test_directory_raises(tmp_path) -> None:
    d = tmp_path / "subdir"
    d.mkdir()
    with pytest.raises(AttachmentError) as ei:
        expand_attachments(f"@{d}")
    assert "directory" in str(ei.value).lower()


def test_oversized_file_raises(tmp_path) -> None:
    f = tmp_path / "huge.txt"
    f.write_text("x" * 300_000)  # > 200kB cap
    with pytest.raises(AttachmentError) as ei:
        expand_attachments(f"@{f}")
    assert "too large" in str(ei.value).lower()


def test_email_not_treated_as_attachment() -> None:
    """`@` in an email address or handle must not be expanded."""
    # Plain email — should pass through untouched (the @ is preceded by
    # alphanumeric, so the negative lookbehind blocks the match).
    out = expand_attachments("email me at amre@example.com")
    assert "amre@example.com" in out
    assert out == "email me at amre@example.com"

    # "@TheSolAI" still matches (it's a free-standing @). It will then fail
    # at the read step because no such file exists — but the message should
    # not be silently corrupted; the caller should surface the error.
    with pytest.raises(AttachmentError):
        expand_attachments("send to @TheSolAI")
