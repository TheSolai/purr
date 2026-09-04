"""The purr ASCII logo and per-agent glyphs.

Kept dependency-free so we can show the logo from anywhere (TUI splash, errors, --version).
"""
from __future__ import annotations

# Box-drawing cat. ~22 lines tall, fits in most terminals.
PURR_LOGO_LINES: list[str] = [
    r"      /\_____/\      ",
    r"     /  o   o  \     ",
    r"    ( ==  ^  == )    ",
    r"     )         (     ",
    r"    (   )   (   )    ",
    r"   (__(___)_(___)__) ",
]

# A "neko arc" variant (shorter, one line) for status bars / corners.
PURR_GLYPH_SMALL = "(=^.^=)"

# Big wordmark — "purr" in a chunky ASCII font.
PURR_WORDMARK: list[str] = [
    r"  ____  _   _  ____  ____  ",
    r" |  _ \| | | ||  _ \|  _ \ ",
    r" | |_) | | | || |_) | | | |",
    r" |  __/| |_| ||  _ <| |_| |",
    r" |_|    \___/ |_| \_\____/ ",
]

PURR_FULL_LOGO: list[str] = [
    r"      /\_____/\        ____  _   _  ____  ____  ",
    r"     /  o   o  \      |  _ \| | | ||  _ \|  _ \ ",
    r"    ( ==  ^  == )     | |_) | | | || |_) | | | |",
    r"     )         (      |  __/| |_| ||  _ <| |_| |",
    r"    (   )   (   )     |_|    \___/ |_| \_\____/ ",
    r"   (__(___)_(___)__)  ",
]

# Per-persona ASCII icon. One line, used in chat bubbles + sidebar.
AGENT_GLYPHS: dict[str, str] = {
    "dross":     "(◉_◉)",   # single-eye mind-spirit, observing
    "assistant": "(=^.^=)",
    "friend":    "(♥.♥)",
    "planner":   "(☼.☼)",
    "sysadmin":  "(>_>)",
}

AGENT_TITLES: dict[str, str] = {
    "dross":     "Dross",
    "assistant": "Assistant",
    "friend":    "Friend",
    "planner":   "Mac Planner",
    "sysadmin":  "Sysadmin",
}


def agent_glyph(name: str) -> str:
    return AGENT_GLYPHS.get(name, "(•_•)")


def agent_title(name: str) -> str:
    return AGENT_TITLES.get(name, name.title())
