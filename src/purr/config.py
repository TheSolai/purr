"""Purr configuration. Loaded from ~/.purr/config.toml, with defaults."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from purr import paths


@dataclass
class Config:
    ollama_host: str = "http://localhost:11434"
    # Default to llama3-groq-tool-use:8b — purpose-built for tool-calling, fast on Mac,
    # 8B size, stable for plugin architectures. Use `/model gpt-oss:20b` for hard
    # reasoning, `/model qwen3:14b` for thinking + tool-calling, `/model qwen2.5:3b`
    # for instant replies.
    default_model: str = "llama3-groq-tool-use:8b"
    theme: str = "catppuccin-mocha"
    confirm_dangerous_tools: bool = True
    max_history_messages: int = 50
    temperature: float = 0.7
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        path = paths.config_path()
        if not path.exists():
            cfg.save()  # write defaults
            return cfg
        try:
            data = tomllib.loads(path.read_text())
        except Exception:
            return cfg
        for key in (
            "ollama_host",
            "default_model",
            "theme",
            "confirm_dangerous_tools",
            "max_history_messages",
            "temperature",
        ):
            if key in data:
                setattr(cfg, key, data[key])
        cfg.extra = {k: v for k, v in data.items() if k not in {
            "ollama_host", "default_model", "theme",
            "confirm_dangerous_tools", "max_history_messages", "temperature",
        }}
        return cfg

    def save(self) -> None:
        path = paths.config_path()
        lines = [
            "# 🐾 purr config — edit me",
            f'ollama_host = "{self.ollama_host}"',
            f'default_model = "{self.default_model}"',
            f'theme = "{self.theme}"',
            f"confirm_dangerous_tools = {str(self.confirm_dangerous_tools).lower()}",
            f"max_history_messages = {self.max_history_messages}",
            f"temperature = {self.temperature}",
        ]
        path.write_text("\n".join(lines) + "\n")
