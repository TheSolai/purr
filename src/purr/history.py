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


def list_sessions(agent: str | None = None) -> list[dict]:
    """List past chat sessions under ~/.purr/chats/.

    Each entry has: agent, session_id, path, mtime (epoch seconds), size_bytes,
    message_count, first_user_message (used as the title).

    Newest first. If `agent` is given, only that agent's sessions are returned.
    """
    chats = paths.chats_dir()
    if not chats.exists():
        return []
    out: list[dict] = []
    for f in chats.glob("*.jsonl"):
        # filename: <agent>__<session_id>.jsonl
        stem = f.stem
        if "__" not in stem:
            continue
        ag, sid = stem.split("__", 1)
        if agent and ag != agent:
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        # peek at the file to count messages and grab the first user line
        msg_count = 0
        first_user = ""
        try:
            with f.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    msg_count += 1
                    if not first_user:
                        try:
                            d = json.loads(line)
                            if d.get("role") == "user":
                                first_user = d.get("content", "")[:80]
                        except Exception:
                            pass
        except OSError:
            continue
        out.append({
            "agent": ag,
            "session_id": sid,
            "path": str(f),
            "mtime": stat.st_mtime,
            "size_bytes": stat.st_size,
            "message_count": msg_count,
            "title": first_user or "(empty)",
        })
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out


def load_session(path: str) -> tuple[str, list[ChatMessage]]:
    """Load a past chat by file path. Returns (agent, messages)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    stem = p.stem
    if "__" not in stem:
        raise ValueError(f"unexpected session filename: {p.name}")
    ag = stem.split("__", 1)[0]
    msgs: list[ChatMessage] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            msgs.append(ChatMessage(
                role=d["role"],
                content=d.get("content", ""),
                tool_calls=d.get("tool_calls"),
                tool_name=d.get("tool_name"),
            ))
        except Exception:
            continue
    return ag, msgs
