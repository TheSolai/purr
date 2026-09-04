"""Agent manager.

An agent is a named persona: a system prompt + a tool scope + an icon.
Users can:
  - switch active agent  (`/agent <name>` or `/assistant`, `/friend`, …)
  - create a new agent  (`/agent new <name> <role>`)
  - list agents         (`/agent list`)
  - edit an agent       (`/agent edit <name>` → opens $EDITOR)
  - delete an agent     (`/agent rm <name>`)

Four built-in personas are seeded on first run:
  assistant  — witty general-purpose local-AI companion
  friend     — warm, no-tools, conversational
  planner    — Calendar / Reminders / Notes / todos
  sysadmin   — shell + file + system info, asks before risky ops
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from purr import paths


# Bump this when shipped builtins change meaningfully. The seeder will
# overwrite the user copy of any builtin whose on-disk version is older.
BUILTINS_VERSION = 4


@dataclass
class Agent:
    name: str
    role: str                 # short tagline
    glyph: str                # ASCII icon
    system_prompt: str
    tools: list[str] = field(default_factory=list)   # names of enabled tools
    temperature: float | None = None                # override default
    model: str | None = None                        # override default model
    builtin: bool = False
    category: str = "general"   # category: friend | assistant | planner | sysadmin | general

    @property
    def title(self) -> str:
        return {
            "dross":     "Dross",
            "assistant": "Assistant",
            "friend":    "Friend",
            "planner":   "Mac Planner",
            "sysadmin":  "Sysadmin",
        }.get(self.name, self.name.title())

    @property
    def category_label(self) -> str:
        return {
            "friend":    "friend",
            "assistant": "assistant",
            "planner":   "planner",
            "sysadmin":  "admin",
            "general":   "general",
        }.get(self.category, self.category)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str | bytes) -> "Agent":
        d = json.loads(data)
        d.setdefault("category", "general")
        # only keep keys the dataclass knows about
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        d = {k: v for k, v in d.items() if k in valid}
        return cls(**d)


class AgentManager:
    """CRUD for agents on disk. ~/.purr/agents/<name>.json."""

    def __init__(self) -> None:
        self._ensure_builtin_seeded()

    def _ensure_builtin_seeded(self) -> None:
        """Copy builtins to ~/.purr/agents/, refreshing any that are stale.

        Stale = on-disk builtin file is older than the shipped copy, OR
        its BUILTINS_VERSION marker (in the file itself) is below the
        current BUILTINS_VERSION constant.
        """
        user_dir = paths.agents_dir()
        builtin_dir = paths.builtin_agents_dir()
        if not builtin_dir.exists():
            return
        for src in builtin_dir.glob("*.json"):
            dst = user_dir / src.name
            should_copy = False
            if not dst.exists():
                should_copy = True
            else:
                # version check — builtins may include a "version" field
                # in the JSON. If user's version is older, refresh.
                try:
                    user_data = json.loads(dst.read_text())
                    user_ver = user_data.get("__builtins_version", 0)
                except Exception:
                    user_ver = 0
                if user_ver < BUILTINS_VERSION:
                    should_copy = True
            if should_copy:
                shutil.copy2(src, dst)

    # ----- listing / loading
    def all(self) -> list[Agent]:
        out: list[Agent] = []
        for p in sorted(paths.agents_dir().glob("*.json")):
            try:
                out.append(Agent.from_json(p.read_text()))
            except Exception:
                continue
        return out

    def names(self) -> list[str]:
        return [a.name for a in self.all()]

    def get(self, name: str) -> Agent | None:
        path = paths.agents_dir() / f"{name}.json"
        if not path.exists():
            return None
        try:
            return Agent.from_json(path.read_text())
        except Exception:
            return None

    # ----- mutation
    def save(self, agent: Agent) -> Path:
        path = paths.agents_dir() / f"{agent.name}.json"
        path.write_text(agent.to_json())
        return path

    def delete(self, name: str) -> bool:
        path = paths.agents_dir() / f"{name}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def new(self, name: str, role: str = "") -> Agent:
        """Create a starter agent with a generic system prompt. User can /agent edit to refine."""
        if self.get(name) is not None:
            raise ValueError(f"agent '{name}' already exists — pick another name")
        a = Agent(
            name=name,
            role=role or "custom agent",
            glyph="(•_•)",
            system_prompt=(
                f"You are '{name}', a helpful local AI agent running inside the purr TUI. "
                f"You are running on the user's Mac via Ollama. Be concise, warm, and useful. "
                f"Use tools when they clearly help. If unsure, ask."
            ),
            tools=[],
        )
        self.save(a)
        return a

    def edit(self, name: str) -> None:
        """Open the agent JSON in $EDITOR. Reload on save."""
        path = paths.agents_dir() / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"no such agent: {name}")
        editor = subprocess.os.environ.get("EDITOR", "nano")
        subprocess.run([editor, str(path)])

    def builtin_names(self) -> Iterable[str]:
        return ("dross", "assistant", "friend", "planner", "sysadmin")
