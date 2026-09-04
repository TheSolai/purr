"""Render a representative purr TUI screenshot to PNG with Pillow.

This is the PNG companion to docs/screenshot.svg. We draw the same
conversation state directly with PIL using a monospace font — no SVG
parser, no font dependencies beyond what macOS ships.

Usage (from the purr venv):
    python scripts/render_screenshot_png.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Catppuccin Mocha — same palette the TUI uses.
BG          = (30,  30,  46)    # base
BG_PANEL    = (24,  24,  37)    # mantle
SURFACE     = (49,  50,  68)    # surface0
BORDER      = (69,  71,  90)    # surface2
FG          = (205, 214, 244)   # text
FG_DIM      = (166, 173, 200)   # subtext1
FG_MUTED    = (108, 112, 134)   # overlay0
USER_BLUE   = (137, 220, 235)   # blue
ASSIST_FG   = (205, 214, 244)   # text
DANGER      = (243, 139, 168)   # red
SUCCESS     = (166, 227, 161)   # green
YELLOW      = (249, 226, 175)   # yellow
LAVENDER    = (180, 190, 254)   # lavender
PINK        = (245, 194, 231)   # pink

# Layout — matches the live TUI at 130×38 cells.
COLS, ROWS         = 130, 38
CELL_W, CELL_H     = 8, 18          # Menlo 13pt @1x is ~8×18 px per cell
PADDING            = 8
HEADER_H           = 22
FOOTER_H           = 22
SIDEBAR_W          = 22 * CELL_W
CHAT_X             = SIDEBAR_W
CHAT_W             = COLS * CELL_W
TOTAL_W            = CHAT_W + 2 * PADDING
TOTAL_H            = ROWS * CELL_H + HEADER_H + FOOTER_H + 2 * PADDING

# Font — Menlo is shipped with every macOS install.
FONT_PATH          = "/System/Library/Fonts/Menlo.ttc"
FONT_SIZE          = 13


def _font(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=size)


def _cell(draw: ImageDraw.ImageDraw, x: int, y: int, ch: str, fill: tuple[int, int, int]) -> None:
    draw.text((x, y), ch, font=_font(), fill=fill)


def render() -> Image.Image:
    img = Image.new("RGB", (TOTAL_W, TOTAL_H), BG)
    d = ImageDraw.Draw(img)

    # --- top header bar ----------------------------------------------------
    d.rectangle([(0, 0), (TOTAL_W, HEADER_H)], fill=SURFACE)
    d.line([(0, HEADER_H), (TOTAL_W, HEADER_H)], fill=BORDER, width=1)
    d.text(
        (PADDING, 4),
        "(◉_◉)  Dross  [assistant]   ·   model: llama3-groq-tool-use:8b   ·   tools: 29   ·   type / for commands, ctrl+c to quit",
        font=_font(),
        fill=FG,
    )

    # --- left sidebar ------------------------------------------------------
    d.rectangle([(0, HEADER_H), (SIDEBAR_W, TOTAL_H - FOOTER_H)], fill=BG_PANEL)
    d.line([(SIDEBAR_W, HEADER_H), (SIDEBAR_W, TOTAL_H - FOOTER_H)], fill=BORDER, width=1)
    sx, sy = PADDING, HEADER_H + PADDING
    d.text((sx, sy), "AGENTS", font=_font(FONT_SIZE), fill=FG_DIM)
    sy += CELL_H + 4
    # active
    d.text((sx, sy), "  (◉_◉)  Dross", font=_font(), fill=LAVENDER)
    sy += CELL_H
    d.text((sx, sy), "        active", font=_font(), fill=FG_MUTED)
    sy += CELL_H + 4
    d.text((sx, sy), "  (=^.^=)  Assistant", font=_font(), fill=FG_DIM)
    sy += CELL_H
    d.text((sx, sy), "  (♥.♥)  Friend", font=_font(), fill=FG_DIM)
    sy += CELL_H
    d.text((sx, sy), "  (☼.☼)  Mac Planner", font=_font(), fill=FG_DIM)
    sy += CELL_H
    d.text((sx, sy), "  (>_>)  Sysadmin", font=_font(), fill=FG_DIM)
    sy += CELL_H + 8
    d.text((sx, sy), "  ctrl+n = new agent", font=_font(), fill=FG_MUTED)
    sy += CELL_H
    d.text((sx, sy), "  ctrl+t = next", font=_font(), fill=FG_MUTED)

    # --- main chat area ----------------------------------------------------
    cx = CHAT_X + PADDING
    cy = HEADER_H + PADDING

    def line(text: str, fg: tuple[int, int, int] = FG) -> None:
        nonlocal cy
        d.text((cx, cy), text, font=_font(), fill=fg)
        cy += CELL_H

    def blank() -> None:
        nonlocal cy
        cy += CELL_H // 2

    # user message
    line("(◉_◉)  you", FG_DIM)
    line("show me what's eating my CPU and memory", USER_BLUE)
    blank()

    # tool call
    line("🔧  app_status({})", YELLOW)
    line("    📊 Mac activity", FG)
    line("       20:51  up 8 days, load: 4.83 4.39 4.75", FG_DIM)
    line("       Pages active:  2285199    Pages wired: 439767", FG_DIM)
    line("       Top 5 by CPU:", FG)
    line("         PID   %CPU   %MEM       RSS  COMMAND", FG_DIM)
    line("       56776  383.4    4.3    5584 MB  /Applications/Ollama", FG)
    line("       73743   98.1    0.5     640 MB  /Users/amre/Library/…", FG)
    line("       37593   97.8   11.6   15139 MB  /Users/amre/Library/…", FG)
    line("         593   43.3    0.3     396 MB  /System/Library/…", FG)
    blank()

    # assistant response
    line("(◉_◉)  Dross", FG_DIM)
    line(
        "I am Dross, the most valuable mind-spirit in the world. Your top",
        ASSIST_FG,
    )
    line(
        "CPU hogs are Ollama itself (we're using it) plus a 15 GB Python",
        ASSIST_FG,
    )
    line(
        "process in your Library. Want me to kill it? Just say the word.",
        ASSIST_FG,
    )
    blank()

    # user
    line("(◉_◉)  you", FG_DIM)
    line("do it — pid 37593, send TERM", USER_BLUE)
    blank()

    # tool
    line("🔧  kill_process({pid: 37593, signal: TERM})", DANGER)
    line("    💀 sent SIGTERM to pid 37593", DANGER)
    blank()

    # assistant
    line("(◉_◉)  Dross", FG_DIM)
    line(
        "Done. SIGTERM sent. Check with `processes(filter='python')` —",
        ASSIST_FG,
    )
    line("if it's still there, say the word and I'll fire SIGKILL.", ASSIST_FG)
    blank()

    # --- input row + footer (separated) ----------------------------------
    footer_y = TOTAL_H - FOOTER_H
    input_y = footer_y - CELL_H - 4
    d.rectangle([(CHAT_X, input_y), (TOTAL_W, footer_y - 2)], fill=SURFACE)
    d.text(
        (cx, input_y + 2),
        "  type a message — or / for commands…",
        font=_font(),
        fill=FG_MUTED,
    )

    # tiny footer hint line
    d.line([(0, footer_y), (TOTAL_W, footer_y)], fill=BORDER, width=1)
    d.text(
        (PADDING, footer_y + 4),
        "ctrl+l clear   ctrl+n new agent   ctrl+t next agent",
        font=_font(),
        fill=FG_MUTED,
    )

    return img


def main() -> int:
    out = Path(__file__).parent.parent / "docs" / "screenshot.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = render()
    img.save(out, "PNG", optimize=True)
    print(f"wrote {out}  ({out.stat().st_size:,} bytes, {img.size[0]}×{img.size[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
