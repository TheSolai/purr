"""@file syntax — inline file attachments in user messages.

The user types `@~/path/to/file.py` in the input. When the message is sent,
each `@<path>` token is replaced with the file's contents wrapped in a fenced
markdown block. If the path doesn't exist, the user gets a clear error.

Multiple attachments in one message are fine:
    "compare @~/foo.py and @~/bar.py"
→ expands to
    "compare
     ```/Users/me/foo.py
     <contents of foo.py>
     ```
     and
     ```/Users/me/bar.py
     <contents of bar.py>
     ```"

Paths may be quoted with single or double quotes if they contain spaces:
    "@'~/my docs/notes.md'"
"""
from __future__ import annotations

import re
from pathlib import Path


# Match @ followed by a path. Stops at whitespace, end of string, or a quote.
# Supports:
#   @/abs/path
#   @~/rel/path
#   @./rel
#   @../rel
#   @'path with spaces'  /  @"path with spaces"
#
# The negative lookbehind avoids matching emails like `user@example.com` —
# an @ that's preceded by an alphanumeric character is part of an email,
# not a file reference.
_ATTACH_RE = re.compile(
    r"""(?<![A-Za-z0-9._%+-])    # not preceded by email-y chars
    @                             # the @
    (?:                           # path body
        '([^']+)'                 #   single-quoted (group 1)
      | "([^"]+)"                 #   double-quoted (group 2)
      | (\S+)                     #   bare token (group 3) — no whitespace
    )""",
    flags=re.UNICODE | re.VERBOSE,
)

# Cap per-file size to keep the prompt sane. 200kB is roughly 50k tokens.
_MAX_FILE_BYTES = 200_000


class AttachmentError(ValueError):
    """Raised when an @file path can't be resolved or read."""


def expand_attachments(text: str, *, base_dir: str | None = None) -> str:
    """Replace every @<path> in `text` with the file's contents.

    Returns the rewritten message. Raises AttachmentError with the first
    bad path on failure (so the TUI can show a clean ❌ instead of
    silently dropping the attachment).
    """
    if "@" not in text:
        return text  # fast path — no work to do
    base = Path(base_dir) if base_dir else None

    def _repl(m: re.Match[str]) -> str:
        raw = m.group(1) or m.group(2) or m.group(3) or ""
        try:
            p = Path(raw).expanduser()
            if base and not p.is_absolute():
                p = (base / p).resolve()
            if not p.exists():
                raise AttachmentError(f"@{raw}: file not found: {p}")
            if p.is_dir():
                raise AttachmentError(f"@{raw}: is a directory, not a file: {p}")
            size = p.stat().st_size
            if size > _MAX_FILE_BYTES:
                raise AttachmentError(
                    f"@{raw}: file too large ({size:,} bytes, max {_MAX_FILE_BYTES:,})"
                )
            contents = p.read_text(encoding="utf-8", errors="replace")
        except AttachmentError:
            raise
        except Exception as e:
            raise AttachmentError(f"@{raw}: {e}") from e
        return (
            f"\n```{_lang_from_path(p)}\n# {p}\n{contents}\n```\n"
        )

    try:
        return _ATTACH_RE.sub(_repl, text)
    except AttachmentError:
        raise
    except Exception as e:  # safety net
        raise AttachmentError(str(e)) from e


_LANG_HINTS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".rs": "rust",
    ".swift": "swift",
    ".go": "go",
    ".sh": "bash",
    ".zsh": "bash",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".rb": "ruby",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
}


def _lang_from_path(p: Path) -> str:
    return _LANG_HINTS.get(p.suffix.lower(), "")
