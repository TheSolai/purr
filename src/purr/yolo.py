"""YOLO mode — pre-approve all dangerous tool calls.

When YOLO is enabled:
- All dangerous tools run WITHOUT the safety modal
- Every action is appended to ~/.purr/logs/yolo-actions.log (append-only)
- The header shows a pulsing red "YOLO" warning

Disabling is one keystroke (`/yolo`) — no confirmation needed.
Enabling requires an extra confirmation because it grants full system trust.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from purr import paths


_LOG_PATH: Path | None = None


def _log_path() -> Path:
    """~/.purr/logs/yolo-actions.log — created on first call."""
    global _LOG_PATH
    if _LOG_PATH is None:
        d = paths.home() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        _LOG_PATH = d / "yolo-actions.log"
    return _LOG_PATH


def record(tool_name: str, args: dict, result: str) -> None:
    """Append one entry to the YOLO audit log.

    Format (one line, easy to grep):
        2026-09-04T20:57:30 | TOOL:kill_process | args={pid: 37593, signal: TERM} | result=ok
    """
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        # truncate result for the log (no need to dump megabytes)
        r = (result or "").replace("\n", " ")[:200]
        a = repr(args)[:300]
        line = f"{ts} | TOOL:{tool_name} | args={a} | result={r}\n"
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # Logging must never crash the user's session.
        pass


def tail(n: int = 20) -> str:
    """Return the last n lines of the YOLO audit log (for /yolo view)."""
    p = _log_path()
    if not p.exists():
        return "(no yolo actions logged yet)"
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:]) if lines else "(empty)"
    except Exception as e:
        return f"(couldn't read log: {e})"
