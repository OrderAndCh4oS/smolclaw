import asyncio
import contextlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style


@dataclass
class TranscriptEntry:
    kind: str
    text: str
    title: str = ""


@dataclass
class UiState:
    label: str = "smolclaw"
    mode: str = "coder"
    input_mode: str = "insert"
    model: str = "model"
    cwd: str = "."
    git_state: str = "git:unknown"
    goal_state: str = ""
    token_total: int = 0
    active_tool: str = "idle"
    safety_state: str = "safety:gated"
    run_state: str = "idle"
    status_message: str = ""
    transcript: list[TranscriptEntry] = field(default_factory=list)


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
    if width <= 1:
        return value[:width]
    return value if len(value) <= width else value[: width - 1] + "…"


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
            cwd=_compact_path(self.workspace_root),
            git_state=_git_state(self.workspace_root),
            safety_state="safety:gated" if getattr(agent, "safety_state", None) is not None else "safety:n/a",
        )
        self.input_buffer = Buffer(multiline=True)
        self._transcript_window: Window | None = None
        self._app: Application | None = None
        self._agent_task: asyncio.Task | None = None
        self._invalidate_handle = None

    async def run(self):
        self._refresh_goal_state()
        self._append("system", "SmolClaw ready. Type /help for commands, /quit to exit.")
        self._app = self._build_app()
        try:
            await self._app.run_async()
        finally:
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
                self.state.status_message = "stop requested"
                request_stop = getattr(self.agent, "request_stop", None)
                if callable(request_stop):
                    request_stop()
                self._invalidate()
            else:
                event.app.exit()

        @key_bindings.add("c-d")
        def _(event):
            if not self.input_buffer.text:
                event.app.exit()

        @key_bindings.add("pageup")
        def _(event):
            if self._transcript_window is not None:
                self._transcript_window.vertical_scroll = max(0, self._transcript_window.vertical_scroll - 10)
                self._invalidate()

        @key_bindings.add("pagedown")
        def _(event):
            if self._transcript_window is not None:
                self._transcript_window.vertical_scroll += 10
                self._invalidate()

        @key_bindings.add("c-q")
        def _(event):
            event.app.exit()

        self._transcript_window = Window(
            FormattedTextControl(self._render_transcript),
            wrap_lines=True,
            always_hide_cursor=True,
        )
        input_area = VSplit([
            Window(
                FormattedTextControl([("class:prompt", "> ")]),
                width=2,
                dont_extend_width=True,
                align=WindowAlign.LEFT,
            ),
            Window(
                BufferControl(buffer=self.input_buffer),
                height=Dimension(min=1, max=5),
                wrap_lines=True,
            ),
        ], height=Dimension(min=1, max=5))
        root = HSplit([
            Window(FormattedTextControl(self._render_top_bar), height=1, style="class:bar.top"),
            self._transcript_window,
            Window(FormattedTextControl(self._render_bottom_bar), height=1, style="class:bar.bottom"),
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
        self.state.status_message = "storing memory"
        self._invalidate()
        try:
            result = await self.memory_store_tool.execute(content=command_arg)
            self._append("system", str(result))
        finally:
            self.state.run_state = "idle"
            self.state.status_message = ""
            self._invalidate()

    async def _handle_remember_thread(self):
        self.state.run_state = "running"
        self.state.status_message = "exporting thread"
        self._invalidate()
        try:
            await self.session_export_hook({
                "session_key": self.agent.session.key,
                "session": self.agent.session,
            })
            self._append("system", "Current thread exported to memory.")
        finally:
            self.state.run_state = "idle"
            self.state.status_message = ""
            self._invalidate()

    async def _start_agent_turn(self, prompt: str):
        if self._agent_task is not None and not self._agent_task.done():
            self._append("system", "Agent is already running.")
            return
        self._agent_task = asyncio.create_task(self._run_agent_turn(prompt))
        await self._agent_task

    async def _run_agent_turn(self, prompt: str):
        self.state.run_state = "running"
        self.state.status_message = ""
        self.state.active_tool = "idle"
        assistant_entry = TranscriptEntry(kind="assistant", title="smolclaw", text="")
        self.state.transcript.append(assistant_entry)
        self._invalidate()

        async def on_output(chunk: str):
            assistant_entry.text += chunk
            self._invalidate_throttled()

        async def on_event(event: dict):
            await self._handle_agent_event(event)

        try:
            response = await self.agent.process(
                prompt,
                on_output=on_output,
                on_event=on_event if self.show_actions else None,
            )
            if not assistant_entry.text.strip() and response:
                assistant_entry.text = response
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._append("error", f"Error: {exc}")
        finally:
            if not assistant_entry.text.strip():
                with contextlib.suppress(ValueError):
                    self.state.transcript.remove(assistant_entry)
            self.state.run_state = "idle"
            self.state.active_tool = "idle"
            self.state.status_message = ""
            self._refresh_goal_state()
            self.state.git_state = _git_state(self.workspace_root)
            self._invalidate()

    async def _handle_agent_event(self, event: dict):
        if event.get("type") == "llm":
            if event.get("phase") == "start":
                self.state.run_state = "thinking"
                self.state.status_message = "thinking"
            elif event.get("phase") == "end":
                self.state.run_state = "running"
                self.state.status_message = ""
                self.state.token_total += int(event.get("total_tokens") or 0)
                model = event.get("model")
                if model:
                    self.state.model = str(model)
            line = self.format_action_event(event)
            if line:
                self._append("system", line)
            self._invalidate()
            return
        if event.get("type") == "tool":
            name = str(event.get("name") or "tool")
            if event.get("phase") == "start":
                self.state.active_tool = name
            elif event.get("phase") == "end":
                self.state.active_tool = "idle"
            line = self.format_action_event(event)
            if line:
                self._append("tool", line)
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
        self.state.transcript.append(TranscriptEntry(kind=kind, text=text, title=title))
        self._invalidate()

    def _refresh_goal_state(self):
        goal = self.goal_store.load(self.agent.session.key)
        if goal is None:
            self.state.goal_state = ""
        elif goal.status == "active":
            self.state.goal_state = f"goal:{goal.turn_count}"
        else:
            self.state.goal_state = f"goal:{goal.status}"

    def _render_top_bar(self) -> StyleAndTextTuples:
        width = shutil.get_terminal_size((100, 24)).columns
        parts = [
            self.state.label,
            self.state.mode,
            self.state.model,
            self.state.cwd,
            self.state.git_state,
        ]
        if self.state.goal_state:
            parts.append(self.state.goal_state)
        return [("", _truncate("  " + "  ".join(parts), width))]

    def _render_bottom_bar(self) -> StyleAndTextTuples:
        width = shutil.get_terminal_size((100, 24)).columns
        tokens = f"tok:{self.state.token_total:,}" if self.state.token_total else "tok:0"
        parts = [
            self.state.input_mode,
            tokens,
            f"tools:{self.state.active_tool}",
            self.state.safety_state,
            self.state.run_state,
        ]
        if self.state.status_message:
            parts.append(self.state.status_message)
        return [("", _truncate("  " + "  ".join(parts), width))]

    def _render_transcript(self) -> StyleAndTextTuples:
        output: StyleAndTextTuples = []
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
                output.append((style, f"{entry.text}\n"))
                continue
            if entry.kind == "system":
                output.append((style, f"{entry.text}\n\n"))
                continue
            output.append((style, f"{title}\n"))
            output.append(("", f"{entry.text.rstrip()}\n\n"))
        if not output:
            output.append(("class:text.dim", ""))
        return output

    def _invalidate(self):
        if self._transcript_window is not None:
            self._transcript_window.vertical_scroll = 10**9
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
