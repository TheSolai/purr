"""Render a screenshot of purr for the README.

This uses Textual's `Pilot.save_screenshot()` which writes an SVG that
captures the live TUI state. We then convert SVG → PNG for embedding.

Usage (from the purr venv):
    PURR_HOME=/tmp/purr-screenshot python scripts/capture_screenshot.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from purr.app import PurrApp
from purr.ollama_client import ChatMessage, OllamaClient


async def main() -> int:
    svg_path = Path(__file__).parent.parent / "docs" / "screenshot.svg"
    svg_path.parent.mkdir(parents=True, exist_ok=True)

    app = PurrApp()

    async with app.run_test(size=(130, 38)) as pilot:
        # Seed a couple of demo messages so the screenshot shows a real conversation
        app._append_bubble(
            "user",
            "show me what's eating my CPU and memory",
            "#89dceb",
        )
        app._append_tool(
            "app_status",
            {},
            (
                "📊 Mac activity\n"
                "  20:51  up 8 days, 19:00, 1 user, load averages: 4.83 4.39 4.75\n"
                "  Pages free:    3227001.\n"
                "  Pages active:  2285199.\n"
                "  Pages wired down: 439767.\n"
                "\n"
                "  Top 5 by CPU:\n"
                "  🧠 5 process(es) (sorted by cpu)\n"
                "        PID   %CPU   %MEM       RSS  COMMAND\n"
                "      56776  383.4    4.3    5584 MB  /Applications/Ol\n"
                "      73743   98.1    0.5     640 MB  /Users/amre/Libr\n"
                "      37593   97.8   11.6   15139 MB  /Users/amre/Libr\n"
                "        593   43.3    0.3     396 MB  /System/Library\n"
                "      41263   40.1    0.6     770 MB  /Applications/Mi"
            ),
        )
        app._append_bubble(
            "assistant",
            (
                "I am Dross, the most valuable mind-spirit in the world. "
                "Your top CPU hogs are Ollama itself (we're using it), plus a 15GB Python "
                "process in your Library eating RAM. Want me to kill the 15GB one? Just say the word."
            ),
            "#cdd6f4",
        )
        app._append_bubble(
            "user",
            "do it — pid 37593, send TERM",
            "#89dceb",
        )
        app._append_tool(
            "kill_process",
            {"pid": 37593, "signal": "TERM"},
            "💀 sent SIGTERM to pid 37593",
        )
        app._append_bubble(
            "assistant",
            "Done. The process received SIGTERM. Check with `processes(filter='python')` — if it's still there, say the word and I'll fire SIGKILL.",
            "#cdd6f4",
        )

        # Give the UI a tick to render everything, then save
        await pilot.pause()
        app.save_screenshot(svg_path)
        print(f"wrote {svg_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
