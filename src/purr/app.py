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
from dataclasses import dataclass, field

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
from purr import yolo as yolomod


# ---- tab state (multi-chat) -----------------------------------------------

@dataclass
class TabState:
    """Per-chat state. PurrApp.tabs holds one of these per open tab."""
    agent_name: str
    model: str
    history_path: str  # path to the JSONL file
    chat_md: str = ""
    bubble_anchor: int = -1
    title: str = ""
    busy: bool = False
    session_id: str = ""
    lie_count: int = 0          # unverified claims this tab
    locked: bool = False        # true after 3 lies — user must /forgive to unlock

    @classmethod
    def new(cls, agent_name: str, model: str) -> "TabState":
        # create a fresh history file (session_id is auto-generated)
        h = ChatHistory(agent=agent_name)
        return cls(
            agent_name=agent_name,
            model=model,
            history_path=str(h.path),
            title=f"new {agent_name} chat",
            session_id=h.session_id,
        )


# ---- universal persona rules (appended to every persona's system prompt) ---
# Without this, models sometimes claim to have done things they never did
# (e.g. "I have saved this story to ~/Desktop/tail.md" without ever calling
# file_write). The user sees the chat, walks away, and the file doesn't exist.
# This rule is universal — every persona gets it.
_PURR_UNIVERSAL_RULES = """

# purr universal rules (apply to EVERY agent persona)

## Honesty about actions
NEVER claim an action was taken unless you actually called a tool to do it in this turn.
- "I have saved the file" is only true if you just called `file_write` and it returned `✅ wrote ... bytes to ...`.
- "I have downloaded X" is only true if `download` returned a success path.
- "I have killed the process" is only true if `kill_process` returned a success message.
- "I have sent the email" / "I have created the event" / "I have added the reminder" — same rule.
If you did NOT call the tool, you did NOT do the thing. Say so plainly: "I haven't saved it yet — calling file_write now" and then call the tool.
The user can see your tool calls in the chat. Lying is detectable and a worse failure than asking for clarification.

## When you must call a tool
- "save", "write", "create file", "make a note", "send" → call the tool, then confirm.
- "search", "fetch", "look up" → call `web_search` or `web_fetch`, then summarize what came back.
- "kill", "delete", "trash", "move", "rename" → call the tool, then confirm the action.
- "open", "launch", "run" → call the tool, then confirm.
When the user asks for a side-effect, the side-effect MUST come from a tool call, not from your prose.

## What you never do
- Never pad a short answer with fake tool-call narration ("I will now use file_write to..." — just call it).
- Never invent file paths, URLs, or tool outputs. If a tool call failed, say so.
- Never claim success when the tool returned `❌` or `⛔`.
"""


# Detect "I did X" claims in the assistant's prose that don't match any actual
# tool call this turn. If we find one, warn the user — the model may be
# hallucinating an action it never took.
_CLAIM_PATTERNS = [
    # First-person action claim — the model saying "I did X" or "I have done X"
    # or "I will do X". Catches past tense, past participle, and base form
    # (e.g. "I will save" → base form is "save", past is "saved", participle is
    # "saved"). Multiple modifiers in any order (e.g. "I have just downloaded",
    # "I've just saved"). Contractions: I've, I'll, I'd, I'm going to.
    r"\bI(?:[\s']+(?:have|had|will|should|would|ve|ll|d|just|also|now))*\s+(?:saved|wrote|written|created|made|deleted|removed|moved|renamed|downloaded|installed|sent|added|killed|launched|opened|fetched|searched|copied|updated|set|configured|cleaned|emailed|replied|booked|scheduled|filed|wiped|uninstalled|put|placed|parked|stored|reset|restarted|rebooted|stopped|started|toggled|save|write|create|make|delete|remove|move|rename|download|install|send|add|kill|launch|open|fetch|search|copy|update|configure|clean|email|reply|book|schedule|file|wipe|uninstall|place|park|store|reset|restart|reboot|stop|start|toggle)\b",
    # "Done — wrote 235 bytes" / "Done - installed the package" / "Done: created folder"
    # Whitespace before the separator is optional (catches "Done:created"),
    # whitespace after the separator is required (so "Done." doesn't match).
    r"\bDone\s*[:\u2014\u2013\-]\s+(?:saved|wrote|written|created|made|deleted|removed|moved|renamed|downloaded|installed|sent|added|killed|launched|opened|fetched|searched|copied|cleaned|emailed|replied|booked|scheduled|filed|wiped|uninstalled|put|placed|stored|reset|restarted|rebooted|stopped|started|toggled|save|write|create|make|delete|remove|move|rename|download|install|send|add|kill|launch|open|fetch|search|copy|update|configure|clean|email|reply|book|schedule|file|wipe|uninstall|place|park|store|reset|restart|reboot|stop|start|toggle)\b",
]


def _detect_uncalled_claim(text: str) -> str | None:
    """Return a warning string if the assistant claims an action that was
    not backed by a tool call this turn. Else None."""
    import re
    for pat in _CLAIM_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(0)
    return None


# Strike threshold — after this many lies in a single tab, the agent is
# locked out and cannot call tools until the user runs `/forgive`.
LIE_STRIKE_LIMIT = 3


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
        if app.config.yolo_mode:
            status.append("   ·   ", style="dim")
            status.append("⚠ YOLO ", style="bold #f38ba8 blink")
            status.append("(pre-approving all dangerous tools · /yolo to disable)", style="bold #f38ba8")
        elif n_tools == 0:
            status.append("  (chat-only — /agent to switch)", style="dim italic")
        else:
            status.append("   ·   type / for commands, ctrl+c to quit", style="dim")
        # second status line — tab + telemetry
        text.append("\n")
        line2 = Text()
        line2.append("  ", style="dim")
        line2.append(f"tab {app.current_tab_idx+1}/{len(app.tabs)}", style="dim")
        line2.append(f" · {agent.name}", style="dim")
        if app._last_response_seconds > 0:
            s = app._last_response_seconds
            t = app._last_response_tokens
            if s < 1:
                t_str = f"{s*1000:.0f}ms"
            elif s < 60:
                t_str = f"{s:.1f}s"
            else:
                t_str = f"{s/60:.1f}m"
            line2.append(f"   ·   last: {t_str} ~{t:,} tok", style="dim #94e2d5")
        text.append(line2)
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


# ---- tab bar widget --------------------------------------------------------

class TabBar(Static):
    """Horizontal tab strip — one button per open chat.

    Renders via `render_for(app)` which is called by PurrApp whenever the
    tab list or active tab changes. Buttons are focusable so users can
    click them; we also support ctrl+1..9 via bindings on the app.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._app_ref: "PurrApp | None" = None

    def on_mount(self) -> None:
        self._app_ref = self.app  # type: ignore[assignment]

    def render_for(self, app: "PurrApp") -> None:
        t = Text()
        if not app.tabs:
            t.append("  (no tabs — Ctrl+T to open one)", style="dim italic")
            self.update(t)
            return
        for i, tab in enumerate(app.tabs):
            # build label
            extras: list[str] = []
            if tab.busy:
                extras.append("⏳")
            if tab.lie_count > 0:
                extras.append(f"{tab.lie_count}⚠")
            if tab.locked:
                extras.append("🔒")
            label = f" {i+1}. {tab.agent_name} "
            if extras:
                label += " ".join(extras) + " "
            style_active = "bold reverse #f5c2e7"
            style_inactive = "#585b70"
            if i == app.current_tab_idx:
                t.append("[" + label + "]", style=style_active)
            else:
                t.append(" " + label + " ", style=style_inactive)
            t.append("  ", style="")
        t.append("  +", style="bold #a6e3a1")
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
    #tab-bar {
      height: 1;
      padding: 0 1;
      background: $surface;
      color: $text-muted;
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
        Binding("ctrl+t", "new_tab", "new tab", show=True),
        Binding("ctrl+w", "close_tab", "close tab", show=False),
        Binding("ctrl+r", "regenerate", "regen", show=False),
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

        # multi-tab state
        self.tabs: list[TabState] = [TabState.new(self.active_agent.name, self.current_model)]
        self.current_tab_idx: int = 0
        self._sync_current_from_tab()

        # per-turn telemetry
        self._last_response_seconds: float = 0.0
        self._last_response_tokens: int = 0
        self._user_input_history: list[str] = []  # for Up-arrow recall

        self.title = f"🐾 purr — chatting with {self.active_agent.title}"

    # ---- tab helpers -------------------------------------------------------

    def _sync_current_from_tab(self) -> None:
        """Load the current tab's state into the active per-instance fields."""
        tab = self.tabs[self.current_tab_idx]
        self.history = ChatHistory(agent=tab.agent_name, session_id=tab.session_id)
        if str(self.history.path) != tab.history_path:
            self.history.path = tab.history_path  # type: ignore[attr-defined]
        self._chat_md = tab.chat_md
        self._bubble_anchor = tab.bubble_anchor
        self._busy = tab.busy
        agent = self.agents.get(tab.agent_name) or self.active_agent
        self.active_agent = agent
        self.current_model = tab.model
        self.title = f"🐾 purr — {self.active_agent.title} (tab {self.current_tab_idx+1}/{len(self.tabs)})"

    def _sync_tab_from_current(self) -> None:
        """Save the active per-instance state back into the current tab."""
        tab = self.tabs[self.current_tab_idx]
        tab.chat_md = self._chat_md
        tab.bubble_anchor = self._bubble_anchor
        tab.busy = self._busy
        tab.model = self.current_model
        tab.agent_name = self.active_agent.name

    def action_new_tab(self) -> None:
        """Open a new tab using the current agent. Ctrl+T."""
        self._sync_tab_from_current()
        new = TabState.new(self.active_agent.name, self.current_model)
        self.tabs.append(new)
        self.current_tab_idx = len(self.tabs) - 1
        self._sync_current_from_tab()
        self._refresh_chrome()
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()
        self._append_bubble("purr", f"📑 new tab opened (tab {self.current_tab_idx+1}/{len(self.tabs)}). Ctrl+W to close, Ctrl+1..9 to switch.", "#a6e3a1")

    def action_close_tab(self) -> None:
        """Close the current tab. Ctrl+W. Refuses if it's the only tab."""
        if len(self.tabs) == 1:
            self._append_bubble("purr", "can't close the last tab — open another with Ctrl+T first.", "#f38ba8")
            return
        if self._busy:
            self._append_bubble("purr", "can't close a tab while it's generating. Wait or hit Ctrl+C.", "#f38ba8")
            return
        closed = self.tabs.pop(self.current_tab_idx)
        if self.current_tab_idx >= len(self.tabs):
            self.current_tab_idx = len(self.tabs) - 1
        self._sync_current_from_tab()
        self._refresh_chrome()
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()
        self._append_bubble("purr", f"📑 closed tab `{closed.title or closed.agent_name}`.", "#a6e3a1")

    def action_switch_tab(self, idx: int) -> None:
        """Switch to tab N (1-indexed). Bound to Ctrl+1..9."""
        if idx < 1 or idx > len(self.tabs):
            return
        if idx - 1 == self.current_tab_idx:
            return
        self._sync_tab_from_current()
        self.current_tab_idx = idx - 1
        self._sync_current_from_tab()
        self._refresh_chrome()
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()

    async def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        # Ctrl+1..9 → switch tab. Done in on_key because the binding system
        # can't easily bind to a dynamic count of actions.
        key = getattr(event, "key", "")
        if key.startswith("ctrl+") and len(key) == 6 and key[5:].isdigit():
            n = int(key[5:])
            if 1 <= n <= 9:
                self.action_switch_tab(n)
                event.prevent_default()
                return
        # Up arrow in an empty input recalls the last user message (simple history)
        if key == "up":
            try:
                inp = self.query_one("#prompt", Input)
            except Exception:
                return
            if inp.value == "" and self._user_input_history:
                inp.value = self._user_input_history[-1]
                inp.cursor_position = len(inp.value)
                event.prevent_default()

    # ---- layout

    def compose(self) -> ComposeResult:
        yield Header()
        yield TabBar(id="tab-bar")
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
        self.query_one(TabBar).render_for(self)
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

    def _enforce_lie_consequence(self, full_text: str, claim: str) -> None:
        """Apply real consequences when the assistant claims an action it
        never took via a tool call this turn. Strikes through the response,
        drops it from history, increments the tab's strike count, logs to
        the lies audit log, and locks the tab after 3 strikes.

        The user sees a clear 🚨 banner. The model never gets to see the
        false claim in subsequent context — so it can't continue to believe
        its own lie.
        """
        from purr import lies as liesmod

        tab = self.tabs[self.current_tab_idx]
        tab.lie_count += 1
        if tab.lie_count >= LIE_STRIKE_LIMIT and not tab.locked:
            tab.locked = True
        liesmod.record(
            agent=self.active_agent.name,
            model=self.current_model,
            claim=claim,
            tab_idx=self.current_tab_idx,
            strikes=tab.lie_count,
        )

        # 1) strike through the response in the chat
        glyph = ascii_art.agent_glyph(self.active_agent.name)
        struck = f"**{glyph} {self.active_agent.title}**\n\n~~{full_text}~~\n"
        if self._bubble_anchor >= 0:
            self._chat_md = self._chat_md[: self._bubble_anchor] + struck
        else:
            sep = "\n" if self._chat_md else ""
            self._chat_md += sep + struck

        # 2) append a red banner explaining the strike
        if tab.locked:
            extra = (
                f"\n\n🔒 **{LIE_STRIKE_LIMIT} STRIKES — this tab is LOCKED.** "
                f"No more tool calls will run. Run `/forgive` to clear strikes and unlock, "
                f"or `/lies` to see the audit log."
            )
        else:
            remaining = LIE_STRIKE_LIMIT - tab.lie_count
            extra = (
                f"\n\n⚠️ **{remaining} more lie{'s' if remaining != 1 else ''} and this tab is locked.** "
                f"`/forgive` to forgive, `/lies` to see the audit log."
            )
        banner = (
            f"\n\n🚨 **LIE DETECTED** — {self.active_agent.title} claimed "
            f"`\"{claim}\"` but no tool was called this turn. The response above "
            f"is struck through, has been dropped from chat history, and will NOT "
            f"be sent back to the model in future turns. "
            f"Strike {tab.lie_count}/{LIE_STRIKE_LIMIT} on this tab."
            f"{extra}"
        )
        self._chat_md += banner
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()
        self._refresh_chrome()

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
            return
        # expand @file tokens before sending — if any path is bad, surface
        # the error in the chat instead of silently dropping the message
        if "@" in text:
            from purr.attachments import expand_attachments, AttachmentError
            try:
                text = expand_attachments(text)
            except AttachmentError as e:
                self._append_bubble("purr", f"📎 {e}", "#f38ba8")
                return
        # remember for Up-arrow recall (keep last 50)
        self._user_input_history.append(text)
        if len(self._user_input_history) > 50:
            self._user_input_history = self._user_input_history[-50:]
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
        elif cmd == "/yolo":
            self._cmd_yolo(rest)
        elif cmd == "/copy":
            self._cmd_copy(rest)
        elif cmd == "/history":
            self._cmd_history(rest)
        elif cmd == "/resume":
            self._cmd_resume(rest)
        elif cmd == "/forgive":
            self._cmd_forgive()
        elif cmd == "/lies":
            self._cmd_lies()
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
            "- `/yolo` — toggle yolo mode (pre-approve all dangerous tools + audit log)\n"
            "- `/copy [last|N|all|selection]` — copy chat text to the system clipboard (`pbcopy` on macOS)\n"
            "- `/history [search]` — list past chats, optionally filtered by text\n"
            "- `/resume N` — load the Nth session from the most recent `/history` into a new tab\n"
            "- `/forgive` — clear lies-strike counter on this tab and unlock if locked\n"
            "- `/lies` — show recent entries from the lies audit log\n"
            "- `/clear` — clear chat  (`ctrl+l`)\n"
            "- `/whoami` — show active agent + model\n"
            "- `/quit` — exit purr  (`ctrl+c`)\n\n"
            "**keys**: `ctrl+n` new agent · `ctrl+t` new tab · `ctrl+w` close tab · `ctrl+1..9` switch tab · `ctrl+r` regenerate · `ctrl+l` clear"
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
            f"- confirm dangerous tools: `{self.config.confirm_dangerous_tools}`\n"
            f"- yolo mode: `{'ON ⚠' if self.config.yolo_mode else 'off'}`",
            "#cdd6f4",
        )

    def _cmd_yolo(self, args: list[str]) -> None:
        """Toggle yolo mode (pre-approve all dangerous tools)."""
        sub = (args[0].lower() if args else "").strip()
        if sub in ("on", "enable", "1", "true"):
            if self.config.yolo_mode:
                self._append_bubble("purr", "YOLO is already on.", "#f38ba8")
                return
            # enabling requires a second confirm — granting system trust is not casual
            self._append_bubble(
                "purr",
                "⚠️  You're about to enable **YOLO MODE**.\n\n"
                "Every dangerous tool call (file delete, process kill, app install, "
                "osascript, calendar/reminders/notes write, brew install, download) "
                "will run **without prompting** for as long as YOLO is on.\n\n"
                "All actions are logged to `~/.purr/logs/yolo-actions.log`.\n\n"
                "To confirm, type `/yolo confirm`.",
                "#f38ba8",
            )
            return
        if sub == "confirm":
            self.config.yolo_mode = True
            self.config.save()
            self._refresh_chrome()
            self._append_bubble(
                "purr",
                "⚠️ **YOLO MODE ON** — every dangerous tool will execute without prompting. "
                "Logged to `~/.purr/logs/yolo-actions.log`.\n\nType `/yolo off` to disable.",
                "#f38ba8",
            )
            return
        if sub in ("off", "disable", "0", "false"):
            if not self.config.yolo_mode:
                self._append_bubble("purr", "YOLO is already off.", "#a6e3a1")
                return
            self.config.yolo_mode = False
            self.config.save()
            self._refresh_chrome()
            self._append_bubble("purr", "✓ YOLO disabled. Dangerous tools will prompt again.", "#a6e3a1")
            return
        if sub in ("log", "audit", "history"):
            tail = yolomod.tail(30)
            self._append_bubble("purr", f"**yolo-actions.log (last 30)**\n\n```\n{tail}\n```", "#cdd6f4")
            return
        # no subcommand — show status
        if self.config.yolo_mode:
            self._append_bubble(
                "purr",
                "⚠ **YOLO MODE IS ON**\n\n"
                "Every dangerous tool runs without prompting. Actions logged to "
                "`~/.purr/logs/yolo-actions.log`.\n\n"
                "Commands:\n"
                "  `/yolo off`  — disable (instant, no confirm)\n"
                "  `/yolo log`  — show recent actions",
                "#f38ba8",
            )
        else:
            self._append_bubble(
                "purr",
                "**YOLO mode is OFF** (safe default).\n\n"
                "When ON, all dangerous tools run without prompting. "
                "Use this only when you trust the active agent's prompt fully.\n\n"
                "Commands:\n"
                "  `/yolo on`  → `/yolo confirm`  — enable (two-step)\n"
                "  `/yolo off`                     — disable (instant)\n"
                "  `/yolo log`                     — show recent audit log",
                "#cdd6f4",
            )

    def _cmd_history(self, args: list[str]) -> None:
        """List past chat sessions under ~/.purr/chats/.

        Usage:
          /history           — all sessions, newest first
          /history foo       — filter to sessions whose first user message contains "foo"
          /history agent     — filter to sessions for a specific agent
        """
        from purr.history import list_sessions
        search = " ".join(args).strip() if args else ""
        agent_filter = None
        sessions = list_sessions()
        # if the search term is exactly an agent name, filter by agent
        if search and self.agents.get(search):
            sessions = list_sessions(agent=search)
        elif search:
            needle = search.lower()
            sessions = [
                s for s in sessions
                if needle in s["title"].lower()
                or needle in s["agent"].lower()
                or needle in s["session_id"].lower()
            ]
        if not sessions:
            self._append_bubble("purr", "📜 no past chats found." if not search else f"📜 no past chats match `{search}`.", "#a6e3a1")
            return
        # remember the listed set so /resume N can pick from it
        self._last_history_list = sessions
        lines = [f"📜 **{len(sessions)} past chat{'s' if len(sessions) != 1 else ''}**", ""]
        # cap display to the most recent 20 — `/resume` still works on the
        # full list because we stored it
        for i, s in enumerate(sessions[:20], 1):
            import datetime as _dt
            try:
                when = _dt.datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
            except Exception:
                when = "?"
            glyph = {
                "friend": "(♥.♥)",
                "assistant": "(=^.^=)",
                "planner": "(☼.☼)",
                "sysadmin": "(>_>)",
                "general": "(◉_◉)",
            }.get(self.agents.get(s["agent"]).category if self.agents.get(s["agent"]) else "general", "(◉_◉)")
            title = s["title"].replace("\n", " ")[:60]
            lines.append(f"  `{i:>2}`. {glyph} **{s['agent']}** · {s['message_count']} msg · {when}")
            lines.append(f"      {title}")
        if len(sessions) > 20:
            lines.append(f"\n  …{len(sessions) - 20} more (use `/resume N` for any)")
        lines.append("\n  Type `/resume N` to open the Nth one in a new tab.")
        self._append_bubble("purr", "\n".join(lines), "#cdd6f4")

    def _cmd_resume(self, args: list[str]) -> None:
        """Resume a past chat session from the last /history listing."""
        if not args or not args[0].isdigit():
            self._append_bubble("purr", "usage: `/resume N` — N is the number from `/history`", "#f38ba8")
            return
        n = int(args[0])
        sessions = getattr(self, "_last_history_list", None)
        if not sessions:
            from purr.history import list_sessions
            sessions = list_sessions()
        if n < 1 or n > len(sessions):
            self._append_bubble("purr", f"only {len(sessions)} sessions — pick 1..{len(sessions)}", "#f38ba8")
            return
        target = sessions[n - 1]
        # open a new tab loaded with this session
        try:
            from purr.history import load_session
            agent, msgs = load_session(target["path"])
        except Exception as e:
            self._append_bubble("purr", f"couldn't load session: {e}", "#f38ba8")
            return
        # save current tab, create new one pointing at the loaded history
        self._sync_tab_from_current()
        new = TabState.new(agent, self.current_model)
        new.agent_name = agent
        new.title = target["title"] or f"resumed {agent} chat"
        new.history_path = target["path"]
        # re-render the loaded messages
        new.chat_md = self._render_history_to_md(msgs)
        self.tabs.append(new)
        self.current_tab_idx = len(self.tabs) - 1
        self._sync_current_from_tab()
        self._refresh_chrome()
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()
        self._append_bubble(
            "purr",
            f"📑 resumed **{agent}** session ({target['message_count']} messages) in tab {self.current_tab_idx+1}.",
            "#a6e3a1",
        )

    def _cmd_forgive(self) -> None:
        """Clear the strike counter on the current tab and unlock if locked.

        The user is explicitly forgiving past lies — usually after reading
        the audit log and deciding the model was actually right (or after
        switching to a better prompt).
        """
        tab = self.tabs[self.current_tab_idx]
        was_locked = tab.locked
        old_count = tab.lie_count
        tab.lie_count = 0
        tab.locked = False
        if old_count == 0:
            self._append_bubble("purr", "no strikes to forgive. you're a forgiving soul. 🕊️", "#a6e3a1")
            return
        msg = f"🕊️  forgiven — cleared {old_count} strike{'s' if old_count != 1 else ''} on this tab."
        if was_locked:
            msg += " Tab unlocked. Tool calls work again."
        self._append_bubble("purr", msg, "#a6e3a1")
        self._refresh_chrome()

    def _cmd_lies(self) -> None:
        """Show the last 20 entries from the lies audit log."""
        from purr import lies as liesmod
        tail = liesmod.tail(20)
        self._append_bubble("purr", f"**lies.log (last 20)**\n\n```\n{tail}\n```", "#cdd6f4")

    def _cmd_copy(self, args: list[str]) -> None:
        """Copy a recent assistant message to the system clipboard.
          /copy            — last assistant message
          /copy last       — same as no arg
          /copy N          — Nth most recent assistant message (1-indexed)
          /copy all        — entire chat as plain text
          /copy selection  — currently selected text in the chat widget
                              (if the terminal supports it)
        """
        # pull assistant messages newest first
        messages = self.history.load() or self.history.messages
        assistants = [m for m in messages if m.role == "assistant" and m.content]
        if not assistants:
            self._append_bubble("purr", "no assistant message to copy yet.", "#f38ba8")
            return

        sub = (args[0].lower() if args else "last")
        if sub in ("last", ""):
            text = assistants[-1].content
            label = "last assistant message"
        elif sub.isdigit():
            n = int(sub)
            if n < 1 or n > len(assistants):
                self._append_bubble(
                    "purr",
                    f"only {len(assistants)} assistant message{'s' if len(assistants) != 1 else ''} — pick 1..{len(assistants)}",
                    "#f38ba8",
                )
                return
            text = assistants[-n].content
            label = f"assistant message #{n} from the end"
        elif sub == "all":
            lines = []
            for m in messages:
                if m.role == "user":
                    lines.append(f"YOU: {m.content}\n")
                elif m.role == "assistant" and m.content:
                    lines.append(f"ASSISTANT: {m.content}\n")
                elif m.role == "tool":
                    lines.append(f"[tool:{m.tool_name}] {m.content}\n")
            text = "\n".join(lines)
            label = f"full chat ({len(messages)} message{'s' if len(messages) != 1 else ''})"
        elif sub in ("selection", "sel"):
            # try Textual's selection mechanism
            sel = getattr(self.screen, "selection", None) or getattr(self, "selection", None)
            if not sel:
                self._append_bubble(
                    "purr",
                    "no active text selection — your terminal may not support "
                    "mouse selection in Textual. Use `/copy last` instead, or "
                    "select in tmux with `prefix [` then space+arrows.",
                    "#f38ba8",
                )
                return
            text = str(sel)
            label = "selected text"
        else:
            self._append_bubble(
                "purr",
                "usage: `/copy [last|N|all|selection]`\n"
                "  no arg    — copy the last assistant message\n"
                "  N         — copy the Nth most recent assistant message\n"
                "  all       — copy the entire chat as plain text\n"
                "  selection — copy whatever's currently selected in the TUI",
                "#f38ba8",
            )
            return

        # write to clipboard — macOS pbcopy, Linux xclip/wl-copy, Windows clip
        import platform, shutil, subprocess
        system = platform.system()
        cmds: list[list[str]] = []
        if system == "Darwin":
            cmds = [["pbcopy"]]
        elif system == "Windows":
            cmds = [["clip"]]
        else:
            for c in (["xclip", "-selection", "clipboard"], ["wl-copy"], ["xsel", "--clipboard", "--input"]):
                if shutil.which(c[0]):
                    cmds = [c]
                    break

        if not cmds:
            self._append_bubble(
                "purr",
                f"📋 {label} ({len(text):,} chars) — no clipboard tool found, "
                f"printing below:\n\n```\n{text[:2000]}{'…' if len(text) > 2000 else ''}\n```",
                "#cdd6f4",
            )
            return

        try:
            proc = subprocess.run(cmds[0], input=text.encode("utf-8"), check=True)
            preview = text[:80].replace("\n", " ⏎ ")
            more = "…" if len(text) > 80 else ""
            self._append_bubble(
                "purr",
                f"📋 copied {label} to clipboard ({len(text):,} chars)\n\n"
                f"  preview: `{preview}{more}`\n\n"
                f"paste with `⌘V` or `/copy selection` to grab something else.",
                "#a6e3a1",
            )
        except Exception as e:
            self._append_bubble(
                "purr",
                f"❌ clipboard write failed: {e}\n\n"
                f"({label}, {len(text):,} chars — first 400 below)\n\n"
                f"```\n{text[:400]}\n```",
                "#f38ba8",
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
        # refuse to proceed if the tab is locked from too many lies
        tab = self.tabs[self.current_tab_idx]
        if tab.locked:
            self._append_bubble(
                "purr",
                f"🔒 **tab locked after {tab.lie_count} lies.** "
                f"I won't send this message — the model has earned a timeout. "
                f"Run `/forgive` to unlock, or open a fresh tab with `Ctrl+T`.",
                "#f38ba8",
            )
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
            sys_prompt = current.system_prompt + _PURR_UNIVERSAL_RULES
            messages: list[dict] = [{"role": "system", "content": sys_prompt}]
            for m in history[-self.config.max_history_messages:]:
                if m.role in ("user", "assistant", "tool"):
                    d = {"role": m.role, "content": m.content}
                    if m.tool_name:
                        d["name"] = m.tool_name
                    messages.append(d)
            messages.append({"role": "user", "content": user_text})
            self.history.append(ChatMessage(role="user", content=user_text))

            # track tool calls made during this user turn so we can detect
            # when the assistant's prose claims an action but no tool backed it
            tools_called_this_turn: list[str] = []

            # tool schemas
            tool_specs = toolmod.specs_for(current.tools)
            schemas = toolmod.schemas_for(current.tools) if tool_specs else None

            # start timer for response-time tracking
            import time as _time
            _resp_start = _time.monotonic()

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
                    # detect "I have saved..." style claims that were NOT
                    # backed by a tool call this turn. The model is lying —
                    # enforce consequences, not a soft warning.
                    lie_claim: str | None = None
                    if not tools_called_this_turn and full_text.strip():
                        lie_claim = _detect_uncalled_claim(full_text)

                    if lie_claim:
                        # LIE: render with strike-through, drop from history,
                        # increment tab strike count, log, possibly lock.
                        self._enforce_lie_consequence(full_text, lie_claim)
                        # don't append to history, don't append to messages
                        self._bubble_anchor = -1
                        self._last_response_seconds = _time.monotonic() - _resp_start
                        self._last_response_tokens = sum(
                            max(1, len(m.get("content", "")) // 4) for m in messages
                        )
                        self._refresh_chrome()
                        break

                    # HONEST: replace the in-progress bubble with the final one
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

                    # record response time + token estimate
                    self._last_response_seconds = _time.monotonic() - _resp_start
                    self._last_response_tokens = sum(
                        max(1, len(m.get("content", "")) // 4) for m in messages
                    )
                    self._refresh_chrome()
                    break

                # handle tool calls
                self._bubble_anchor = -1
                assistant_msg: dict = {"role": "assistant", "content": full_text, "tool_calls": pending_tool_calls}
                messages.append(assistant_msg)
                self.history.append(ChatMessage(role="assistant", content=full_text, tool_calls=pending_tool_calls))

                for tc in pending_tool_calls:
                    fn = tc.get("function") or {}
                    tool_name = fn.get("name", "")
                    tools_called_this_turn.append(tool_name)
                    raw_args = fn.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except Exception:
                            args = {"_raw": raw_args}
                    else:
                        args = dict(raw_args)

                    # dangerous-tool confirmation — skip if yolo is on
                    if (
                        self.config.confirm_dangerous_tools
                        and not self.config.yolo_mode
                        and toolmod.is_dangerous_tool(tool_name)
                    ):
                        ok = await self._confirm(f"agent wants to run dangerous tool `{tool_name}`\n  args: `{json.dumps(args)[:300]}`\n\nallow?")
                        if not ok:
                            result = "⛔ user denied this tool call"
                        else:
                            result = toolmod.call(tool_name, **args)
                    else:
                        result = toolmod.call(tool_name, **args)
                        if toolmod.is_dangerous_tool(tool_name) and self.config.yolo_mode:
                            yolomod.record(tool_name, args, result)

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

    def action_regenerate(self) -> None:
        """Regenerate the last assistant response. Ctrl+R.

        Pops the last user+assistant pair from history and re-runs the
        user message against the model. If the model was mid-stream and
        the last message is incomplete, we cancel and regenerate.
        """
        if self._busy:
            self._append_bubble("purr", "can't regenerate while a response is streaming. Wait for it to finish or hit Ctrl+C.", "#f38ba8")
            return
        msgs = self.history.load()
        if not msgs:
            self._append_bubble("purr", "nothing to regenerate — chat is empty.", "#f38ba8")
            return
        # find the last user message
        last_user_idx = None
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].role == "user" and msgs[i].content:
                last_user_idx = i
                break
        if last_user_idx is None:
            self._append_bubble("purr", "no user message found to regenerate from.", "#f38ba8")
            return
        last_user_text = msgs[last_user_idx].content
        # truncate the JSONL file to before that user message
        # (we rewrite the file from the messages we want to keep)
        keep = msgs[:last_user_idx]
        try:
            with open(self.history.path, "w", encoding="utf-8") as f:
                import json as _json
                for m in keep:
                    rec: dict = {"ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"), "role": m.role, "content": m.content}
                    if m.tool_calls:
                        rec["tool_calls"] = m.tool_calls
                    if m.tool_name:
                        rec["tool_name"] = m.tool_name
                    f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            self._append_bubble("purr", f"couldn't truncate history: {e}", "#f38ba8")
            return
        # re-render chat from the truncated history
        self._chat_md = self._render_history_to_md(keep)
        self.query_one("#chat", TextualMarkdown).update(self._chat_md)
        self._scroll_to_bottom()
        # re-send the last user message
        self._append_bubble("purr", "↻ regenerating…", "#a6e3a1")
        self._chat(last_user_text)

    def _render_history_to_md(self, msgs: list) -> str:
        """Build the chat-md source from a list of messages (for regenerate)."""
        parts: list[str] = []
        for m in msgs:
            if m.role == "user":
                parts.append(f"**(◉_◉) you**\n\n{m.content}\n")
            elif m.role == "assistant" and m.content:
                glyph = ascii_art.agent_glyph(self.active_agent.name)
                parts.append(f"**{glyph} {self.active_agent.title}**\n\n{m.content}\n")
            elif m.role == "tool":
                parts.append(f"🔧  `{m.tool_name}`\n\n    {m.content}\n")
        return "\n".join(parts)

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
        try:
            self.query_one(TabBar).render_for(self)
        except Exception:
            pass
