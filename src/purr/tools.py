"""Tool registry for purr agents.

Each tool is a function (callable) that takes keyword args and returns a string
(the result that gets appended to the chat as a 'tool' role message).

Tools are grouped by name and exposed to the Ollama `/api/chat` `tools` field as
JSON-schema function definitions. The agent loop detects tool calls in the
model's response, executes them, and feeds the result back to the model.
"""
from __future__ import annotations

import os
import platform
import shlex
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# ---- safety
DANGEROUS_PREFIXES = (
    "rm ", "rm\t", "sudo ", "shutdown", "reboot", "halt",
    "mkfs", "dd ", "chmod -R 777", "chown -R",
    "curl ", "wget ",  # network exfil
    "mv /", "cp /",
    "pkill -9 -f",
    "kill -9 1", "killall",
    ":(){:|:&};:",  # fork bomb
)


def is_dangerous(cmd: str) -> bool:
    s = cmd.lstrip()
    return any(s.startswith(p) for p in DANGEROUS_PREFIXES) or " -rf " in s


# ---- core tool functions --------------------------------------------------

def shell(command: str, cwd: str | None = None, timeout: int = 30) -> str:
    """Run a shell command. Returns combined stdout+stderr, truncated."""
    if is_dangerous(command):
        return f"🛑  refused: command looks dangerous. Get user approval first."
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"⏱  timed out after {timeout}s"
    out = (result.stdout or "") + (("" if not result.stderr else "\n" + result.stderr) if result.stderr else "")
    out = out.strip()
    if len(out) > 4000:
        out = out[:4000] + f"\n…(truncated, {len(out)} chars total)"
    if result.returncode != 0:
        out = f"[exit {result.returncode}]\n{out}"
    return out or "(no output)"


def file_read(path: str, max_bytes: int = 20_000) -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"❌ not found: {path}"
        if p.is_dir():
            return "\n".join(sorted(os.listdir(p))[:200]) or "(empty dir)"
        data = p.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return f"(binary file, {len(data)} bytes)"
    except Exception as e:
        return f"❌ {e}"


def file_write(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"✅ wrote {len(content)} bytes to {p}"


def system_info() -> str:
    return (
        f"os={platform.system()} {platform.release()} ({platform.machine()})\n"
        f"python={platform.python_version()}\n"
        f"cwd={os.getcwd()}\n"
        f"user={os.environ.get('USER', '?')}\n"
        f"shell={os.environ.get('SHELL', '?')}\n"
    )


def brew(action: str, package: str | None = None) -> str:
    """Run `brew <action> [package]`. action ∈ {list, info, install, search}."""
    if action not in {"list", "info", "install", "search", "update", "outdated", "doctor"}:
        return f"❌ unknown brew action: {action}"
    cmd = ["brew", action]
    if package:
        cmd.append(package)
    if action in {"install", "update"}:
        return f"🛑  brew {action} is a system change — confirm with user before running"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return ((r.stdout or "") + (r.stderr or "")).strip()[:4000] or "(no output)"
    except Exception as e:
        return f"❌ {e}"


# ---- macOS / AppleScript --------------------------------------------------

def macos_run(script: str, timeout: int = 20) -> str:
    """Run an arbitrary AppleScript via osascript. Returns stdout."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        out = out.strip()
        if r.returncode != 0 and not out:
            out = f"exit {r.returncode}"
        return out[:4000] or "(no output)"
    except subprocess.TimeoutExpired:
        return f"⏱  osascript timed out after {timeout}s"
    except FileNotFoundError:
        return "❌ osascript not found (not macOS?)"
    except Exception as e:
        return f"❌ {e}"


def calendar(action: str, title: str | None = None, when: str | None = None,
             duration_minutes: int = 60) -> str:
    """Quick Calendar helpers via AppleScript.

    action ∈ {today, list_calendars, add, open}.
    'when' is a free-form date string, parsed by AppleScript's «date» class via shell.
    """
    if action == "today":
        return macos_run("""
            set out to ""
            set today to current date
            set startOfDay to today - (time of today)
            set endOfDay to startOfDay + 86400
            set calLimit to 6
            set calSeen to 0
            tell application "Calendar"
                set calCount to 0
                set calList to calendars
                set calsTotal to (count of calList)
                if calsTotal < 1 then return "no calendars"
                set calsToCheck to calLimit
                if calsTotal < calLimit then set calsToCheck to calsTotal
                repeat with i from 1 to calsToCheck
                    set c to item i of calList
                    set evs to (every event of c whose start date ≥ startOfDay and start date < endOfDay)
                    if (count of evs) > 0 then
                        set calCount to calCount + 1
                        set out to out & "📅 " & (name of c) & linefeed
                        repeat with e in evs
                            set ts to (start date of e)
                            set hh to (hours of ts as string)
                            if (length of hh) < 2 then set hh to "0" & hh
                            set mm to (minutes of ts as string)
                            if (length of mm) < 2 then set mm to "0" & mm
                            set out to out & "  " & hh & ":" & mm & "  " & (summary of e) & linefeed
                        end repeat
                    end if
                end repeat
                if calsTotal > calLimit then
                    set out to out & "(checked first " & calLimit & " of " & calsTotal & " calendars)"
                end if
                if calCount = 0 then
                    return "no events today"
                end if
            end tell
            return out
        """, timeout=60)
    if action == "list_calendars":
        return macos_run('tell application "Calendar" to return name of every calendar')
    if action == "add":
        if not title or not when:
            return "❌ need title and when"
        # Build a script that creates a one-hour event 1 minute from now as a safe fallback,
        # unless 'when' is a parseable date.
        script = f'''
            set theDate to date "{when}"
            set theCal to first calendar whose name is "Calendar"
            tell application "Calendar"
                tell theCal
                    set newEvent to make new event with properties {{summary:"{title}", start date:theDate, end date:theDate + {duration_minutes} * 60}}
                end tell
            end tell
            return "added '{title}' on " & (theDate as string)
        '''
        return macos_run(script)
    if action == "open":
        return macos_run('tell application "Calendar" to activate')
    return f"❌ unknown calendar action: {action}"


def reminders(action: str, title: str | None = None, due: str | None = None,
              list_name: str = "Reminders") -> str:
    """Reminders via AppleScript. action ∈ {list, add, complete, open}."""
    if action == "open":
        return macos_run('tell application "Reminders" to activate')
    if action == "list":
        return macos_run(f'''
            tell application "Reminders"
                set out to ""
                repeat with l in lists
                    if name of l is "{list_name}" then
                        set out to out & "📝 " & (name of l) & linefeed
                        repeat with r in (reminders of l)
                            if not (completed of r) then
                                set out to out & "  • " & (name of r)
                                try
                                    if due date of r is not missing value then
                                        set out to out & "  (due " & ((due date of r) as string) & ")"
                                    end if
                                end try
                                set out to out & linefeed
                            end if
                        end repeat
                    end if
                end repeat
                if out is "" then return "no active reminders"
                return out
            end tell
        ''')
    if action == "add":
        if not title:
            return "❌ need a title"
        if due:
            script = f'''
                tell application "Reminders"
                    set theList to list "{list_name}"
                    set theDate to date "{due}"
                    tell theList
                        make new reminder with properties {{name:"{title}", due date:theDate}}
                    end tell
                    return "added '{title}' to {list_name} (due {due})"
                end tell
            '''
        else:
            script = f'''
                tell application "Reminders"
                    set theList to list "{list_name}"
                    tell theList
                        make new reminder with properties {{name:"{title}"}}
                    end tell
                    return "added '{title}' to {list_name}"
                end tell
            '''
        return macos_run(script)
    if action == "complete":
        if not title:
            return "❌ need title (substring match)"
        return macos_run(f'''
            tell application "Reminders"
                set theList to list "{list_name}"
                set out to ""
                repeat with r in (reminders of theList)
                    if (name of r) contains "{title}" and not (completed of r) then
                        set completed of r to true
                        set out to out & "✅ " & (name of r) & linefeed
                    end if
                end repeat
                if out is "" then return "no matching active reminder"
                return out
            end tell
        ''')
    return f"❌ unknown reminders action: {action}"


def notes(action: str, title: str | None = None, body: str | None = None,
          folder: str = "Notes") -> str:
    """Apple Notes via AppleScript. action ∈ {list, add, open}."""
    if action == "open":
        return macos_run('tell application "Notes" to activate')
    if action == "list":
        return macos_run('tell application "Notes" to return name of every note')
    if action == "add":
        if not title:
            return "❌ need a title"
        body_escaped = (body or "").replace('"', '\\"').replace("\n", "\\n")
        return macos_run(f'''
            tell application "Notes"
                tell default folder
                    make new note with properties {{name:"{title}", body:"{body_escaped}"}}
                end tell
            end tell
            return "✅ added note '{title}'"
        ''')
    return f"❌ unknown notes action: {action}"


def app_launcher(app: str) -> str:
    """Open an app by name (or path)."""
    try:
        subprocess.run(["open", "-a", app], check=False, timeout=10)
        return f"🚀 launched '{app}'"
    except Exception as e:
        return f"❌ {e}"


# ---- file / desktop / download helpers -------------------------------------

def _human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.1f} {u}" if u != "B" else f"{int(f)} {u}"
        f /= 1024
    return f"{f:.1f} TB"


def _format_age(secs: float) -> str:
    if secs < 60: return f"{int(secs)}s"
    if secs < 3600: return f"{int(secs/60)}m"
    if secs < 86400: return f"{int(secs/3600)}h"
    if secs < 86400*30: return f"{int(secs/86400)}d"
    if secs < 86400*365: return f"{int(secs/(86400*30))}mo"
    return f"{int(secs/(86400*365))}y"


# Maps a file extension to a friendly category for desktop cleanup.
EXT_CATEGORY: dict[str, str] = {
    # Documents
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents",
    ".txt": "Documents", ".rtf": "Documents", ".md": "Documents",
    ".pages": "Documents", ".numbers": "Documents", ".key": "Documents",
    ".csv": "Documents", ".xls": "Documents", ".xlsx": "Documents",
    ".ppt": "Documents", ".pptx": "Documents",
    # Images
    ".png": "Images", ".jpg": "Images", ".jpeg": "Images", ".gif": "Images",
    ".webp": "Images", ".heic": "Images", ".tiff": "Images", ".bmp": "Images",
    ".svg": "Images", ".ico": "Images", ".raw": "Images",
    # Videos
    ".mp4": "Videos", ".mov": "Videos", ".mkv": "Videos", ".avi": "Videos",
    ".webm": "Videos", ".m4v": "Videos", ".wmv": "Videos",
    # Audio
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio", ".aac": "Audio",
    ".m4a": "Audio", ".ogg": "Audio", ".opus": "Audio",
    # Archives
    ".zip": "Archives", ".tar": "Archives", ".gz": "Archives",
    ".bz2": "Archives", ".7z": "Archives", ".rar": "Archives",
    ".dmg": "Installers", ".iso": "Installers", ".pkg": "Installers",
    # Code / config
    ".py": "Code", ".js": "Code", ".ts": "Code", ".tsx": "Code", ".jsx": "Code",
    ".rs": "Code", ".go": "Code", ".java": "Code", ".c": "Code", ".cpp": "Code",
    ".h": "Code", ".hpp": "Code", ".swift": "Code", ".kt": "Code",
    ".json": "Code", ".yaml": "Code", ".yml": "Code", ".toml": "Code",
    ".html": "Code", ".css": "Code", ".scss": "Code",
    ".sh": "Code", ".zsh": "Code", ".bash": "Code",
    # Fonts
    ".ttf": "Fonts", ".otf": "Fonts", ".woff": "Fonts", ".woff2": "Fonts",
}


def _categorize(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in EXT_CATEGORY:
        return EXT_CATEGORY[ext]
    return "Other"


def mkdir(path: str) -> str:
    """Create a directory (and any missing parents). Idempotent."""
    p = Path(path).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
        return f"✅ created {p}"
    except Exception as e:
        return f"❌ {e}"


def list_dir(path: str, sort_by: str = "name", limit: int = 200) -> str:
    """List a directory with sizes and mtimes. sort_by ∈ {name, mtime, size}."""
    p = Path(path).expanduser()
    if not p.exists():
        return f"❌ not found: {path}"
    if not p.is_dir():
        return f"❌ not a directory: {path}"
    try:
        entries = list(p.iterdir())
    except PermissionError:
        return f"❌ permission denied: {path}"
    # sort
    if sort_by == "mtime":
        entries.sort(key=lambda e: e.stat().st_mtime if e.exists() else 0, reverse=True)
    elif sort_by == "size":
        def _sz(e: Path) -> int:
            try:
                return e.stat().st_size if e.is_file() else 0
            except OSError:
                return 0
        entries.sort(key=_sz, reverse=True)
    else:
        entries.sort(key=lambda e: e.name.lower())

    now = time.time()
    lines = [f"📁 {p}  ({len(entries)} entries)"]
    for e in entries[:limit]:
        try:
            st = e.stat()
            if e.is_dir():
                kind = "📂"
                size = "—"
            else:
                kind = "📄"
                size = _human_size(st.st_size)
            age = _format_age(now - st.st_mtime)
            hidden = "·" if e.name.startswith(".") else " "
            lines.append(f"  {kind}{hidden}{e.name:40s} {size:>10s}  {age} ago")
        except OSError:
            continue
    if len(entries) > limit:
        lines.append(f"  …({len(entries) - limit} more)")
    return "\n".join(lines)


def move_to(src_paths: list[str], dst_dir: str, create_dst: bool = True) -> str:
    """Move one or more files into dst_dir. Auto-creates dst if needed."""
    if not src_paths:
        return "❌ no src paths"
    dst = Path(dst_dir).expanduser()
    if create_dst:
        dst.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for raw in src_paths:
        src = Path(raw).expanduser()
        if not src.exists():
            errors.append(f"missing: {src}")
            continue
        target = dst / src.name
        # if collision, append index
        if target.exists():
            stem, suf = src.stem, src.suffix
            for i in range(1, 1000):
                candidate = dst / f"{stem} ({i}){suf}"
                if not candidate.exists():
                    target = candidate
                    break
        try:
            src.rename(target)
            moved.append(str(target))
        except Exception as e:
            # fall back to copy+delete (cross-volume)
            try:
                import shutil
                shutil.move(str(src), str(target))
                moved.append(str(target))
            except Exception as e2:
                errors.append(f"{src}: {e2}")
    out = []
    if moved: out.append(f"✅ moved {len(moved)} item(s) to {dst}")
    for m in moved[:10]: out.append(f"   • {m}")
    if len(moved) > 10: out.append(f"   …({len(moved) - 10} more)")
    if skipped: out.append(f"⚠ skipped: {len(skipped)}")
    if errors: out.append(f"❌ errors: {len(errors)}")
    for e in errors[:5]: out.append(f"   • {e}")
    return "\n".join(out) if out else "(nothing moved)"


def trash(paths: list[str]) -> str:
    """Move files to the Trash (recoverable). Uses Finder on macOS."""
    if not paths:
        return "❌ no paths"
    results: list[str] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.exists():
            results.append(f"⚠ not found: {p}")
            continue
        # macOS: tell Finder to delete (sends to Trash, recoverable)
        if platform.system() == "Darwin":
            script = f'tell application "Finder" to delete POSIX file "{p}"'
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                results.append(f"🗑  trashed {p}")
            else:
                results.append(f"❌ {p}: {r.stderr.strip() or 'osascript failed'}")
        else:
            # POSIX fallback — just rm (no Trash on most systems)
            try:
                p.unlink()
                results.append(f"🗑  deleted {p}")
            except Exception as e:
                results.append(f"❌ {p}: {e}")
    return "\n".join(results)


def desktop_summary(desktop: str = "~/Desktop") -> str:
    """What's on the user's Desktop right now — by category, size, age."""
    p = Path(desktop).expanduser()
    if not p.exists():
        return f"❌ no Desktop at {p}"
    now = time.time()
    by_cat: dict[str, list[tuple[Path, int, float]]] = {}
    total = 0
    total_size = 0
    for entry in p.iterdir():
        if entry.name.startswith("."):  # skip .DS_Store etc
            continue
        try:
            if entry.is_dir():
                # count files inside
                n = sum(1 for _ in entry.rglob("*") if _.is_file())
                size = sum(_.stat().st_size for _ in entry.rglob("*") if _.is_file())
                cat = "Folders"
                mtime = entry.stat().st_mtime
                by_cat.setdefault(cat, []).append((entry, size, mtime))
                total += 1
                total_size += size
            else:
                st = entry.stat()
                cat = _categorize(entry)
                by_cat.setdefault(cat, []).append((entry, st.st_size, st.st_mtime))
                total += 1
                total_size += st.st_size
        except OSError:
            continue
    lines = [f"🖥  {p} — {total} items, {_human_size(total_size)} total"]
    for cat in sorted(by_cat):
        items = by_cat[cat]
        cat_size = sum(s for _, s, _ in items)
        lines.append(f"\n  {cat}  ({len(items)} item{'s' if len(items)!=1 else ''}, {_human_size(cat_size)})")
        items.sort(key=lambda t: t[1], reverse=True)
        for entry, size, mtime in items[:6]:
            try:
                age = _format_age(now - mtime)
                kind = "📂" if entry.is_dir() else "📄"
                lines.append(f"    {kind} {entry.name:40s} {_human_size(size) if size else '—':>10s}  {age} ago")
            except OSError:
                continue
        if len(items) > 6:
            lines.append(f"    …({len(items) - 6} more)")
    return "\n".join(lines)


def desktop_cleanup(desktop: str = "~/Desktop",
                   categories: list[str] | None = None,
                   dry_run: bool = True) -> str:
    """Sort files on the Desktop into category subfolders. dry_run=True is the default."""
    p = Path(desktop).expanduser()
    if not p.exists():
        return f"❌ no Desktop at {p}"
    cats = set(categories) if categories else {
        "Documents", "Images", "Videos", "Audio",
        "Archives", "Installers", "Code", "Fonts", "Other",
    }
    moves: list[tuple[Path, Path]] = []
    for entry in p.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            continue
        cat = _categorize(entry)
        if cat not in cats:
            cat = "Other"
        target_dir = p / cat
        target = target_dir / entry.name
        if target.exists():
            stem, suf = entry.stem, entry.suffix
            for i in range(1, 1000):
                cand = target_dir / f"{stem} ({i}){suf}"
                if not cand.exists():
                    target = cand
                    break
        moves.append((entry, target))

    if not moves:
        return f"🖥  {p} is already clean — nothing to sort."

    if dry_run:
        lines = [f"🖥  dry-run: would move {len(moves)} file(s) on {p}"]
        by_cat: dict[str, int] = {}
        for src, dst in moves:
            by_cat[dst.parent.name] = by_cat.get(dst.parent.name, 0) + 1
        for cat, n in sorted(by_cat.items()):
            lines.append(f"   • {n:3d} → {cat}/")
        lines.append("\n(no files moved — re-run with dry_run=False to do it)")
        return "\n".join(lines)

    # actually do it
    by_cat: dict[str, int] = {}
    errors: list[str] = []
    for src, dst in moves:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            by_cat[dst.parent.name] = by_cat.get(dst.parent.name, 0) + 1
        except OSError:
            try:
                import shutil
                shutil.move(str(src), str(dst))
                by_cat[dst.parent.name] = by_cat.get(dst.parent.name, 0) + 1
            except Exception as e:
                errors.append(f"{src}: {e}")
    lines = [f"🖥  sorted {sum(by_cat.values())} file(s) on {p}"]
    for cat, n in sorted(by_cat.items()):
        lines.append(f"   • {n:3d} → {cat}/")
    if errors:
        lines.append(f"❌ {len(errors)} error(s)")
        for e in errors[:5]:
            lines.append(f"   • {e}")
    return "\n".join(lines)


def open_url(url: str) -> str:
    """Open a URL in the user's default browser."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https", "ftp", "file"}:
        return f"❌ refused: scheme '{parsed.scheme}' is not allowed"
    try:
        subprocess.run(["open", url], check=False, timeout=10)
        return f"🌐 opened {url}"
    except Exception as e:
        return f"❌ {e}"


def download(url: str, dest_dir: str = "~/Downloads", filename: str | None = None,
             timeout: int = 120) -> str:
    """Download a file from a URL to dest_dir. Returns the local path."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https", "ftp"}:
        return f"❌ refused: scheme '{parsed.scheme}' is not allowed"
    d = Path(dest_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    if not filename:
        # try to extract from URL, fall back to last path component
        name = os.path.basename(parsed.path) or "download"
        # strip query params that snuck in
        name = name.split("?")[0].split("#")[0] or "download"
        filename = name
    target = d / filename
    if target.exists():
        stem, suf = target.stem, target.suffix
        for i in range(1, 1000):
            cand = d / f"{stem} ({i}){suf}"
            if not cand.exists():
                target = cand
                break
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "purr/0.1 (+ollama local assistant)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(target, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            chunk = 64 * 1024
            read = 0
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                read += len(buf)
        size = target.stat().st_size
        return f"✅ downloaded {target}  ({_human_size(size)})"
    except Exception as e:
        try:
            if target.exists():
                target.unlink()
        except Exception:
            pass
        return f"❌ download failed: {e}"


def install_app(source: str) -> str:
    """Open a .dmg/.pkg (mounts dmg, opens installer window). Source = local path or URL."""
    # if URL, download first
    if source.startswith(("http://", "https://", "ftp://")):
        result = download(source)
        if result.startswith("❌"):
            return result
        # extract local path from the "✅ downloaded ..." line
        try:
            local = result.split(" ", 2)[2]
        except Exception:
            return f"❌ couldn't parse downloaded path from: {result}"
        source = local
    p = Path(source).expanduser()
    if not p.exists():
        return f"❌ not found: {p}"
    suf = p.suffix.lower()
    try:
        if suf == ".dmg":
            subprocess.run(["open", str(p)], check=False, timeout=15)
            return f"📦 mounted {p.name} — drag the .app to /Applications in the Finder window that just opened."
        if suf == ".pkg":
            subprocess.run(["open", str(p)], check=False, timeout=15)
            return f"📦 opened installer for {p.name} — follow the prompts."
        if suf == ".app":
            subprocess.run(["open", "-a", str(p)], check=False, timeout=15)
            return f"🚀 launched {p.name}"
        # unknown — try `open` anyway
        subprocess.run(["open", str(p)], check=False, timeout=15)
        return f"🚀 opened {p.name}"
    except Exception as e:
        return f"❌ {e}"


def find_files(name_pattern: str, root: str = "~", max_results: int = 200) -> str:
    """Find files by name substring (case-insensitive). Returns a list of paths."""
    r = Path(root).expanduser()
    if not r.exists():
        return f"❌ root not found: {root}"
    pat = name_pattern.lower()
    matches: list[Path] = []
    try:
        for p in r.rglob("*"):
            if pat in p.name.lower():
                matches.append(p)
                if len(matches) >= max_results:
                    break
    except (PermissionError, OSError):
        pass
    if not matches:
        return f"(no files matching '{name_pattern}' under {r})"
    lines = [f"🔎 {len(matches)} match(es) for '{name_pattern}' under {r}"]
    for m in matches[:50]:
        try:
            sz = _human_size(m.stat().st_size) if m.is_file() else "—"
        except OSError:
            sz = "—"
        lines.append(f"   {m}  ({sz})")
    if len(matches) > 50:
        lines.append(f"   …({len(matches) - 50} more)")
    return "\n".join(lines)


def disk_usage(path: str = "~", max_depth: int = 1) -> str:
    """Show disk usage of a path, recursively to max_depth (1 = top level only)."""
    p = Path(path).expanduser()
    if not p.exists():
        return f"❌ not found: {path}"
    try:
        out = subprocess.run(
            ["du", "-h", "-d", str(max(0, max_depth)), str(p)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return f"❌ du failed: {out.stderr.strip()}"
        # filter the path prefix duplication
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        return "\n".join(lines) or "(empty)"
    except subprocess.TimeoutExpired:
        return "⏱  du timed out after 60s"
    except Exception as e:
        return f"❌ {e}"


def reveal_in_finder(path: str) -> str:
    """Open Finder with the file/folder selected."""
    p = Path(path).expanduser()
    if not p.exists():
        return f"❌ not found: {path}"
    try:
        subprocess.run(["open", "-R", str(p)], check=False, timeout=10)
        return f"📂 revealed {p} in Finder"
    except Exception as e:
        return f"❌ {e}"


# ---- web access -----------------------------------------------------------

_USER_AGENT = "purr/0.1 (+ollama local assistant; +https://github.com/TheSolai/purr)"


def _strip_html(html: str) -> str:
    """Cheap HTML-to-text without external deps. Not perfect, but good enough
    for feeding clean prose to an LLM."""
    import re
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    html = re.sub(r"<(br|/p|/li|/tr|/div|h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = (
        html.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    lines = []
    for ln in html.splitlines():
        ln = " ".join(ln.split())
        if ln:
            lines.append(ln)
    return "\n".join(lines)


def web_fetch(url: str, max_chars: int = 12000, timeout: int = 20) -> str:
    """Fetch a URL and return the page as plain text. No API key, no JS.

    Returns up to `max_chars` characters (default 12k — enough for a full
    README or news article, will be truncated for very long pages).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"❌ refused: scheme '{parsed.scheme}' is not allowed"
    if not parsed.netloc:
        return f"❌ bad URL: no host"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html, text/plain, text/markdown;q=0.9, */*;q=0.5",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read()
            charset = "utf-8"
            if "charset=" in ctype:
                try:
                    charset = ctype.split("charset=", 1)[1].split(";")[0].strip()
                except Exception:
                    pass
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            final_url = resp.geturl()
            status = resp.status
    except Exception as e:
        return f"❌ fetch failed: {e}"
    if "html" in ctype.lower() or "<html" in text[:200].lower():
        body = _strip_html(text)
    else:
        body = text
    body = body.strip()
    if len(body) > max_chars:
        body = body[:max_chars] + f"\n\n…(truncated, full length {len(body)} chars)"
    return (
        f"📥 {final_url}  (HTTP {status}, {ctype.split(';')[0]})\n\n{body}"
    )


def web_search(query: str, max_results: int = 8, timeout: int = 15) -> str:
    """Search the web using DuckDuckGo's Lite endpoint. No API key needed.

    Uses `lite.duckduckgo.com` because the main HTML endpoint is heavily
    JavaScript-rendered and returns 14KB of shell to non-browser UAs.
    """
    q = (query or "").strip()
    if not q:
        return "❌ empty query"
    url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": q, "kl": "us-en"})
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"❌ search failed: {e}"
    import re
    from urllib.parse import parse_qs, urlparse, urlunparse

    def _unwrap_ddg(url: str) -> str:
        """DDG wraps every result in a redirect like //duckduckgo.com/l/?uddg=REAL&rut=...
        Extract the real destination."""
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

    rows: list[dict] = []
    # DDG Lite structure: each result has an <a href="DUCK_REDIRECT" class='result-link'>Title</a>
    # followed by a sibling <td class='result-snippet'>SNIPPET</td>.
    # Note: href comes BEFORE class in DDG Lite, and class uses single quotes.
    for m in re.finditer(
        r"<a[^>]+href=['\"](?P<url>[^'\"]+)['\"][^>]+class=['\"]result-link['\"][^>]*>(?P<title>.*?)</a>.*?"
        r"<td[^>]+class=['\"]result-snippet['\"][^>]*>(?P<snippet>.*?)</td>",
        text, flags=re.DOTALL,
    ):
        url = m.group("url")
        if "duckduckgo-help-pages" in url or "ads-by-microsoft" in url:
            continue
        rows.append({
            "title": _strip_html(m.group("title")).strip(),
            "url": _unwrap_ddg(url),
            "snippet": _strip_html(m.group("snippet")).strip()[:300],
        })
        if len(rows) >= max_results:
            break
    if not rows:
        for m in re.finditer(
            r"<a[^>]+href=['\"](?P<url>[^'\"]+)['\"][^>]+class=['\"]result-link['\"][^>]*>(?P<title>.*?)</a>",
            text, flags=re.DOTALL,
        ):
            url = m.group("url")
            if "duckduckgo-help-pages" in url or "ads-by-microsoft" in url:
                continue
            rows.append({
                "title": _strip_html(m.group("title")).strip(),
                "url": _unwrap_ddg(url),
                "snippet": "(no snippet)",
            })
            if len(rows) >= max_results:
                break
    if not rows:
        return f"🔎 no results for '{query}' (DuckDuckGo returned no parseable hits)"
    lines = [f"🔎 {len(rows)} result(s) for '{query}':"]
    for i, r in enumerate(rows, 1):
        lines.append(f"\n  {i}. {r['title']}")
        lines.append(f"     {r['url']}")
        if r['snippet'] and r['snippet'] != "(no snippet)":
            lines.append(f"     {r['snippet']}")
    return "\n".join(lines)


# ---- process / activity monitor --------------------------------------------

def _parse_ps_output(out: str) -> list[dict]:
    """Parse `ps -axo pid,pcpu,pmem,rss,comm,args` output into dicts."""
    rows: list[dict] = []
    lines = out.strip().splitlines()
    # header: PID %CPU %MEM RSS COMM ARGS
    for ln in lines[1:]:
        parts = ln.split(None, 5)
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[0])
            cpu = float(parts[1])
            mem_pct = float(parts[2])
            rss_kb = int(parts[3])
            comm = parts[4] if len(parts) > 4 else ""
            args = parts[5] if len(parts) > 5 else ""
            rows.append({
                "pid": pid,
                "cpu": cpu,
                "mem_pct": mem_pct,
                "rss_mb": rss_kb / 1024,
                "comm": comm,
                "args": args[:120],
            })
        except (ValueError, IndexError):
            continue
    return rows


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + ln for ln in text.splitlines())


def processes(sort_by: str = "cpu", limit: int = 20, filter: str | None = None) -> str:
    """List running processes. sort_by ∈ {cpu, mem, pid, name}."""
    sort_key = {"cpu": "cpu", "mem": "mem_pct", "pid": "pid", "name": "comm"}.get(sort_by, "cpu")
    try:
        r = subprocess.run(
            ["ps", "-axo", "pid,pcpu,pmem,rss,comm,args", "-r"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        return f"❌ ps failed: {e}"
    rows = _parse_ps_output(r.stdout)
    if filter:
        f = filter.lower()
        rows = [row for row in rows if f in row["comm"].lower() or f in row["args"].lower()]
    rows.sort(key=lambda r: r[sort_key], reverse=(sort_key != "pid"))
    rows = rows[:limit]
    if not rows:
        return "(no processes matched)"
    lines = [f"🧠 {len(rows)} process(es) (sorted by {sort_by})"]
    lines.append(f"  {'PID':>7s}  {'%CPU':>5s}  {'%MEM':>5s}  {'RSS':>8s}  COMMAND")
    for row in rows:
        comm = row["comm"][:50]
        lines.append(
            f"  {row['pid']:>7d}  {row['cpu']:>5.1f}  {row['mem_pct']:>5.1f}  "
            f"{row['rss_mb']:>6.0f} MB  {comm}"
        )
    return "\n".join(lines)


def top_processes(by: str = "cpu", n: int = 5) -> str:
    """Show the top-N processes by CPU or memory."""
    return processes(sort_by=by, limit=n)


def process_info(pid: int) -> str:
    """Detailed info on a single process."""
    if pid <= 0:
        return "❌ invalid pid"
    try:
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid,ppid,user,pcpu,pmem,rss,etime,stat,comm,args"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        return f"❌ ps failed: {e}"
    if r.returncode != 0 or not r.stdout.strip():
        return f"❌ no such process: pid {pid}"
    return r.stdout.strip()


def kill_process(pid: int, signal: str = "TERM") -> str:
    """Send a signal to a process. DANGEROUS — will ask for confirmation.

    signal ∈ {TERM, KILL, HUP, INT}.
    Defaults to TERM (graceful) — use KILL only if TERM doesn't work.
    """
    if pid <= 0:
        return "❌ invalid pid"
    if pid == os.getpid():
        return "🛑 refusing to kill my own process"
    sig = signal.upper()
    if sig not in {"TERM", "KILL", "HUP", "INT"}:
        return f"❌ unknown signal: {signal}"
    sig_arg = f"-{sig}"
    # Don't allow killing obvious system PIDs
    if pid in {0, 1}:
        return f"🛑 refusing to kill pid {pid} (kernel/init)"
    try:
        r = subprocess.run(["kill", sig_arg, str(pid)], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return f"💀 sent SIG{sig} to pid {pid}"
        return f"❌ kill failed: {r.stderr.strip() or 'unknown error'}"
    except Exception as e:
        return f"❌ {e}"


def app_status() -> str:
    """Quick activity overview — load avg, top 5 CPU, top 5 memory."""
    try:
        r1 = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5)
        r2 = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
    except Exception as e:
        return f"❌ {e}"
    lines = ["📊 Mac activity"]
    lines.append("  " + r1.stdout.strip())
    for ln in r2.stdout.splitlines():
        if any(k in ln for k in ("Pages free", "Pages active", "Pages inactive", "Pages wired", "Swap")):
            lines.append("  " + ln.strip())
    lines.append("")
    lines.append("  Top 5 by CPU:")
    lines.append(_indent(processes(sort_by="cpu", limit=5), "    "))
    lines.append("")
    lines.append("  Top 5 by memory:")
    lines.append(_indent(processes(sort_by="mem", limit=5), "    "))
    return "\n".join(lines)


# ---- registry & schemas --------------------------------------------------

@dataclass
class ToolSpec:
    name: str
    description: str
    fn: object
    schema: dict
    dangerous: bool = False


TOOLS: dict[str, ToolSpec] = {
    "shell": ToolSpec(
        name="shell",
        description="Run a shell command on the user's Mac. Returns stdout+stderr. Read-only and harmless commands are fine; purr will prompt before anything dangerous.",
        fn=shell,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Run a shell command. Returns combined output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to run."},
                        "cwd":     {"type": "string", "description": "Optional working directory."},
                        "timeout": {"type": "integer", "description": "Optional timeout in seconds (default 30)."},
                    },
                    "required": ["command"],
                },
            },
        },
    ),
    "file_read": ToolSpec(
        name="file_read",
        description="Read a file's contents (or list a directory).",
        fn=file_read,
        schema={
            "type": "function",
            "function": {
                "name": "file_read",
                "description": "Read text from a path, or list a directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
    ),
    "file_write": ToolSpec(
        name="file_write",
        description="Write a string to a file. Will prompt for confirmation.",
        fn=file_write,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "file_write",
                "description": "Write text to a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
    ),
    "system_info": ToolSpec(
        name="system_info",
        description="Get basic system info: OS, Python, cwd, user, shell.",
        fn=system_info,
        schema={
            "type": "function",
            "function": {
                "name": "system_info",
                "description": "Return system info as a string.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ),
    "brew": ToolSpec(
        name="brew",
        description="Homebrew helper. Read-only actions (list/info/search/doctor/outdated) are safe; install/update will prompt.",
        fn=brew,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "brew",
                "description": "Run a brew action.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action":  {"type": "string"},
                        "package": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
    ),
    "macos_run": ToolSpec(
        name="macos_run",
        description="Run an arbitrary AppleScript via osascript. Powerful — prompts for confirmation.",
        fn=macos_run,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "macos_run",
                "description": "Run an AppleScript string. Returns stdout/stderr.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script":  {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["script"],
                },
            },
        },
    ),
    "calendar": ToolSpec(
        name="calendar",
        description="Apple Calendar: list today's events, list calendars, add an event, open the app.",
        fn=calendar,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "calendar",
                "description": "Interact with the user's Apple Calendar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action":           {"type": "string"},
                        "title":            {"type": "string"},
                        "when":             {"type": "string"},
                        "duration_minutes": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
        },
    ),
    "reminders": ToolSpec(
        name="reminders",
        description="Apple Reminders: list, add, or complete reminders.",
        fn=reminders,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "reminders",
                "description": "Interact with the user's Reminders.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action":    {"type": "string"},
                        "title":     {"type": "string"},
                        "due":       {"type": "string"},
                        "list_name": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
    ),
    "notes": ToolSpec(
        name="notes",
        description="Apple Notes: list, add, or open notes.",
        fn=notes,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "notes",
                "description": "Interact with the user's Notes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "title":  {"type": "string"},
                        "body":   {"type": "string"},
                        "folder": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
    ),
    "app_launcher": ToolSpec(
        name="app_launcher",
        description="Open a macOS app by name.",
        fn=app_launcher,
        schema={
            "type": "function",
            "function": {
                "name": "app_launcher",
                "description": "Open a macOS application by name (e.g. 'Safari', 'Notes').",
                "parameters": {
                    "type": "object",
                    "properties": {"app": {"type": "string"}},
                    "required": ["app"],
                },
            },
        },
    ),
}


def specs_for(names: list[str]) -> list[ToolSpec]:
    return [TOOLS[n] for n in names if n in TOOLS]


def schemas_for(names: list[str]) -> list[dict]:
    return [TOOLS[n].schema for n in names if n in TOOLS]


def call(name: str, **kwargs) -> str:
    spec = TOOLS.get(name)
    if spec is None:
        return f"❌ unknown tool: {name}"
    try:
        return spec.fn(**kwargs)
    except Exception as e:
        return f"❌ tool {name} crashed: {e}"


def is_dangerous_tool(name: str) -> bool:
    return TOOLS.get(name, ToolSpec(name="", description="", fn=None, schema={})).dangerous


# ---- register the new tools in the registry --------------------------------

def _register_files_tools() -> None:
    TOOLS["mkdir"] = ToolSpec(
        name="mkdir",
        description="Create a directory (and any missing parents). Idempotent — safe to call on existing dirs.",
        fn=mkdir,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "mkdir",
                "description": "Create a directory at `path` (uses mkdir -p semantics). Path may be absolute or start with ~.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
    )
    TOOLS["list_dir"] = ToolSpec(
        name="list_dir",
        description="List a directory's contents with size and mtime. Read-only.",
        fn=list_dir,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List a directory. `sort_by` is one of 'name', 'mtime', 'size'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": "string"},
                        "sort_by": {"type": "string", "enum": ["name", "mtime", "size"]},
                        "limit":   {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
    )
    TOOLS["move_to"] = ToolSpec(
        name="move_to",
        description="Move one or more files into a destination directory. Will prompt for confirmation.",
        fn=move_to,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "move_to",
                "description": "Move files into `dst_dir`. On name collisions, an index is appended.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src_paths":  {"type": "array", "items": {"type": "string"}},
                        "dst_dir":     {"type": "string"},
                        "create_dst":  {"type": "boolean", "default": True},
                    },
                    "required": ["src_paths", "dst_dir"],
                },
            },
        },
    )
    TOOLS["trash"] = ToolSpec(
        name="trash",
        description="Send files to the Trash (recoverable from Finder). NOT a permanent delete.",
        fn=trash,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "trash",
                "description": "Move files to the macOS Trash via Finder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["paths"],
                },
            },
        },
    )
    TOOLS["desktop_summary"] = ToolSpec(
        name="desktop_summary",
        description="Summarize the user's Desktop: total count, size, files grouped by category (Documents, Images, etc). Read-only.",
        fn=desktop_summary,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "desktop_summary",
                "description": "Show what's on the Desktop right now.",
                "parameters": {
                    "type": "object",
                    "properties": {"desktop": {"type": "string", "default": "~/Desktop"}},
                },
            },
        },
    )
    TOOLS["desktop_cleanup"] = ToolSpec(
        name="desktop_cleanup",
        description="Sort files on the Desktop into category subfolders (Documents/, Images/, Videos/, etc). Default dry_run=True shows what would happen. Will prompt for confirmation when actually executing.",
        fn=desktop_cleanup,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "desktop_cleanup",
                "description": "Sort files on the Desktop into category folders. Always call with dry_run=True first to show the user what will happen, then dry_run=False after they confirm.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "desktop":    {"type": "string", "default": "~/Desktop"},
                        "categories": {"type": "array", "items": {"type": "string"}},
                        "dry_run":    {"type": "boolean", "default": True},
                    },
                },
            },
        },
    )
    TOOLS["open_url"] = ToolSpec(
        name="open_url",
        description="Open a URL in the user's default browser. http/https/ftp/file only.",
        fn=open_url,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "open_url",
                "description": "Open a URL in the user's default browser.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
    )
    TOOLS["download"] = ToolSpec(
        name="download",
        description="Download a file from a URL to the user's Downloads folder (or another dest_dir).",
        fn=download,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "download",
                "description": "Download a file to the user's machine.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url":      {"type": "string"},
                        "dest_dir": {"type": "string", "default": "~/Downloads"},
                        "filename": {"type": "string"},
                        "timeout":  {"type": "integer", "default": 120},
                    },
                    "required": ["url"],
                },
            },
        },
    )
    TOOLS["install_app"] = ToolSpec(
        name="install_app",
        description="Install a macOS app — accepts a local .dmg/.pkg/.app path or a URL. Mounts dmgs, opens installers. Will prompt for confirmation.",
        fn=install_app,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "install_app",
                "description": "Install a macOS app from a local path or URL. For .dmg, the user will be prompted to drag to /Applications in the Finder window that opens.",
                "parameters": {
                    "type": "object",
                    "properties": {"source": {"type": "string"}},
                    "required": ["source"],
                },
            },
        },
    )
    TOOLS["find_files"] = ToolSpec(
        name="find_files",
        description="Search for files by name substring (case-insensitive). Read-only.",
        fn=find_files,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "find_files",
                "description": "Search for files whose name contains `name_pattern`.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name_pattern": {"type": "string"},
                        "root":         {"type": "string", "default": "~"},
                        "max_results":  {"type": "integer", "default": 200},
                    },
                    "required": ["name_pattern"],
                },
            },
        },
    )
    TOOLS["disk_usage"] = ToolSpec(
        name="disk_usage",
        description="Show disk usage of a path, recursively. Read-only.",
        fn=disk_usage,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "disk_usage",
                "description": "Show disk usage of a path (uses `du -h -d max_depth`).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":      {"type": "string", "default": "~"},
                        "max_depth": {"type": "integer", "default": 1},
                    },
                },
            },
        },
    )
    TOOLS["reveal_in_finder"] = ToolSpec(
        name="reveal_in_finder",
        description="Open a Finder window with the file/folder selected.",
        fn=reveal_in_finder,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "reveal_in_finder",
                "description": "Reveal a file or folder in Finder.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
    )


_register_files_tools()


# ---- register the web tools -----------------------------------------------

def _register_web_tools() -> None:
    TOOLS["open_url"] = ToolSpec(
        name="open_url",
        description="Open a URL in the user's default browser. http/https/ftp/file only.",
        fn=open_url,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "open_url",
                "description": "Open a URL in the user's default browser. Use for sites that need JS rendering.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
    )
    TOOLS["download"] = ToolSpec(
        name="download",
        description="Download a file from a URL to ~/Downloads. Prompts before installing.",
        fn=download,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "download",
                "description": "Download a file via HTTP. Writes to dest_dir (default ~/Downloads).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url":      {"type": "string"},
                        "dest_dir": {"type": "string", "default": "~/Downloads"},
                        "filename": {"type": "string"},
                        "timeout":  {"type": "integer", "default": 120},
                    },
                    "required": ["url"],
                },
            },
        },
    )
    TOOLS["web_fetch"] = ToolSpec(
        name="web_fetch",
        description="Fetch a URL and return the page as plain text. No API key needed.",
        fn=web_fetch,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": "Fetch a URL and return its content as plain text. Use for reading docs, READMEs, articles, GitHub pages, etc. No JavaScript support — use open_url for JS-heavy sites.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url":        {"type": "string"},
                        "max_chars":  {"type": "integer", "default": 12000},
                        "timeout":    {"type": "integer", "default": 20},
                    },
                    "required": ["url"],
                },
            },
        },
    )
    TOOLS["web_search"] = ToolSpec(
        name="web_search",
        description="Search the web via DuckDuckGo. No API key needed. Returns titles, URLs, snippets.",
        fn=web_search,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web using DuckDuckGo's HTML endpoint. Returns up to `max_results` results with title, URL, and snippet. No API key required.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":       {"type": "string"},
                        "max_results": {"type": "integer", "default": 8},
                        "timeout":     {"type": "integer", "default": 15},
                    },
                    "required": ["query"],
                },
            },
        },
    )


_register_web_tools()


# ---- register the activity-monitor tools -----------------------------------

def _register_activity_tools() -> None:
    TOOLS["app_status"] = ToolSpec(
        name="app_status",
        description="Quick Mac activity overview: load average, memory pressure, top 5 processes by CPU and memory. Read-only.",
        fn=app_status,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "app_status",
                "description": "Show Mac activity: load, memory, top processes by CPU + memory.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    )
    TOOLS["processes"] = ToolSpec(
        name="processes",
        description="List running processes with PID, CPU%, memory%, RSS, command. Read-only.",
        fn=processes,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "processes",
                "description": "List running processes. `sort_by` is one of 'cpu', 'mem', 'pid', 'name'. `filter` is an optional case-insensitive substring match on command/args.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sort_by": {"type": "string", "enum": ["cpu", "mem", "pid", "name"]},
                        "limit":   {"type": "integer", "default": 20},
                        "filter":  {"type": "string"},
                    },
                },
            },
        },
    )
    TOOLS["top_processes"] = ToolSpec(
        name="top_processes",
        description="Top N processes by CPU or memory. Read-only.",
        fn=top_processes,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "top_processes",
                "description": "Show the top-N processes by cpu or mem.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "by": {"type": "string", "enum": ["cpu", "mem"]},
                        "n":  {"type": "integer", "default": 5},
                    },
                },
            },
        },
    )
    TOOLS["process_info"] = ToolSpec(
        name="process_info",
        description="Detailed info on a single process by pid (user, parent, cpu, mem, runtime, status, command). Read-only.",
        fn=process_info,
        dangerous=False,
        schema={
            "type": "function",
            "function": {
                "name": "process_info",
                "description": "Show detailed information about a process by its pid.",
                "parameters": {
                    "type": "object",
                    "properties": {"pid": {"type": "integer"}},
                    "required": ["pid"],
                },
            },
        },
    )
    TOOLS["kill_process"] = ToolSpec(
        name="kill_process",
        description="Send a signal to a process. DANGEROUS — will prompt for confirmation. Defaults to SIGTERM (graceful). Use SIGKILL only if TERM doesn't work. Refuses to kill pid 0/1 or purr itself.",
        fn=kill_process,
        dangerous=True,
        schema={
            "type": "function",
            "function": {
                "name": "kill_process",
                "description": "Send a Unix signal to a process. signal ∈ {TERM, KILL, HUP, INT}. Default TERM.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pid":    {"type": "integer"},
                        "signal": {"type": "string", "enum": ["TERM", "KILL", "HUP", "INT"], "default": "TERM"},
                    },
                    "required": ["pid"],
                },
            },
        },
    )


_register_activity_tools()
