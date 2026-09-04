"""🐾 purr — Textual TUI for chatting with your local Ollama models.

Layout:
  ┌──────────────────┬─────────────────────────────────────────────────┐
  │ agent sidebar    │ ASCII header (gradient)                          │
  │  assistant       │                                                 │
  │  friend          │ chat scrollback (Markdown rendered)              │
  │  planner         │                                                 │
  │  sysadmin        │                                                 │
  │  custom…         │ input prompt                                    │
  └──────────────────┴─────────────────────────────────────────────────┘
  status bar: model · tokens · active agent · quit hints

Slash commands:
  /agent list                     list all agents
  /agent <name>                   switch to agent
  /agent new <name> [role]        create a new agent
  /agent edit <name>              open agent JSON in $EDITOR
  /agent rm <name>                delete an agent (blocks builtins)
  /model <name>                   set the Ollama model for this session
  /models                         list installed models
  /clear                          clear the chat scrollback
  /tools                          show tools the active agent can use
  /whoami                         print active agent + model
  /help                           show help
  /quit                           exit purr
"""
from __future__ import annotations

import asyncio
import json
import shlex
import sys
from typing import ClassVar

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Input,
    ListItem,
    ListView,
    Markdown as TextualMarkdown,
    Static,
)
from textual.containers import VerticalScroll

from purr import __app_glyph__, __app_name__, __version__
from purr import ascii_art, paths
from purr.agents import Agent, AgentManager
from purr.config import Config
from purr.history import ChatHistory
from purr.ollama_client import ChatMessage, OllamaClient
from purr import tools as toolmod


# ---- widget helpers --------------------------------------------------------

class Header(Static):
    """The gradient ASCII banner + a one-line status row."""

    DEFAULT_CSS = """
    Header {
      height: auto;
      padding: 0 1;
      border-bottom: solid $accent 30%;
    }
    Header #status {
      color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._app_ref: PurrApp | None = None

    def on_mount(self) -> None:
        self._app_ref = self.app  # type: ignore[assignment]

    def render_for(self, app: "PurrApp") -> None:
        # Logo with a horizontal gradient (catppuccin-ish: pink → mauve → blue)
        logo = ascii_art.PURR_FULL_LOGO
        gradient = ["#f5c2e7", "#cba6f7", "#89b4fa", "#74c7ec", "#94e2d5"]
        text = Text()
        for i, line in enumerate(logo):
            color = gradient[i % len(gradient)]
            text.append(line + "\n", style=color)
        # status line — glyph, name, ROLE pill, model, hint
        agent = app.active_agent
        cat_color = {
            "friend":    "#f5c2e7",   # pink
            "assistant": "#89b4fa",   # blue
            "planner":   "#a6e3a1",   # green
            "sysadmin":  "#fab387",   # peach
            "general":   "#cba6f7",   # mauve
        }.get(agent.category, "#cba6f7")
        n_tools = len(agent.tools)
        status = Text()
        status.append("  ")
        status.append(ascii_art.agent_glyph(agent.name), style="bold")
        status.append(f"  {agent.title}", style="bold #f5c2e7")
        status.append("  [", style="dim")
        status.append(agent.category_label, style=f"bold {cat_color}")
        status.append(f"]", style="dim")
        status.append("   ·   model: ", style="dim")
        status.append(app.current_model, style="#94e2d5")
        status.append(f"   ·   tools: {n_tools}", style="dim")
        if n_tools == 0:
            status.append("  (chat-only — /agent to switch)", style="dim italic")
        else:
            status.append("   ·   type / for commands, ctrl+c to quit", style="dim")
        text.append(status)
        self.update(text)


class Sidebar(Static):
    """Left rail — list of agents, current one highlighted."""

    DEFAULT_CSS = """
    Sidebar {
      width: 22;
      border-right: solid $accent 30%;
      padding: 1 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._app_ref: PurrApp | None = None

    def on_mount(self) -> None:
        self._app_ref = self.app  # type: ignore[assignment]

    def render_for(self, app: "PurrApp") -> None:
        mgr: AgentManager = app.agents
        active_name = app.active_agent.name
        t = Text()
        t.append("AGENTS\n", style="bold #f5c2e7")
        t.append("─" * 18 + "\n", style="#585b70")
        for a in mgr.all():
            glyph = ascii_art.agent_glyph(a.name)
            line = f"{glyph}  {a.title}"
            if a.name == active_name:
                t.append("▸ ", style="bold #f5c2e7")
                t.append(line + "\n", style="bold #f5c2e7")
            else:
                t.append("  ", style="dim")
                t.append(line + "\n", style="")
            if a.role:
                t.append(f"     {a.role}\n", style="dim italic")
        t.append("\n")
        t.append(f"{__app_glyph__}  {__app_name__} v{__version__}\n", style="dim")
        t.append("ctrl+n = new agent", style="dim italic")
        self.update(t)


# ---- the app itself --------------------------------------------------------

class PurrApp(App):
    CSS = """
    Screen {
      layout: vertical;
    }
    #body {
      height: 1fr;
    }
    #chat-scroll {
      height: 1fr;
      padding: 0 2;
    }
    #chat {
      padding: 1 0;
    }
    #prompt-row {
      height: 3;
      padding: 0 1;
      border-top: solid $accent 30%;
    }
    #prompt {
      height: 3;
    }
    #sidebar {
      width: 26;
      border-right: solid $accent 30%;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "quit", "quit", show=True),
        Binding("ctrl+l", "clear_chat", "clear", show=True),
        Binding("ctrl+n", "new_agent", "new agent", show=True),
        Binding("ctrl+t", "next_agent", "next agent", show=True),
        Binding("f1", "help", "help", show=False),
    ]

    active_agent: Agent = None  # type: ignore[assignment]
    current_model: str = ""

    def __init__(self) -> None:
        super().__init__()
        self.config = Config.load()
        self.agents = AgentManager()
        # start on Dross — he's the main man
        all_a = self.agents.all()
        first = next((a for a in all_a if a.name == "dross"), all_a[0] if all_a else None)
        if first is None:
            first = self.agents.new("assistant", "default assistant")
        self.active_agent = first
        self.current_model = first.model or self.config.default_model
        self.client = OllamaClient(host=self.config.ollama_host)
        self.history = ChatHistory(agent=self.active_agent.name)
        self._busy = False
        self._chat_md = ""          # full Markdown source shown in the chat pane
        self._bubble_anchor = -1    # index into _chat_md where the in-progress bubble starts (or -1)
        self.title = f"🐾 purr — chatting with {self.active_agent.title}"

    # ---- layout

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield Sidebar(id="sidebar")
            with Vertical():
                with VerticalScroll(id="chat-scroll"):
                    yield TextualMarkdown(id="chat")
                yield Input(placeholder="type a message — or / for commands…", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Header).render_for(self)
        self.query_one(Sidebar).render_for(self)
        self._greet()
        # focus the input so keystrokes land there immediately
        self.query_one("#prompt", Input).focus()

    def _greet(self) -> None:
        # Show a one-line intro in the chat scrollback
        n_agents = len(self.agents.all())
        intro = (
            f"🐾 **{__app_name__} v{__version__}** — your local Ollama companion\n\n"
            f"Active agent: **{self.active_agent.title}**  ·  model: `{self.current_model}`\n\n"
            f"You've got **{n_agents} personas** loaded — Dross runs the show, "
            f"the Assistant handles general work, Friend listens, Mac Planner wrangles your Apple apps, "
            f"and Sysadmin does the shell. Type `/agent` to switch, `/help` for the rest."
        )
        self._append_md(intro)

    # ---- rendering helpers

    def _append_md(self, md_text: str) -> None:
        self._chat_md = (self._chat_md + "\n\n---\n\n" + md_text) if self._chat_md else md_text
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()

    def _append_bubble(self, who: str, body: str, color: str) -> None:
        if who == "user":
            block = f"**› you**\n\n{body}\n"
        else:
            glyph = ascii_art.agent_glyph(self.active_agent.name)
            block = f"**{glyph} {self.active_agent.title}**\n\n{body}\n"
        self._chat_md = (self._chat_md + "\n" + block) if self._chat_md else block
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()

    def _append_tool(self, name: str, args: dict, result: str) -> None:
        snippet = json.dumps(args, ensure_ascii=False)[:200]
        block = (
            f"```\n🔧 {name}({snippet})\n```\n\n"
            f"```\n{result[:1200]}\n```\n"
        )
        self._chat_md = (self._chat_md + "\n" + block) if self._chat_md else block
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        try:
            self.query_one("#chat-scroll", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    # ---- input handling

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._run_command(text)
        else:
            self._chat(text)

    # ---- slash commands

    def _run_command(self, line: str) -> None:
        try:
            parts = shlex.split(line)
        except ValueError as e:
            self._append_bubble("purr", f"couldn't parse: `{e}`", "#f38ba8")
            return
        if not parts:
            return
        cmd, rest = parts[0], parts[1:]
        if cmd in ("/quit", "/exit", "/q"):
            self.exit()
            return
        if cmd in ("/help", "/?", "/h"):
            self._show_help()
        elif cmd == "/clear":
            self.action_clear_chat()
        elif cmd == "/agent":
            self._cmd_agent(rest)
        elif cmd == "/model":
            self._cmd_model(rest)
        elif cmd == "/models":
            self._list_models()
        elif cmd == "/whoami":
            self._append_bubble("purr",
                f"agent=`{self.active_agent.name}` ({self.active_agent.title})  ·  model=`{self.current_model}`",
                "#a6e3a1")
        elif cmd == "/tools":
            self._show_tools()
        elif cmd == "/role":
            self._show_role()
        elif cmd == "/status":
            self._show_status()
        elif cmd == "/new":
            self.action_new_agent()
        else:
            self._append_bubble("purr", f"unknown command: `{cmd}`. type `/help`.", "#f38ba8")

    def _show_help(self) -> None:
        help_md = (
            "**purr commands**\n\n"
            "- `/agent list` — list all agents\n"
            "- `/agent <name>` — switch to an agent\n"
            "- `/agent new <name> [role…]` — create a new agent\n"
            "- `/agent edit <name>` — open agent JSON in `$EDITOR`\n"
            "- `/agent rm <name>` — delete an agent (built-ins are protected)\n"
            "- `/model <name>` — switch Ollama model for this session\n"
            "- `/models` — list installed models\n"
            "- `/tools` — show tools enabled for the active agent\n"
            "- `/role` — show the active agent's category + permissions\n"
            "- `/status` — show purr + ollama + model state\n"
            "- `/clear` — clear chat  (`ctrl+l`)\n"
            "- `/whoami` — show active agent + model\n"
            "- `/quit` — exit purr  (`ctrl+c`)\n\n"
            "**keys**: `ctrl+n` new agent · `ctrl+t` next agent · `ctrl+l` clear"
        )
        self._append_bubble("purr", help_md, "#cdd6f4")

    def _show_role(self) -> None:
        a = self.active_agent
        n = len(a.tools)
        cat = a.category_label
        if n == 0:
            perm = "chat-only — no tools, no system access. Switch personas for any task work."
        else:
            tools_str = ", ".join(f"`{t}`" for t in a.tools)
            perm = f"**{n} tool(s) enabled:**\n\n{tools_str}"
        self._append_bubble(
            "purr",
            f"**{a.title}** — category: `{cat}`\n\n"
            f"**role:** {a.role}\n\n"
            f"**permissions:**\n\n{perm}",
            "#cdd6f4",
        )

    def _show_status(self) -> None:
        a = self.active_agent
        self._append_bubble(
            "purr",
            f"**purr status**\n\n"
            f"- agent: `{a.name}` ({a.title}, category `{a.category_label}`)\n"
            f"- model: `{self.current_model}`\n"
            f"- host: `{self.config.ollama_host}`\n"
            f"- tools: {len(a.tools)} enabled\n"
            f"- chats dir: `{paths.chats_dir()}`\n"
            f"- agents dir: `{paths.agents_dir()}`\n"
            f"- config: `{paths.config_path()}`\n"
            f"- confirm dangerous tools: `{self.config.confirm_dangerous_tools}`",
            "#cdd6f4",
        )

    def _cmd_agent(self, args: list[str]) -> None:
        if not args or args[0] in ("list", "ls"):
            items = self.agents.all()
            lines = []
            for a in items:
                glyph = ascii_art.agent_glyph(a.name)
                tag = "  _(builtin)_" if a.builtin else ""
                lines.append(f"- {glyph} `{a.name}` — {a.title} — {a.role}{tag}")
            self._append_bubble("purr", "**the team**\n\n" + "\n".join(lines), "#cdd6f4")
            return
        sub = args[0]
        if sub == "new":
            if len(args) < 2:
                self._append_bubble("purr", "usage: `/agent new <name> [role…]`", "#f38ba8")
                return
            name = args[1]
            role = " ".join(args[2:]) if len(args) > 2 else ""
            try:
                a = self.agents.new(name, role=role)
            except ValueError as e:
                self._append_bubble("purr", f"`{e}`", "#f38ba8")
                return
            self._append_bubble("purr", f"created agent `{a.name}`. type `/agent {a.name}` to switch, or `/agent edit {a.name}` to customize it.", "#a6e3a1")
            self._refresh_chrome()
            return
        if sub == "edit":
            if len(args) < 2:
                self._append_bubble("purr", "usage: `/agent edit <name>`", "#f38ba8")
                return
            try:
                self.agents.edit(args[1])
            except FileNotFoundError as e:
                self._append_bubble("purr", f"`{e}`", "#f38ba8")
            self._refresh_chrome()
            return
        if sub in ("rm", "delete", "remove"):
            if len(args) < 2:
                self._append_bubble("purr", "usage: `/agent rm <name>`", "#f38ba8")
                return
            name = args[1]
            agent = self.agents.get(name)
            if agent is None:
                self._append_bubble("purr", f"no such agent: `{name}`", "#f38ba8")
                return
            if agent.builtin:
                self._append_bubble("purr", f"refusing to delete built-in agent `{name}`. copy it first: `/agent new {name}-copy`.", "#f38ba8")
                return
            self.agents.delete(name)
            if self.active_agent.name == name:
                self.active_agent = self.agents.all()[0]
                self.history = ChatHistory(agent=self.active_agent.name)
            self._append_bubble("purr", f"deleted agent `{name}`.", "#a6e3a1")
            self._refresh_chrome()
            return
        # treat as a switch
        agent = self.agents.get(sub)
        if agent is None:
            self._append_bubble("purr", f"no such agent: `{sub}`. try `/agent list`.", "#f38ba8")
            return
        self.active_agent = agent
        self.history = ChatHistory(agent=agent.name)
        if agent.model:
            self.current_model = agent.model
        self.title = f"🐾 purr — {agent.title}"
        self._append_bubble("purr", f"switched to **{agent.title}** ({agent.role}). model: `{self.current_model}`.", "#a6e3a1")
        self._refresh_chrome()

    def _cmd_model(self, args: list[str]) -> None:
        if not args:
            self._append_bubble("purr", f"current model: `{self.current_model}`. usage: `/model <name>`.", "#cdd6f4")
            return
        self.current_model = args[0]
        self._append_bubble("purr", f"model set to `{self.current_model}`.", "#a6e3a1")
        self._refresh_chrome()

    def _list_models(self) -> None:
        self.run_worker(self._list_models_async(), exclusive=False)

    async def _list_models_async(self) -> None:
        try:
            models = await self.client.list_models()
        except Exception as e:
            self._append_bubble("purr", f"couldn't list models: `{e}`", "#f38ba8")
            return
        if not models:
            self._append_bubble("purr", "no models pulled. run `ollama pull <name>` first.", "#f38ba8")
            return
        lines = "\n".join(f"- `{m['name']}`" for m in models)
        self._append_bubble("purr", f"**installed models**\n\n{lines}", "#cdd6f4")

    def _show_tools(self) -> None:
        if not self.active_agent.tools:
            self._append_bubble("purr", f"agent `{self.active_agent.name}` has no tools enabled (chat-only).", "#cdd6f4")
            return
        lines = "\n".join(f"- `{n}`" for n in self.active_agent.tools)
        self._append_bubble("purr", f"**tools for {self.active_agent.title}**\n\n{lines}\n\n(type `/agent edit {self.active_agent.name}` to change)", "#cdd6f4")

    # ---- chat loop (async streaming + tool calls)

    def _chat(self, user_text: str) -> None:
        if self._busy:
            self._append_bubble("purr", "still working on the last reply — press `esc` to interrupt.", "#f38ba8")
            return
        self._busy = True
        self._append_bubble("user", user_text, "#89dceb")
        self.run_worker(self._chat_async(user_text), exclusive=True)

    async def _chat_async(self, user_text: str) -> None:
        try:
            # reload agent in case user edited it
            current = self.agents.get(self.active_agent.name) or self.active_agent
            self.active_agent = current

            # build message list
            history = self.history.load()
            messages: list[dict] = [{"role": "system", "content": current.system_prompt}]
            for m in history[-self.config.max_history_messages:]:
                if m.role in ("user", "assistant", "tool"):
                    d = {"role": m.role, "content": m.content}
                    if m.tool_name:
                        d["name"] = m.tool_name
                    messages.append(d)
            messages.append({"role": "user", "content": user_text})
            self.history.append(ChatMessage(role="user", content=user_text))

            # tool schemas
            tool_specs = toolmod.specs_for(current.tools)
            schemas = toolmod.schemas_for(current.tools) if tool_specs else None

            # multi-turn tool loop (max 4 iterations to bound)
            for _turn in range(4):
                temperature = current.temperature if current.temperature is not None else self.config.temperature

                # stream the response
                full_text = ""
                pending_tool_calls: list[dict] = []
                self._bubble_anchor = -1
                try:
                    async for chunk in self.client.stream_chat(
                        model=self.current_model,
                        messages=messages,
                        tools=schemas,
                        temperature=temperature,
                    ):
                        msg = chunk.get("message") or {}
                        delta = msg.get("content") or ""
                        if delta:
                            full_text += delta
                            self._live_update_assistant(full_text, phase="typing")
                        elif not full_text and not pending_tool_calls:
                            self._live_update_assistant("", phase="thinking")
                        if msg.get("tool_calls"):
                            pending_tool_calls = msg["tool_calls"]
                except Exception as e:
                    self._append_bubble("purr", f"ollama error: `{e}`", "#f38ba8")
                    self._busy = False
                    return

                # finalize assistant message
                if not pending_tool_calls:
                    # done — replace the in-progress bubble with the final one (no caret, no "typing…" label)
                    if full_text.strip():
                        glyph = ascii_art.agent_glyph(self.active_agent.name)
                        final = f"**{glyph} {self.active_agent.title}**\n\n{full_text}\n"
                        if self._bubble_anchor >= 0:
                            self._chat_md = self._chat_md[: self._bubble_anchor] + final
                        else:
                            sep = "\n" if self._chat_md else ""
                            self._chat_md += sep + final
                        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
                        self._scroll_to_bottom()
                    self._bubble_anchor = -1
                    self.history.append(ChatMessage(role="assistant", content=full_text))
                    messages.append({"role": "assistant", "content": full_text})
                    break

                # handle tool calls
                self._bubble_anchor = -1
                assistant_msg: dict = {"role": "assistant", "content": full_text, "tool_calls": pending_tool_calls}
                messages.append(assistant_msg)
                self.history.append(ChatMessage(role="assistant", content=full_text, tool_calls=pending_tool_calls))

                for tc in pending_tool_calls:
                    fn = tc.get("function") or {}
                    tool_name = fn.get("name", "")
                    raw_args = fn.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except Exception:
                            args = {"_raw": raw_args}
                    else:
                        args = dict(raw_args)

                    # dangerous-tool confirmation
                    if self.config.confirm_dangerous_tools and toolmod.is_dangerous_tool(tool_name):
                        ok = await self._confirm(f"agent wants to run dangerous tool `{tool_name}`\n  args: `{json.dumps(args)[:300]}`\n\nallow?")
                        if not ok:
                            result = "⛔ user denied this tool call"
                        else:
                            result = toolmod.call(tool_name, **args)
                    else:
                        result = toolmod.call(tool_name, **args)

                    self._append_tool(tool_name, args, result)
                    messages.append({"role": "tool", "name": tool_name, "content": result})
                    self.history.append(ChatMessage(role="tool", content=result, tool_name=tool_name))
                # loop again — model sees tool results and continues

        finally:
            self._busy = False

    def _live_update_assistant(self, text: str, phase: str = "thinking") -> None:
        """Stream-update the in-progress assistant bubble.

        phase ∈ {"thinking", "typing"}. We track the anchor position of the
        current bubble inside self._chat_md so successive chunks just rewrite
        the tail — no headers get duplicated.
        """
        glyph = ascii_art.agent_glyph(self.active_agent.name)
        header = f"**{glyph} {self.active_agent.title}**"
        label = "_(thinking…)_" if phase == "thinking" else "_(typing…)_"
        if not text and phase == "thinking":
            block = f"{header} {label}\n\n"
        else:
            block = f"{header} {label}\n\n{text}▌"

        if self._bubble_anchor < 0:
            # first tick of this turn — append a fresh bubble, remember where it starts
            sep = "\n" if self._chat_md else ""
            self._chat_md += sep + block
            self._bubble_anchor = len(self._chat_md) - len(block)
        else:
            # rewrite the tail starting at the anchor
            self._chat_md = self._chat_md[: self._bubble_anchor] + block
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()

    async def _confirm(self, message: str) -> bool:
        # Modal confirm — push a screen with a yes/no
        from textual.screen import ModalScreen

        class ConfirmScreen(ModalScreen[bool]):
            DEFAULT_CSS = """
            ConfirmScreen {
              align: center middle;
            }
            #confirm {
              width: 70%;
              max-width: 90;
              height: auto;
              padding: 1 2;
              border: thick $warning;
              background: $surface;
            }
            #confirm-buttons {
              height: 3;
              align-horizontal: center;
            }
            Button {
              margin: 0 1;
            }
            """
            def compose(self) -> ComposeResult:
                with Vertical(id="confirm"):
                    yield Static(message)
                    with Horizontal(id="confirm-buttons"):
                        yield Static("y = allow · n = deny · esc = cancel", id="hint")

            def key_y(self) -> None:
                self.dismiss(True)
            def key_n(self) -> None:
                self.dismiss(False)
            def key_escape(self) -> None:
                self.dismiss(False)

        return await self.push_screen_wait(ConfirmScreen())

    # ---- key actions

    def action_clear_chat(self) -> None:
        self._chat_md = ""
        self.query_one("#chat", TextualMarkdown).update("")
        self._greet()

    def action_new_agent(self) -> None:
        from getpass import getuser
        # Quick inline creation; user can /agent edit <name> after.
        name = f"agent-{getuser()}-new"
        # De-dup
        suffix = 1
        base = name
        while self.agents.get(name) is not None:
            name = f"{base}-{suffix}"
            suffix += 1
        self.agents.new(name, role="created via ctrl+n")
        self._append_bubble("purr", f"created `{name}`. type `/agent edit {name}` to customize, then `/agent {name}` to switch.", "#a6e3a1")
        self._refresh_chrome()

    def action_next_agent(self) -> None:
        all_a = self.agents.all()
        if not all_a:
            return
        idx = next((i for i, a in enumerate(all_a) if a.name == self.active_agent.name), 0)
        nxt = all_a[(idx + 1) % len(all_a)]
        self._cmd_agent([nxt.name])

    def action_help(self) -> None:
        self._show_help()

    # ---- chrome refresh

    def _refresh_chrome(self) -> None:
        self.query_one(Header).render_for(self)
        self.query_one("#sidebar", Sidebar).render_for(self)
