# Contributing to purr

Purr is a small, focused TUI. We welcome PRs — keep them tight.

## Quick start

```bash
git clone https://github.com/TheSolai/purr
cd purr
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/
```

That should print `47 passed` and exit.

## Pull request checklist

- [ ] Tests pass: `pytest tests/`
- [ ] New code has tests (if behavior is testable without a running Ollama server)
- [ ] No secrets, API keys, or user-specific paths in any file
- [ ] No new top-level dependencies without discussion (we try to keep the dep tree small)
- [ ] System prompt changes to a built-in persona include a `BUILTINS_VERSION` bump in `src/purr/agents.py`
- [ ] If you added a tool, added it to at least one persona's `tools: []` so it actually gets called

## Code style

- Black-compatible formatting (line length 100, 4-space indent).
- Type hints on all new public functions.
- Docstring every public function with a one-line summary.
- Tool descriptions (the `description=` field in `ToolSpec`) should be **3-4 short sentences max** — the LLM reads them.

## Architecture cheatsheet

```
src/purr/
  __main__.py       # python -m purr entry
  app.py            # Textual app: header, sidebar, chat, prompt, keybinds
  ascii_art.py      # logo + per-persona glyphs
  config.py         # ~/.purr/config.toml loader
  paths.py          # filesystem locations
  agents.py         # Agent dataclass + AgentManager
  ollama_client.py  # httpx async streaming chat
  history.py        # JSONL per-session chat history
  tools.py          # tool registry + 27 tools (split by registration fn)
  agents_builtin/   # 5 default personas (JSON)
tests/              # 47 tests, all run without Ollama
```

### Adding a tool

```python
# In src/purr/tools.py, inside one of the _register_*_tools() functions:
def my_tool(arg: str) -> str:
    """One-line description for the LLM."""
    return "result string"

TOOLS["my_tool"] = ToolSpec(
    name="my_tool",
    description="What this does (the LLM reads this)",
    fn=my_tool,
    dangerous=False,  # True if purr should prompt before running
    schema={
        "type": "function",
        "function": {
            "name": "my_tool",
            "description": "...",
            "parameters": {
                "type": "object",
                "properties": {"arg": {"type": "string"}},
                "required": ["arg"],
            },
        },
    },
)
```

Add the name to the relevant persona's `tools: []` in their JSON.

### Adding a persona

1. Add `src/purr/agents_builtin/<name>.json`
2. Add the name to `AgentManager.builtin_names()` in `src/purr/agents.py`
3. Bump `BUILTINS_VERSION` in `src/purr/agents.py`
4. Add the title to `Agent.title` in `src/purr/agents.py` (if you want a custom display name)
5. Add the glyph to `AGENT_GLYPHS` in `src/purr/ascii_art.py`
6. Add a category — must be one of `friend`, `assistant`, `planner`, `sysadmin`, `general`
7. Add a test in `tests/test_agents.py` if the persona is non-trivial

### Adding a slash command

In `PurrApp._run_command()` in `src/purr/app.py`:

```python
elif cmd == "/mycommand":
    self._do_mycommand()
```

Use `self._append_bubble("purr", text, "#cdd6f4")` to print output.

## License

By contributing, you agree your contributions are MIT-licensed.
