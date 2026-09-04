# Example personas for purr

These are starting points. Copy any of them to `~/.purr/agents/`, edit
the JSON, and you've got a custom agent — no Python required.

## Quick install

```bash
# Pick a persona and install it
cp examples/personas/researcher.json ~/.purr/agents/
cp examples/personas/coder.json      ~/.purr/agents/
cp examples/personas/triage.json     ~/.purr/agents/
cp examples/personas/writer.json     ~/.purr/agents/

# Launch purr and switch to one
purr
> /agent researcher
```

That's it. The persona shows up in `/agent list` and the header role pill
immediately. Switch back any time with `/agent dross`.

## What's included

| Persona     | Glyph      | Best for                                                   | Tools (highlights)                            |
|-------------|------------|------------------------------------------------------------|-----------------------------------------------|
| `researcher` | `(⌐■_■)`   | Deep dives with citations — papers, news, primary sources | `web_search`, `web_fetch`, `file_write`       |
| `coder`      | `(>‿◕)`   | Read-edit-test loops on real code                          | `shell`, `file_read/write`, `web_fetch`       |
| `triage`     | `(⌒_⌒)`   | Inbox-zero for Desktop + Downloads                         | `desktop_summary`, `trash`, `move_to`         |
| `writer`     | `(✎_✎)`   | Drafts, edits, proofreads — emails, READMEs, commits       | `file_read/write`, `web_fetch`                |

## Anatomy of a persona

```jsonc
{
  "__builtins_version": 0,         // 0 = user file; builtins use 3+
  "name": "researcher",            // used by `/agent <name>`
  "role": "a deep-research …",    // one-liner shown in /agent list
  "glyph": "(⌐■_■)",               // shown next to the name in chat
  "builtin": false,                // marks the file as user-created
  "category": "general",           // drives the role pill: assistant/friend/planner/sysadmin/general
  "tools": [                       // whitelist of tool names this agent can call
    "web_fetch", "web_search", "file_read", "file_write"
  ],
  "temperature": 0.3,              // model temperature (null = inherit from config)
  "model": null,                   // override model (null = inherit from config)
  "system_prompt": "You are …"     // the agent's instructions
}
```

## Make your own

1. Copy the closest existing one: `cp examples/personas/researcher.json ~/.purr/agents/myagent.json`
2. Edit `name`, `role`, `glyph`, `tools`, and `system_prompt`.
3. Set `__builtins_version: 0` and `builtin: false`.
4. In purr: `/agent myagent` to load it. `/agent edit myagent` opens it in `$EDITOR`.

The full tool list is shown by `/tools` in the TUI. Tool names are
case-sensitive and must match exactly.

## Persona design tips

- **Start with the goal, not the tools.** Decide what the agent is *for*,
  then pick the 3-6 tools it actually needs. A long `tools` list makes
  weak models flounder.
- **Keep system prompts tight.** 200-400 words. Tell the agent its
  workflow, its rules, and what to do when unsure. Avoid philosophy.
- **Use the `category`** — it drives the header pill (`[assistant]`,
  `[planner]`, etc.) and the `/role` summary.
- **Test on a real task.** If the agent can't do the thing you designed
  it for after 3-4 prompts, the system prompt needs work, not the tools.
