"""Chat history persistence — one JSONL file per (agent, session) under ~/.purr/chats/."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from purr import paths
from purr.ollama_client import ChatMessage


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ChatHistory:
    """Append-only chat log. Cheap, human-readable, easy to grep."""

    def __init__(self, agent: str, session_id: str | None = None) -> None:
        self.agent = agent
        self.session_id = session_id or f"{_now()}_{uuid.uuid4().hex[:6]}"
        self.path = paths.chats_dir() / f"{_safe(agent)}__{_safe(self.session_id)}.jsonl"
        if not self.path.exists():
            self.path.write_text("")

    def append(self, message: ChatMessage) -> None:
        rec = {
            "ts": _now(),
            "role": message.role,
            "content": message.content,
        }
        if message.tool_calls:
            rec["tool_calls"] = message.tool_calls
        if message.tool_name:
            rec["tool_name"] = message.tool_name
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def load(self) -> list[ChatMessage]:
        out: list[ChatMessage] = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                out.append(ChatMessage(
                    role=d["role"],
                    content=d.get("content", ""),
                    tool_calls=d.get("tool_calls"),
                    tool_name=d.get("tool_name"),
                ))
            except Exception:
                continue
        return out
