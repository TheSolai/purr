"""Lies audit log — every hallucinated claim gets a permanent record.

When the assistant claims an action ("I have saved the file") without
actually calling the tool, purr logs it here. The user can `tail -f` the
log from another shell to see the pattern, or `/lies` in the TUI.

Format (one line, easy to grep):
    2026-09-04T22:38:00 | AGENT:dross | MODEL:llama3-groq-tool-use:8b | CLAIM:"I have saved" | TAB:1 | STRIKES:1

Writes are append-only and never crash the session on error — same
discipline as the YOLO audit log.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from purr import paths


_LOG_PATH: Path | None = None


def _log_path() -> Path:
    global _LOG_PATH
    if _LOG_PATH is None:
        d = paths.home() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        _LOG_PATH = d / "lies.log"
    return _LOG_PATH


def record(agent: str, model: str, claim: str, tab_idx: int, strikes: int) -> None:
    """Append one lie event to the audit log."""
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        c = claim.replace("\n", " ")[:120]
        line = (
            f"{ts} | AGENT:{agent} | MODEL:{model} | CLAIM:\"{c}\" "
            f"| TAB:{tab_idx} | STRIKES:{strikes}\n"
        )
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # Logging must never crash the user's session.
        pass


def tail(n: int = 20) -> str:
    """Return the last n lines of the lies log (for /lies view)."""
    p = _log_path()
    if not p.exists():
        return "(no lies logged yet — purr is honest today 🎉)"
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:]) if lines else "(empty)"
    except Exception as e:
        return f"(couldn't read log: {e})"
