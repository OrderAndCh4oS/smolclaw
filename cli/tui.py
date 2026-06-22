import asyncio
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, ScrollOffsets, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style

from app import diagnostics
from app.model_settings import (
    apply_subagent_model_selection,
    apply_runtime_model_selection,
    get_reasoning_effort,
    model_help,
    model_list,
    model_status,
    parse_model_selection,
    subagent_model_status,
)

SPINNER_FRAMES = ("|", "/", "-", "\\")
DETAILS_HEIGHT = 4
MAX_ACTIVITY_ENTRIES = 80


@dataclass
class TranscriptEntry:
    kind: str
    text: str
    title: str = ""


@dataclass
class ActivityEntry:
    kind: str
    text: str


@dataclass
class UiState:
    label: str = "smolclaw"
    mode: str = "coder"
    input_mode: str = "insert"
    model: str = "model"
    reasoning_effort: str = ""
    cwd: str = "."
    git_state: str = "git:unknown"
    goal_state: str = ""
    token_total: int = 0
    active_tool: str = "idle"
    activity: str = "idle"
    spinner_index: int = 0
    safety_state: str = "safety:gated"
    run_state: str = "idle"
    details_visible: bool = False
    transcript: list[TranscriptEntry] = field(default_factory=list)
    activity_log: list[ActivityEntry] = field(default_factory=list)


def _compact_path(path: str, max_len: int = 36) -> str:
    path = os.path.abspath(os.path.expanduser(path))
    home = os.path.expanduser("~")
    if path == home:
        path = "~"
    elif path.startswith(home + os.sep):
        path = "~" + path[len(home):]
    if len(path) <= max_len:
        return path
    parts = path.split(os.sep)
    if len(parts) <= 2:
        return path[-max_len:]
    tail = os.sep.join(parts[-2:])
    return f"...{os.sep}{tail}"[-max_len:]


def _truncate(value: str, width: int) -> str:
    value = value.replace("\n", " ")
    if width <= 1:
        return value[:width]
    return value if len(value) <= width else value[: width - 3] + "..."


def _fit_line(value: str, width: int) -> str:
    if width <= 0:
        return ""
    return _truncate(value, width).ljust(width)


def _git_state(cwd: str) -> str:
    try:
        branch = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        ).stdout.strip()
        if not branch:
            commit = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            ).stdout.strip()
            branch = commit or "detached"
        dirty = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        ).stdout.strip()
    except Exception:
        return "git:n/a"
    return f"git:{branch}{'*' if dirty else ''}"


class CoderTui:
    def __init__(
        self,
        *,
        agent,
        goal_store,
        session_manager,
        memory_store_tool,
        session_export_hook,
        smol_rag,
        workspace_root: str,
        model: str,
        auto_export: bool,
        show_actions: bool,
        slash_commands_help: str,
        format_goal_status: Callable[[object], str],
        parse_goal_run_count: Callable[[str], int],
        build_goal_loop_prompt: Callable[[], str],
        format_action_event: Callable[[dict], Optional[str]],
        label: str = "smolclaw",
    ):
        self.agent = agent
        self.goal_store = goal_store
        self.session_manager = session_manager
        self.memory_store_tool = memory_store_tool
        self.session_export_hook = session_export_hook
        self.smol_rag = smol_rag
        self.workspace_root = os.path.abspath(os.path.expanduser(workspace_root))
        self.auto_export = auto_export
        self.show_actions = show_actions
        self.slash_commands_help = slash_commands_help
        self.format_goal_status = format_goal_status
        self.parse_goal_run_count = parse_goal_run_count
        self.build_goal_loop_prompt = build_goal_loop_prompt
        self.format_action_event = format_action_event
        self.state = UiState(
            label=label,
            model=getattr(getattr(agent, "llm", None), "completion_model", None) or model,
            reasoning_effort=get_reasoning_effort(getattr(agent, "llm", None)) or "",
            cwd=_compact_path(self.workspace_root),
            git_state=_git_state(self.workspace_root),
            safety_state="safety:gated" if getattr(agent, "safety_state", None) is not None else "safety:n/a",
            details_visible=show_actions,
        )
        self.input_buffer = Buffer(multiline=True)
        self._transcript_window: Window | None = None
        self._app: Application | None = None
        self._agent_task: asyncio.Task | None = None
        self._spinner_task: asyncio.Task | None = None
        self._invalidate_handle = None
        self._pending_llm_output = ""
        self._scroll_offset = 0
        self._terminal_log_handler = logging.NullHandler()

    async def run(self):
        self._refresh_goal_state()
        self._append("system", "SmolClaw ready. Type /help for commands, /quit to exit.")
        self._app = self._build_app()
        self._spinner_task = asyncio.create_task(self._animate_spinner())
        try:
            with self._suppress_terminal_logs(), self._handle_loop_exceptions(), self._capture_stderr():
                await self._app.run_async()
        finally:
            if self._spinner_task is not None:
                self._spinner_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._spinner_task
            await self._shutdown()

    def _build_app(self) -> Application:
        key_bindings = KeyBindings()

        @key_bindings.add("enter")
        def _(event):
            text = self.input_buffer.text.strip()
            if not text:
                return
            self.input_buffer.set_document(Document(""))
            asyncio.create_task(self.submit(text))

        @key_bindings.add("escape", "enter")
        @key_bindings.add("c-j")
        def _(event):
            self.input_buffer.insert_text("\n")

        @key_bindings.add("c-c")
        def _(event):
            if self.state.run_state in {"running", "thinking"}:
                self.state.run_state = "stopping"
                self.state.activity = "stopping"
                request_stop = getattr(self.agent, "request_stop", None)
                if callable(request_stop):
                    request_stop()
                self._invalidate()
            else:
                event.app.exit()

        @key_bindings.add("pageup")
        def _(event):
            self._scroll_page(up=True)

        @key_bindings.add("pagedown")
        def _(event):
            self._scroll_page(up=False)

        @key_bindings.add(Keys.ScrollUp)
        @key_bindings.add(Keys.ShiftUp)
        def _(event):
            self._scroll_lines(3)

        @key_bindings.add(Keys.ScrollDown)
        @key_bindings.add(Keys.ShiftDown)
        def _(event):
            self._scroll_lines(-3)

        @key_bindings.add("c-u")
        def _(event):
            self._scroll_page(up=True)

        @key_bindings.add("c-d")
        def _(event):
            if not self.input_buffer.text:
                event.app.exit()
                return
            self._scroll_page(up=False)

        @key_bindings.add("c-q")
        def _(event):
            event.app.exit()

        self._transcript_window = Window(
            FormattedTextControl(self._render_transcript),
            wrap_lines=False,
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        details_window = ConditionalContainer(
            Window(
                FormattedTextControl(self._render_details),
                height=Dimension.exact(DETAILS_HEIGHT),
                wrap_lines=False,
                always_hide_cursor=True,
                dont_extend_height=True,
                ignore_content_height=True,
                style="class:details",
            ),
            filter=Condition(lambda: self.state.details_visible),
        )
        input_window = Window(
            BufferControl(buffer=self.input_buffer),
            height=Dimension.exact(3),
            wrap_lines=True,
            dont_extend_height=True,
            ignore_content_height=True,
            scroll_offsets=ScrollOffsets(top=0, bottom=0),
        )
        input_area = VSplit([
            Window(
                FormattedTextControl([("class:prompt", "> ")]),
                width=2,
                height=Dimension.exact(3),
                dont_extend_width=True,
                dont_extend_height=True,
                ignore_content_height=True,
                align=WindowAlign.LEFT,
            ),
            input_window,
        ], height=Dimension.exact(3))
        root = HSplit([
            Window(
                FormattedTextControl(self._render_top_bar),
                height=Dimension.exact(1),
                dont_extend_height=True,
                ignore_content_height=True,
                style="class:bar.top",
            ),
            self._transcript_window,
            details_window,
            Window(
                FormattedTextControl(self._render_bottom_bar),
                height=Dimension.exact(1),
                dont_extend_height=True,
                ignore_content_height=True,
                style="class:bar.bottom",
            ),
            input_area,
        ])
        style = Style.from_dict({
            "bar.top": "reverse",
            "bar.bottom": "reverse",
            "prompt": "ansigreen bold",
            "role.user": "ansicyan bold",
            "role.assistant": "ansigreen bold",
            "role.system": "ansibrightblack",
            "role.tool": "ansiyellow",
            "role.error": "ansired bold",
            "text.dim": "ansibrightblack",
            "details": "ansibrightblack",
            "details.title": "ansibrightblack reverse",
            "details.tool": "ansiyellow",
            "details.error": "ansired",
        })
        return Application(
            layout=Layout(root, focused_element=input_area),
            key_bindings=key_bindings,
            full_screen=True,
            mouse_support=True,
            style=style,
        )

    async def submit(self, text: str):
        self._append("user", text, title="you")
        command_parts = text.split(maxsplit=1)
        command = command_parts[0]
        command_arg = command_parts[1].strip() if len(command_parts) > 1 else ""

        if command in ("/", "/help", "/commands"):
            self._append("system", self.slash_commands_help)
            return
        if text in ("/quit", "/exit"):
            if self._app is not None:
                self._app.exit()
            return
        if text == "/clear":
            self.agent.session.clear()
            self.session_manager.save(self.agent.session)
            self.state.transcript.clear()
            self._append("system", "Session cleared.")
            return
        if text == "/logs":
            self._append("system", self._diagnostics_paths())
            return
        if command == "/model":
            self._handle_model(command_arg)
            return
        if text == "/details":
            self.state.details_visible = not self.state.details_visible
            state = "shown" if self.state.details_visible else "hidden"
            self._append("system", f"Tool details {state}.")
            return
        if command == "/goal":
            await self._handle_goal(command_arg)
            return
        if command == "/remember":
            await self._handle_remember(command_arg)
            return
        if command == "/remember-thread":
            await self._handle_remember_thread()
            return

        await self._start_agent_turn(text)

    async def _handle_goal(self, command_arg: str):
        sub_parts = command_arg.split(maxsplit=1)
        subcommand = sub_parts[0] if sub_parts else "status"
        sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""
        session_key = self.agent.session.key
        if subcommand in ("", "status"):
            self._append("system", self.format_goal_status(self.goal_store.load(session_key)))
            self._refresh_goal_state()
            return
        if subcommand == "start":
            if not sub_arg:
                self._append("system", "Usage: /goal start <objective>")
                return
            goal = self.goal_store.start(session_key, sub_arg)
            self._append("system", f"Goal set: {goal.objective}")
            self._refresh_goal_state()
            return
        if subcommand == "complete":
            try:
                goal = self.goal_store.update(session_key, status="complete", note=sub_arg)
            except ValueError as exc:
                self._append("error", f"Error: {exc}")
                return
            self._append("system", self.format_goal_status(goal))
            self._refresh_goal_state()
            return
        if subcommand == "block":
            try:
                goal = self.goal_store.update(session_key, status="blocked", note=sub_arg)
            except ValueError as exc:
                self._append("error", f"Error: {exc}")
                return
            self._append("system", self.format_goal_status(goal))
            self._refresh_goal_state()
            return
        if subcommand == "clear":
            removed = self.goal_store.clear(session_key)
            self._append("system", "Goal cleared." if removed else "No goal was set.")
            self._refresh_goal_state()
            return
        if subcommand == "run":
            try:
                max_turns = self.parse_goal_run_count(sub_arg)
            except Exception as exc:
                self._append("error", str(exc))
                return
            goal = self.goal_store.load(session_key)
            if goal is None or goal.status != "active":
                self._append("system", "No active goal to run.")
                self._refresh_goal_state()
                return
            for turn_index in range(max_turns):
                goal = self.goal_store.load(session_key)
                if goal is None or goal.status != "active":
                    break
                self._append("system", f"Goal turn {turn_index + 1}/{max_turns}")
                await self._start_agent_turn(self.build_goal_loop_prompt())
                goal = self.goal_store.load(session_key)
                if goal is None:
                    self._append("system", "Goal cleared.")
                    break
                if goal.status != "active":
                    self._append("system", self.format_goal_status(goal))
                    break
            self._refresh_goal_state()
            return
        self._append("system", "Usage: /goal status|start|run|complete|block|clear")

    async def _handle_remember(self, command_arg: str):
        if not command_arg:
            self._append("system", "Usage: /remember <text>")
            return
        self.state.run_state = "running"
        self.state.activity = "storing"
        self._invalidate()
        try:
            result = await self.memory_store_tool.execute(content=command_arg)
            self._append("system", str(result))
        finally:
            self.state.run_state = "idle"
            self.state.activity = "idle"
            self._invalidate()

    async def _handle_remember_thread(self):
        self.state.run_state = "running"
        self.state.activity = "exporting"
        self._invalidate()
        try:
            await self.session_export_hook({
                "session_key": self.agent.session.key,
                "session": self.agent.session,
            })
            self._append("system", "Current thread exported to memory.")
        finally:
            self.state.run_state = "idle"
            self.state.activity = "idle"
            self._invalidate()

    async def _start_agent_turn(self, prompt: str):
        if self._agent_task is not None and not self._agent_task.done():
            self._append("system", "Agent is already running.")
            return
        self._agent_task = asyncio.create_task(self._run_agent_turn(prompt))
        await self._agent_task

    async def _run_agent_turn(self, prompt: str):
        self.state.run_state = "running"
        self.state.active_tool = "idle"
        self.state.activity = "running"
        self._pending_llm_output = ""
        assistant_entry = TranscriptEntry(kind="assistant", title="smolclaw", text="")
        self.state.transcript.append(assistant_entry)
        self._invalidate()

        async def on_output(chunk: str):
            self._pending_llm_output += chunk
            self._invalidate_throttled()

        async def on_event(event: dict):
            await self._handle_agent_event(event)

        try:
            response = await self.agent.process(
                prompt,
                on_output=on_output,
                on_event=on_event,
            )
            if self._pending_llm_output and not assistant_entry.text.strip():
                self._flush_pending_llm_output(has_tool_calls=False)
            if not assistant_entry.text.strip() and response:
                assistant_entry.text = response
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            incident_id = diagnostics.record_exception(
                exc,
                boundary="tui.agent_turn",
                session_key=getattr(getattr(self.agent, "session", None), "key", ""),
            )
            self._append("error", diagnostics.user_error_message(incident_id, str(exc)))
        finally:
            if not assistant_entry.text.strip():
                with contextlib.suppress(ValueError):
                    self.state.transcript.remove(assistant_entry)
            self.state.run_state = "idle"
            self.state.active_tool = "idle"
            self.state.activity = "idle"
            self._refresh_goal_state()
            self.state.git_state = _git_state(self.workspace_root)
            self._invalidate()

    async def _handle_agent_event(self, event: dict):
        if event.get("type") == "llm":
            if event.get("phase") == "start":
                self.state.run_state = "thinking"
                self.state.activity = "thinking"
                self._pending_llm_output = ""
            elif event.get("phase") == "end":
                self.state.run_state = "running"
                self.state.activity = "running"
                self.state.token_total += int(event.get("total_tokens") or 0)
                model = event.get("model")
                if model:
                    self.state.model = str(model)
                self.state.reasoning_effort = get_reasoning_effort(self.agent.llm) or ""
                self._flush_pending_llm_output(has_tool_calls=bool(event.get("has_tool_calls")))
            line = self.format_action_event(event)
            if line:
                self._record_activity("system", line)
            self._invalidate()
            return
        if event.get("type") == "tool":
            name = str(event.get("name") or "tool")
            if event.get("phase") == "start":
                self._flush_pending_llm_output(has_tool_calls=True)
                self.state.active_tool = name
                self.state.activity = self._activity_label(name)
            elif event.get("phase") == "end":
                self.state.active_tool = "idle"
                self.state.activity = "running"
            line = self.format_action_event(event)
            if line:
                self._record_activity("tool", line)
            self._invalidate()

    async def _shutdown(self):
        if self._agent_task is not None and not self._agent_task.done():
            request_stop = getattr(self.agent, "request_stop", None)
            if callable(request_stop):
                request_stop()
            self._agent_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._agent_task
        try:
            if self.auto_export:
                await self.agent.close()
            else:
                await self.agent.close()
        finally:
            close_fn = getattr(self.smol_rag, "close", None)
            if callable(close_fn):
                result = close_fn()
                if asyncio.iscoroutine(result):
                    await result

    def _append(self, kind: str, text: str, title: str = ""):
        self._scroll_offset = 0
        self.state.transcript.append(TranscriptEntry(kind=kind, text=text, title=title))
        self._invalidate()

    def _record_activity(self, kind: str, text: str):
        self.state.activity_log.append(ActivityEntry(kind=kind, text=text))
        if len(self.state.activity_log) > MAX_ACTIVITY_ENTRIES:
            del self.state.activity_log[: len(self.state.activity_log) - MAX_ACTIVITY_ENTRIES]

    def _flush_pending_llm_output(self, *, has_tool_calls: bool):
        if not self._pending_llm_output:
            return
        text = self._pending_llm_output
        self._pending_llm_output = ""
        if has_tool_calls:
            self._record_activity("system", text.strip())
            return
        assistant_entry = self._current_assistant_entry()
        if assistant_entry is not None:
            assistant_entry.text += text
            self._scroll_offset = 0

    def _current_assistant_entry(self) -> TranscriptEntry | None:
        if not self.state.transcript:
            return None
        entry = self.state.transcript[-1]
        return entry if entry.kind == "assistant" else None

    def _handle_model(self, command_arg: str):
        if not command_arg:
            self._append("system", model_help(self.agent.llm, getattr(self.agent, "model_settings", None)))
            return
        if command_arg == "list":
            self._append("system", model_list())
            return
        subagent_parts = command_arg.split(maxsplit=1)
        if subagent_parts[0] == "subagents":
            model_settings = getattr(self.agent, "model_settings", None)
            if len(subagent_parts) == 1:
                self._append("system", subagent_model_status(model_settings))
                return
            try:
                selection = parse_model_selection(subagent_parts[1])
            except ValueError as exc:
                self._append("error", f"Error: {exc}")
                return
            apply_subagent_model_selection(selection, model_settings)
            self._append("system", f"Switched {subagent_model_status(model_settings)}")
            return
        try:
            selection = parse_model_selection(command_arg)
        except ValueError as exc:
            self._append("error", f"Error: {exc}")
            return
        apply_runtime_model_selection(self.agent.llm, selection, getattr(self.agent, "model_settings", None))
        self.state.model = selection.model
        self.state.reasoning_effort = get_reasoning_effort(self.agent.llm) or ""
        self._append("system", f"Switched {model_status(self.agent.llm)}")

    def _refresh_goal_state(self):
        goal = self.goal_store.load(self.agent.session.key)
        if goal is None:
            self.state.goal_state = ""
        elif goal.status == "active":
            self.state.goal_state = f"goal:{goal.turn_count}"
        else:
            self.state.goal_state = f"goal:{goal.status}"

    def _render_top_bar(self) -> StyleAndTextTuples:
        width = self._terminal_width()
        parts = [
            self.state.label,
            self.state.mode,
            self.state.model,
        ]
        if self.state.reasoning_effort:
            parts.append(f"effort:{self.state.reasoning_effort}")
        parts.extend([
            self.state.cwd,
            self.state.git_state,
        ])
        if self.state.goal_state:
            parts.append(self.state.goal_state)
        return [("", _fit_line("  " + "  ".join(parts), width))]

    def _render_bottom_bar(self) -> StyleAndTextTuples:
        width = self._terminal_width()
        tokens = f"tok:{self.state.token_total:,}" if self.state.token_total else "tok:0"
        parts = [
            self.state.input_mode,
            tokens,
            f"tools:{self.state.active_tool}",
            self.state.safety_state,
            f"spin:{self._spinner_frame()}",
            f"details:{'on' if self.state.details_visible else 'off'}",
            f"status:{self.state.activity}",
        ]
        return [("", _fit_line("  " + "  ".join(parts), width))]

    def _render_details(self) -> StyleAndTextTuples:
        width = self._terminal_width()
        body_height = DETAILS_HEIGHT - 1
        title = _fit_line("  details  /details to hide", width)
        lines = self._activity_lines(width)
        visible = lines[-body_height:] if body_height > 0 else []

        output: StyleAndTextTuples = [("class:details.title", f"{title}\n")]
        output.extend((style, f"{line}\n") for style, line in visible)
        missing_rows = body_height - len(visible)
        if missing_rows > 0:
            output.append(("class:details", "\n" * missing_rows))
        return output

    def _render_transcript(self) -> StyleAndTextTuples:
        width = self._terminal_width()
        height = self._transcript_height()
        lines = self._transcript_lines(width)
        if not lines:
            return [("class:text.dim", "")]

        self._scroll_offset = min(self._scroll_offset, max(0, len(lines) - height))
        end = max(0, len(lines) - self._scroll_offset)
        start = max(0, end - height)
        visible = lines[start:end]

        output: StyleAndTextTuples = []
        for style, line in visible:
            output.append((style, f"{line}\n"))
        missing_rows = height - len(visible)
        if missing_rows > 0:
            output.append(("", "\n" * missing_rows))
        return output

    def _transcript_lines(self, width: int) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        text_width = max(1, width)
        for entry in self.state.transcript:
            style = {
                "user": "class:role.user",
                "assistant": "class:role.assistant",
                "system": "class:role.system",
                "tool": "class:role.tool",
                "error": "class:role.error",
            }.get(entry.kind, "")
            title = entry.title or entry.kind
            if entry.kind == "tool":
                lines.extend(self._wrap_lines(entry.text, text_width, style))
                continue
            if entry.kind == "system":
                lines.extend(self._wrap_lines(entry.text, text_width, style))
                lines.append(("", ""))
                continue
            lines.append((style, title))
            lines.extend(self._wrap_lines(entry.text.rstrip(), text_width, ""))
            lines.append(("", ""))
        return lines

    def _activity_lines(self, width: int) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        text_width = max(1, width)
        for entry in self.state.activity_log:
            style = {
                "system": "class:details",
                "tool": "class:details.tool",
                "error": "class:details.error",
            }.get(entry.kind, "class:details")
            if entry.text.startswith("failed:"):
                style = "class:details.error"
            lines.extend(self._wrap_lines(entry.text, text_width, style))
        return lines

    def _wrap_lines(self, text: str, width: int, style: str) -> list[tuple[str, str]]:
        wrapped: list[tuple[str, str]] = []
        for raw_line in text.splitlines() or [""]:
            chunks = textwrap.wrap(
                raw_line,
                width=max(1, width),
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [""]
            wrapped.extend((style, chunk) for chunk in chunks)
        return wrapped

    def _invalidate(self):
        if self._app is not None:
            self._app.invalidate()

    def _invalidate_throttled(self):
        if self._app is None:
            return
        if self._invalidate_handle is not None:
            return
        loop = asyncio.get_running_loop()

        def _flush():
            self._invalidate_handle = None
            self._invalidate()

        self._invalidate_handle = loop.call_later(0.05, _flush)

    def _terminal_width(self) -> int:
        if self._app is not None:
            with contextlib.suppress(Exception):
                return max(1, int(self._app.output.get_size().columns))
        return max(1, int(shutil.get_terminal_size((100, 24)).columns))

    def _terminal_height(self) -> int:
        if self._app is not None:
            with contextlib.suppress(Exception):
                return max(1, int(self._app.output.get_size().rows))
        return max(1, int(shutil.get_terminal_size((100, 24)).lines))

    def _transcript_height(self) -> int:
        details_height = DETAILS_HEIGHT if self.state.details_visible else 0
        return max(1, self._terminal_height() - 5 - details_height)

    def _max_scroll_offset(self) -> int:
        return max(0, len(self._transcript_lines(self._terminal_width())) - self._transcript_height())

    def _scroll_lines(self, delta: int):
        self._scroll_offset = min(
            self._max_scroll_offset(),
            max(0, self._scroll_offset + delta),
        )
        self._invalidate()

    def _scroll_page(self, *, up: bool):
        page = max(1, self._transcript_height() - 1)
        self._scroll_lines(page if up else -page)

    def _activity_label(self, tool_name: str) -> str:
        name = tool_name.lower()
        if "search" in name or "grep" in name or "find" in name:
            return "searching"
        if "fetch" in name or "web" in name:
            return "fetching"
        if "read" in name or "recall" in name:
            return "reading"
        if "write" in name or "edit" in name or "patch" in name:
            return "editing"
        if "git" in name:
            return "checking"
        if "memory" in name:
            return "remembering"
        return name

    def _spinner_frame(self) -> str:
        if self.state.activity == "idle":
            return "."
        return SPINNER_FRAMES[self.state.spinner_index % len(SPINNER_FRAMES)]

    async def _animate_spinner(self):
        while True:
            await asyncio.sleep(0.2)
            if self.state.activity == "idle":
                if self.state.spinner_index != 0:
                    self.state.spinner_index = 0
                    self._invalidate()
                continue
            self.state.spinner_index = (self.state.spinner_index + 1) % len(SPINNER_FRAMES)
            self._invalidate()

    def _diagnostics_paths(self) -> str:
        log_dir = os.path.join(self.workspace_root, "stores", "logs")
        return "\n".join([
            f"Diagnostics logs: {log_dir}",
            f"Events: {os.path.join(log_dir, 'events.jsonl')}",
            f"Text log: {os.path.join(log_dir, 'smolclaw.log')}",
        ])

    @contextlib.contextmanager
    def _suppress_terminal_logs(self):
        loggers = [
            logging.getLogger("app"),
            logging.getLogger("smolclaw"),
            logging.getLogger("mini-rag"),
        ]
        previous_propagation = {logger: logger.propagate for logger in loggers}
        for logger in loggers:
            logger.addHandler(self._terminal_log_handler)
            logger.propagate = False
        try:
            yield
        finally:
            for logger in loggers:
                with contextlib.suppress(ValueError):
                    logger.removeHandler(self._terminal_log_handler)
                logger.propagate = previous_propagation[logger]

    @contextlib.contextmanager
    def _handle_loop_exceptions(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()

        def _handler(_loop, context):
            exception = context.get("exception")
            if exception is None:
                exception = RuntimeError(str(context.get("message") or "Unhandled error"))
            incident_id = diagnostics.record_exception(
                exception,
                boundary="tui.event_loop",
                session_key=getattr(getattr(self.agent, "session", None), "key", ""),
            )
            self._append("error", diagnostics.user_error_message(incident_id, str(exception)))

        loop.set_exception_handler(_handler)
        try:
            yield
        finally:
            loop.set_exception_handler(previous_handler)

    @contextlib.contextmanager
    def _capture_stderr(self):
        previous_stderr = sys.stderr
        loop = asyncio.get_running_loop()
        buffer: list[str] = []

        def _emit(text: str):
            clean = text.strip()
            if clean:
                incident_id = diagnostics.record_exception(
                    RuntimeError(clean),
                    boundary="tui.stderr",
                    session_key=getattr(getattr(self.agent, "session", None), "key", ""),
                )
                self._append("error", diagnostics.user_error_message(incident_id, clean))

        class _TuiStderr:
            encoding = getattr(previous_stderr, "encoding", "utf-8")
            errors = getattr(previous_stderr, "errors", "replace")

            def write(self, text):
                if not isinstance(text, str):
                    text = str(text)
                buffer.append(text)
                return len(text)

            def flush(self):
                if not buffer:
                    return
                joined = "".join(buffer)
                buffer.clear()
                loop.call_soon_threadsafe(_emit, joined)

            def isatty(self):
                return False

            def fileno(self):
                return previous_stderr.fileno()

        sys.stderr = _TuiStderr()
        try:
            yield
        finally:
            sys.stderr.flush()
            sys.stderr = previous_stderr
