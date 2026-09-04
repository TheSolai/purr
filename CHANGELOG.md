# Changelog

All notable changes to **purr** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project adheres to
[Semantic Versioning](https://semver.org/).

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
