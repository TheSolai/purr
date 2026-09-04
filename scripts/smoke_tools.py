"""Smoke test for purr's tool layer — exercises each macOS tool directly.

Run from the purr venv:  python scripts/smoke_tools.py
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from purr import tools as t


def show(label: str, out: str) -> None:
    out = out.strip().splitlines()
    if len(out) <= 8:
        print(f"\n=== {label} ===")
        for line in out:
            print("  " + line)
    else:
        print(f"\n=== {label} (first 8 of {len(out)} lines) ===")
        for line in out[:8]:
            print("  " + line)
        print(f"  …(truncated)")


def main() -> int:
    # 1) system_info (safe)
    show("system_info", t.system_info())

    # 2) shell — read-only
    show("shell: uname -a", t.shell("uname -a"))
    show("shell: ls ~/code/purr", t.shell("ls -la /Users/amre/code/purr"))
    show("shell: refuses dangerous", t.shell("rm -rf /tmp/should_not_delete"))

    # 3) file_read
    show("file_read: pyproject.toml", t.file_read("/Users/amre/code/purr/pyproject.toml"))
    show("file_read: /Users/amre/code/purr", t.file_read("/Users/amre/code/purr"))

    # 4) calendar — today
    show("calendar: today", t.calendar("today"))
    show("calendar: list", t.calendar("list_calendars"))

    # 5) reminders — list (no mutation)
    show("reminders: list", t.reminders("list"))

    # 6) notes — list
    show("notes: list", t.notes("list"))

    # 7) app_launcher — open Activity Monitor (safe, doesn't modify state)
    show("app_launcher: Activity Monitor", t.app_launcher("Activity Monitor"))

    # 8) macos_run — say "hi" (no-op)
    show('macos_run: say ""', t.macos_run('say ""'))

    return 0


if __name__ == "__main__":
    sys.exit(main())
