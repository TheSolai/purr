# Changelog

All notable changes to **purr** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-09-04

### Added
- **Multi-tab concurrent chats.** `Ctrl+T` opens a new tab with the current
  agent + a fresh history file. `Ctrl+W` closes the current tab. `Ctrl+1..9`
  switches to tab N. Tab bar at the top of the chat shows the active tab in
  inverted pink, busy tabs with a ⏳ marker, and a `+` to hint at the new-tab
  action. Each tab persists independently to `~/.purr/chats/`. Busy state is
  per-tab so you can switch while a long response streams.
- **`@file` syntax** (a la aider/Continue). Type `@~/path/to/file.py` in
  the input and the file's contents are inlined into the message before
  sending, wrapped in a fenced code block with the right language hint
  (`@foo.py` → `python`, `@foo.rs` → `rust`, etc.). Supports absolute,
  `~`-relative, and `./`/`../` paths. Quoted paths for filenames with
  spaces: `@'~/my docs/notes.md'`. Email addresses (`user@host`) are
  protected by a negative lookbehind so they don't get mistakenly
  expanded. Hard cap 200 kB per file.
- **Edit-and-regenerate.** `Ctrl+R` regenerates the last assistant response
  by truncating history to before the last user message and re-sending.
  `Up` arrow in an empty input recalls the last user message (basic
  history of 50). `Ctrl+R` is a no-op while a response is streaming.
- **Token count + response time in the header.** Second status line shows
  `tab N/M · agent · last: 13.2s ~2,572 tok` after every model turn.
  Token estimate is `len(content) // 4` (rough but good enough for at-a-glance).
- **`/history [search]` and `/resume N`.** `/history` lists up to 20 past
  chat sessions from `~/.purr/chats/` (with full filter — works by
  agent name, message text, or session id), with message counts and
  timestamps. `/resume N` opens the Nth session from the most recent
  `/history` listing in a new tab.
- **10 new history tests** (`tests/test_history.py`) and **10 new attachment
  tests** (`tests/test_attachments.py`).
- Total tests: **150** (was 130). Live-verified `@file` end-to-end and
  multi-tab state.

## [0.1.3] — 2026-09-04

### Fixed
- **Tool-call hallucination detector.** When the assistant claims an action
  ("I have saved the file", "Done — installed the package", "I just downloaded
  the installer") but no tool was actually called this turn, purr now appends
  a warning bubble naming the matched phrase and suggesting a re-prompt. The
  matched patterns handle first-person + modifiers + contractions + base-form
  verbs, plus "Done — verb" and "Done: verb" variants. Narrative inside a
  story ("Midnight opened the box") does NOT trip the warning — only first-
  person or "Done —" claims do.
- **Universal honesty rule** appended to every persona's system prompt. Tells
  the model to never claim a side-effect ("saved", "sent", "killed") without a
  backing tool call, and to call the tool, not just describe the call.
- **`file_write` no longer prompts.** It was marked `dangerous=True` even
  though the README called it reversible — fixed. New files and rewrites now
  execute immediately, no modal. Overwrite targets are still recoverable
  (Finder, Time Machine).
- **`file_write` is robust to weird model output.** Now handles content as
  `list` of lines (joined with `\n`), `int`/`float`/`bool` (coerced via
  `str()`/`repr()`), `None` (friendly ❌ instead of TypeError), missing path
  (friendly ❌ instead of TypeError), permission errors (friendly ❌ instead
  of crash). Always ends the file with a newline (POSIX text-file convention).
- **Dross's catchphrase** "I have considered the alternative and rejected it."
  is no longer matched as a hallucination.

### Added
- **`/copy [last|N|all|selection]`** — copies chat text to the system
  clipboard. `last` (default) is the most recent assistant message; `N` is
  the Nth most recent; `all` is the whole chat as plain text; `selection`
  is whatever's selected in the TUI (when supported). macOS uses `pbcopy`,
  Linux tries `xclip`/`wl-copy`/`xsel`, Windows uses `clip`. Falls back to
  printing the text in a code block if no clipboard tool is found.
- **12 new `file_write` tests** (basic, trailing newline, list/int/bool/None
  content, missing path, parent dir creation, tilde expansion, permission
  errors) and **58 new claim-detector tests** (parametrized).
- Total tests: **130** (was 60).

## [0.1.2] — 2026-09-04

### Added
- **`examples/personas/`** — four copy-paste-and-customize starter personas:
  Researcher (citation-first deep dives), Coder (read-edit-test loops on real code),
  Triage (Desktop + Downloads cleanup), Writer (drafts + edits). Each is a plain JSON
  you can `cp` into `~/.purr/agents/` and tweak. See [`examples/README.md`](examples/README.md).
- **`docs/screenshot.png`** — PNG render of the TUI via Pillow + Menlo (no SVG→PNG
  conversion needed). 1056×744, regenerable with `make screenshot`. Companion to
  `docs/screenshot.svg` for cases where raster is preferred (GitHub social cards, etc).
- **`tests/test_streaming.py`** — 7 new tests with a real `http.server`-based mock
  Ollama on a random port. Exercises the full httpx streaming path, not just the
  parser. Covers text-only, tool calls, error status, empty streams, and `health()`.
- **`.pypirc.example`** — template for PyPI upload + a note on Trusted Publishers.
- **`make screenshot`** — regenerates both the SVG and PNG.
- **`Pillow>=10`** moved into the `[dev]` extras (only used by the screenshot script).
- **README** now points at the PNG screenshot and links the publish steps.

### Notes
- Total tests: **60** (was 53) — all green locally and on CI.
- `make publish-dryrun` builds a clean sdist + wheel (`purr-0.1.2-py3-none-any.whl` + `.tar.gz`).

## [0.1.1] — 2026-09-04

### Added
- **Web access (2 tools)**: `web_fetch` (URL → text, regex-based HTML stripping, 12k char cap) and `web_search` (DuckDuckGo Lite, no API key, redirects unwrapped). All non-Friend personas get both.
- **YOLO mode**: `/yolo on` → `/yolo confirm` opt-in toggle that pre-approves all dangerous tool calls and writes an append-only audit log to `~/.purr/logs/yolo-actions.log`. Two-step on, one-step off, never crashes the session on log errors. Header shows `⚠ YOLO` warning when on.
- **6 more tests** (web tools, DDG redirect unwrap, config round-trip on yolo_mode) → 53 total, all green.
- **CHANGELOG.md**, **CONTRIBUTING.md**, **Makefile**, **docs/screenshot.svg** (live TUI render).
- **GitHub Actions CI** for Python 3.11 / 3.12 / 3.13 on macOS.

## [0.1.0] — 2026-09-04

### Added
- Initial public release.
- **5 built-in personas**: Dross (default, the main man), Assistant, Friend (chat-only), Mac Planner, Sysadmin.
- **27 tools** across 4 groups:
  - **System** (6): `shell` (refuses `rm`/`sudo`/`dd`/`-rf`), `file_read`, `file_write`, `system_info`, `brew`, `macos_run`, `app_launcher`.
  - **Productivity** (3): `calendar`, `reminders`, `notes` (all AppleScript-driven, configurable safety).
  - **Files/Desktop** (12): `mkdir`, `list_dir`, `move_to`, `trash` (recoverable macOS Trash, not `rm`), `find_files`, `disk_usage`, `reveal_in_finder`, `desktop_summary`, `desktop_cleanup` (with `dry_run=True` preview), `open_url`, `download`, `install_app`.
  - **Activity monitor** (5): `app_status`, `processes` (sortable, filterable), `top_processes`, `process_info`, `kill_process` (DANGEROUS, refuses pid 0/1 and purr itself, defaults to TERM, supports KILL/HUP/INT).
- **Slash commands**: `/agent list|new|edit|rm|<name>`, `/model`, `/models`, `/tools`, `/role`, `/status`, `/whoami`, `/clear`, `/help`, `/quit`.
- **Keys**: `ctrl+n` new agent, `ctrl+t` cycle, `ctrl+l` clear, `ctrl+c` quit.
- **Streaming Markdown** with thinking/typing indicators + auto-scroll.
- **Safety modal** prompts the user for every dangerous tool call.
- **Role pill** in the header status bar (`[assistant]`, `[friend]`, `[planner]`, `[admin]`, `[general]`).
- **Auto-refreshing builtins** — bump `BUILTINS_VERSION` in `agents.py` to roll out changes to all users without clobbering their custom personas.
- **Plugin extension points** documented in README:
  - Add a tool: drop a function into `_register_*_tools()` in `src/purr/tools.py`.
  - Add a persona: JSON in `src/purr/agents_builtin/`, bump `BUILTINS_VERSION`.
  - Add a slash command: handler in `PurrApp._run_command()` in `src/purr/app.py`.
- **47 tests** (`pytest tests/`) covering tool registry, agent manager, config, paths.
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — tests on macOS, Python 3.11/3.12/3.13.
- **MIT license**.
- **Default model**: `llama3-groq-tool-use:8b` (purpose-built for tool calling). Configurable via `/model` or `~/.purr/config.toml`.

### Notes
- Purr is the user-facing shell for the OpenClaw / Dross agent system — Dross is the same persona across purr, OpenClaw, the Dross macOS app, and any other system that uses the OpenClaw soul.
- All chat / tool state lives locally in `~/.purr/`. No network calls, no telemetry, no API keys needed (Ollama is local).
