import asyncio
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import threading
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
from app.approvals import ApprovalRequest, format_approval_detail, format_approval_review_option
from app.checkpoints import CheckpointStore
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
from app.pricing import format_costs
from app.work_loop import WorkLoopJobSupervisor, terminate_active_work_loop_processes
from app.workspace import WorkspaceContext
from cli.commands import (
    GOAL_COMMAND_HELP,
    SLASH_COMMANDS_HELP,
    SlashCommandDispatcher,
    _format_diagnostics_paths,
    _format_goal_started,
    _format_inferred_goal_started,
    _format_undo_result,
    infer_goal_from_thread,
    _parse_goal_command,
    parse_slash_command,
)

SPINNER_FRAMES = ("|", "/", "-", "\\")
DETAILS_HEIGHT = 4
APPROVAL_PANEL_HEIGHT = 10
APPROVAL_REVIEW_OPTIONS = (
    ("approve", "Approve once", "Allow this exact tool call one time."),
    ("deny", "Deny", "Reject this pending tool call."),
    ("info", "Provide or request further information", "Close this dialog and type context or a question."),
    ("detail", "Show exact request details", "Print the full approval request in the transcript."),
    ("close", "Close", "Leave the request pending."),
)
MAX_ACTIVITY_ENTRIES = 80
TRANSCRIPT_RENDER_MARGIN = 80
SHUTDOWN_PHASE_TIMEOUT = 8.0
ACTIVE_RUN_STATES = {
    "running",
    "thinking",
    "storing",
    "exporting",
    "initializing",
    "tracing",
    "approving",
    "checking",
    "undoing",
    "clearing",
    "loading",
    "stopping",
    "shutting_down",
}
_TASK_FAILED = object()


class _WorkerLoop:
    """Dedicated event loop for agent/tool work that should not starve rendering."""

    def __init__(self):
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run, name="smolclaw-tui-worker", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    def submit(self, awaitable: Awaitable):
        if self._loop is None:
            raise RuntimeError("worker loop is not ready")
        return asyncio.run_coroutine_threadsafe(awaitable, self._loop)

    def stop(self):
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)


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
class _WrappedEntryCache:
    signature: tuple[str, str, str]
    width: int
    lines: list[tuple[str, str]]


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
    session_cost: dict = field(default_factory=lambda: {"totals": {}, "unknown_calls": 0, "unknown_models": []})
    active_tool: str = "idle"
    activity: str = "idle"
    spinner_index: int = 0
    safety_state: str = "safety:gated"
    run_state: str = "idle"
    details_visible: bool = False
    approval_review_visible: bool = False
    approval_review_index: int = 0
    approval_choice_index: int = 0
    approval_review_items: list[ApprovalRequest] = field(default_factory=list)
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


def _git_state(cwd: str, command_runner=subprocess.run) -> str:
    try:
        branch = command_runner(
            ["git", "-C", cwd, "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        ).stdout.strip()
        if not branch:
            commit = command_runner(
                ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            ).stdout.strip()
            branch = commit or "detached"
        dirty = command_runner(
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
        checkpoint_store: CheckpointStore,
        approval_store,
        workspace_root: str,
        log_dir: str,
        model: str,
        auto_export: bool,
        show_actions: bool,
        slash_commands_help: str,
        format_goal_status: Callable[[object], str],
        parse_goal_run_count: Callable[[str], int],
        build_goal_loop_prompt: Callable[[], str],
        build_memory_review_prompt: Callable[[str], str],
        format_trace_status: Callable[[str, str], str],
        resolve_approval_command: Callable[[str, str], str],
        resolve_memory_command: Callable[[str], object],
        initialize_project: Callable[[], str],
        format_action_event: Callable[[dict], Optional[str]],
        resolve_worktree_command: Callable[[str], str] | None = None,
        resolve_work_loop_command: Callable[[str], str] | None = None,
        terminal_size_provider: Callable[[tuple[int, int]], os.terminal_size] | None = None,
        shutdown_phase_timeout: float = SHUTDOWN_PHASE_TIMEOUT,
        git_state_provider: Callable[[str], str] | None = None,
        label: str = "smolclaw",
    ):
        self.agent = agent
        self.goal_store = goal_store
        self.session_manager = session_manager
        self.memory_store_tool = memory_store_tool
        self.session_export_hook = session_export_hook
        self.smol_rag = smol_rag
        self.checkpoint_store = checkpoint_store
        self.approval_store = approval_store
        self.workspace_root = os.path.abspath(os.path.expanduser(workspace_root))
        self.log_dir = os.path.abspath(os.path.expanduser(log_dir))
        self.auto_export = auto_export
        self.show_actions = show_actions
        self.slash_commands_help = slash_commands_help
        self.format_goal_status = format_goal_status
        self.parse_goal_run_count = parse_goal_run_count
        self.build_goal_loop_prompt = build_goal_loop_prompt
        self.build_memory_review_prompt = build_memory_review_prompt
        self.format_trace_status = format_trace_status
        self.resolve_approval_command = resolve_approval_command
        self.resolve_memory_command = resolve_memory_command
        self.resolve_worktree_command = resolve_worktree_command or (lambda arg: "No active isolated worktree.")
        self.resolve_work_loop_command = resolve_work_loop_command or (lambda arg: "Work-loop commands are unavailable.")
        self.terminal_size_provider = terminal_size_provider or shutil.get_terminal_size
        self.shutdown_phase_timeout = shutdown_phase_timeout
        self.git_state_provider = git_state_provider or _git_state
        self.initialize_project = initialize_project
        self.format_action_event = format_action_event
        self.state = UiState(
            label=label,
            model=getattr(getattr(agent, "llm", None), "completion_model", None) or model,
            reasoning_effort=get_reasoning_effort(getattr(agent, "llm", None)) or "",
            cwd=_compact_path(self.workspace_root),
            git_state="git:loading",
            safety_state="safety:gated" if getattr(agent, "safety_state", None) is not None else "safety:n/a",
            details_visible=show_actions,
        )
        self.input_buffer = Buffer(multiline=True)
        self._transcript_window: Window | None = None
        self._app: Application | None = None
        self._ui_loop: asyncio.AbstractEventLoop | None = None
        self._worker_loop: _WorkerLoop | None = None
        self._agent_task: asyncio.Task | None = None
        self._goal_refresh_task: asyncio.Task | None = None
        self._git_refresh_task: asyncio.Task | None = None
        self._spinner_task: asyncio.Task | None = None
        self._shutdown_task: asyncio.Task | None = None
        self._invalidate_handle = None
        self._pending_llm_output = ""
        self._scroll_offset = 0
        self._transcript_cache: dict[int, _WrappedEntryCache] = {}
        self._activity_cache: dict[int, _WrappedEntryCache] = {}
        self._terminal_log_handler = logging.NullHandler()
        self._shutdown_started = False
        self._shutdown_complete = False
        self._shutdown_forced = False
        self._slash_dispatcher = self._build_slash_dispatcher()

    async def run(self):
        self._ui_loop = asyncio.get_running_loop()
        self._append("system", "SmolClaw ready. Type /help for commands, /quit to exit.")
        self._app = self._build_app()
        self._schedule_goal_refresh()
        self._schedule_git_refresh()
        self._spinner_task = asyncio.create_task(self._animate_spinner())
        try:
            with self._suppress_terminal_logs(), self._handle_loop_exceptions(), self._capture_stderr():
                await self._app.run_async()
        finally:
            await self._shutdown()
            if self._goal_refresh_task is not None and not self._goal_refresh_task.done():
                self._goal_refresh_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._goal_refresh_task
            if self._git_refresh_task is not None and not self._git_refresh_task.done():
                self._git_refresh_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._git_refresh_task
            if self._spinner_task is not None:
                self._spinner_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._spinner_task

    def _build_app(self) -> Application:
        key_bindings = KeyBindings()
        approval_review_visible = Condition(lambda: self.state.approval_review_visible)

        @key_bindings.add("enter")
        def _(event):
            text = self.input_buffer.text.strip()
            if self.state.approval_review_visible and not text:
                asyncio.create_task(self._choose_selected_approval_option())
                return
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
            if self.state.run_state in (ACTIVE_RUN_STATES - {"stopping", "shutting_down"}):
                self.state.run_state = "stopping"
                self.state.activity = "stopping"
                request_stop = getattr(self.agent, "request_stop", None)
                if callable(request_stop):
                    request_stop()
                self._invalidate()
            elif self.state.run_state in {"stopping", "shutting_down"}:
                self._force_exit()
            else:
                self._begin_exit()

        @key_bindings.add("pageup")
        def _(event):
            self._scroll_page(up=True)

        @key_bindings.add("pagedown")
        def _(event):
            self._scroll_page(up=False)

        @key_bindings.add("up", filter=approval_review_visible)
        def _(event):
            self._move_approval_choice(-1)

        @key_bindings.add("down", filter=approval_review_visible)
        def _(event):
            self._move_approval_choice(1)

        @key_bindings.add("a", filter=approval_review_visible)
        def _(event):
            asyncio.create_task(self._resolve_selected_approval("approve"))

        @key_bindings.add("d", filter=approval_review_visible)
        def _(event):
            asyncio.create_task(self._resolve_selected_approval("deny"))

        @key_bindings.add("escape", filter=approval_review_visible)
        def _(event):
            self._close_approval_review()

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
                self._begin_exit()
                return
            self._scroll_page(up=False)

        @key_bindings.add("c-q")
        def _(event):
            self._begin_exit()

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
        approval_review_window = ConditionalContainer(
            Window(
                FormattedTextControl(self._render_approval_review),
                height=Dimension.exact(APPROVAL_PANEL_HEIGHT),
                wrap_lines=False,
                always_hide_cursor=True,
                dont_extend_height=True,
                ignore_content_height=True,
                style="class:approval",
            ),
            filter=approval_review_visible,
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
            approval_review_window,
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
            "approval": "ansibrightblack",
            "approval.title": "reverse",
            "approval.selected": "reverse",
            "approval.action": "ansigreen bold reverse",
            "approval.danger": "ansired bold reverse",
        })
        return Application(
            layout=Layout(root, focused_element=input_area),
            key_bindings=key_bindings,
            full_screen=True,
            mouse_support=True,
            style=style,
        )

    def _is_active(self) -> bool:
        if self.state.run_state in ACTIVE_RUN_STATES:
            return True
        if self._agent_task is not None and not self._agent_task.done():
            return True
        if self._shutdown_task is not None and not self._shutdown_task.done():
            return True
        return False

    def _reject_if_active(self, command: str) -> bool:
        if not self._is_active():
            return False
        self._append("system", f"{command} is unavailable while {self.state.activity}.")
        return True

    async def _run_status_task(
        self,
        *,
        activity: str,
        active_tool: str,
        boundary: str,
        worker_fn: Callable[[], object],
        user_error_exceptions: tuple[type[Exception], ...] = (),
    ):
        self.state.run_state = activity
        self.state.activity = activity
        self.state.active_tool = active_tool
        self._invalidate()
        try:
            return await self._run_in_worker(worker_fn)
        except asyncio.CancelledError:
            raise
        except user_error_exceptions as exc:
            self._append("error", f"Error: {exc}")
            return _TASK_FAILED
        except Exception as exc:
            incident_id = diagnostics.record_exception(
                exc,
                boundary=boundary,
                session_key=getattr(getattr(self.agent, "session", None), "key", ""),
            )
            self._append("error", diagnostics.user_error_message(incident_id, str(exc)))
            return _TASK_FAILED
        finally:
            self.state.run_state = "idle"
            self.state.activity = "idle"
            self.state.active_tool = "idle"
            self._invalidate()

    def _schedule_git_refresh(self):
        if self._app is None:
            return
        if self._shutdown_started or self._shutdown_forced:
            return
        if self._git_refresh_task is not None and not self._git_refresh_task.done():
            return
        self.state.git_state = "git:loading"
        self._git_refresh_task = asyncio.create_task(self._refresh_git_state())
        self._invalidate()

    def _schedule_goal_refresh(self):
        if self._app is None:
            return
        if self._shutdown_started or self._shutdown_forced:
            return
        if self._goal_refresh_task is not None and not self._goal_refresh_task.done():
            return
        self._goal_refresh_task = asyncio.create_task(self._refresh_goal_state())

    async def _refresh_git_state(self):
        try:
            git_state = await self._run_in_worker(lambda: self.git_state_provider(self.workspace_root))
        except asyncio.CancelledError:
            raise
        except Exception:
            git_state = "git:n/a"
        self.state.git_state = git_state
        self._invalidate()

    def _build_slash_dispatcher(self) -> SlashCommandDispatcher:
        dispatcher = SlashCommandDispatcher()

        @dispatcher.register("/", "/help", "/commands")
        async def _dispatch_help(parsed):
            self._append("system", self.slash_commands_help or SLASH_COMMANDS_HELP)
            return True

        @dispatcher.register("/quit", "/exit")
        async def _dispatch_exit(parsed):
            self._begin_exit()
            return True

        @dispatcher.register("/logs")
        async def _dispatch_logs(parsed):
            self._append("system", self._diagnostics_paths())
            return True

        @dispatcher.register("/details")
        async def _dispatch_details(parsed):
            self.state.details_visible = not self.state.details_visible
            state = "shown" if self.state.details_visible else "hidden"
            self._append("system", f"Tool details {state}.")
            return True

        return dispatcher

    async def submit(self, text: str):
        if self._ui_loop is None:
            self._ui_loop = asyncio.get_running_loop()
        self._append("user", text, title="you")
        parsed = parse_slash_command(text)
        command = parsed.name
        command_arg = parsed.arg

        if await self._slash_dispatcher.dispatch(parsed):
            return

        work_loop_control = command == "/work-loop" and command_arg.split(maxsplit=1)[0:1] in (
            ["stop"],
            ["pause"],
            ["resume"],
            ["state"],
            ["control"],
        )
        if work_loop_control:
            self._append("system", str(self.resolve_work_loop_command(command_arg)))
            return

        if command.startswith("/") and self._reject_if_active(command):
            return

        if text == "/clear":
            result = await self._run_status_task(
                activity="clearing",
                active_tool="session",
                boundary="tui.clear",
                worker_fn=self._clear_session,
            )
            if result is not _TASK_FAILED:
                self.state.transcript.clear()
                self._invalidate_transcript_cache()
                self._append("system", str(result))
            return
        if text == "/init":
            result = await self._run_status_task(
                activity="initializing",
                active_tool="init",
                boundary="tui.init",
                worker_fn=self.initialize_project,
            )
            if result is not _TASK_FAILED:
                self._append("system", str(result))
            return
        if command == "/trace":
            result = await self._run_status_task(
                activity="tracing",
                active_tool="trace",
                boundary="tui.trace",
                worker_fn=lambda: self.format_trace_status(self.agent.session.key, command_arg),
            )
            if result is not _TASK_FAILED:
                self._append("system", str(result))
            return
        if command == "/approval":
            if command_arg.split(maxsplit=1)[0:1] == ["review"]:
                await self._open_approval_review()
                return
            result = await self._run_status_task(
                activity="approving",
                active_tool="approval",
                boundary="tui.approval",
                worker_fn=lambda: self.resolve_approval_command(self.agent.session.key, command_arg),
            )
            if result is not _TASK_FAILED:
                self._append("system", str(result))
            return
        if command == "/memory":
            memory_parts = command_arg.split(maxsplit=1)
            memory_subcommand = memory_parts[0] if memory_parts else "status"
            memory_sub_arg = memory_parts[1].strip() if len(memory_parts) > 1 else ""
            if memory_subcommand in {"review", "reconcile"}:
                if getattr(self.smol_rag, "contradiction_detector", None) is None:
                    result = await self._run_status_task(
                        activity="reviewing",
                        active_tool="memory",
                        boundary="tui.memory",
                        worker_fn=lambda: self.resolve_memory_command(command_arg),
                    )
                    if result is not _TASK_FAILED:
                        self._append("system", str(result))
                    return
                await self._start_agent_turn(self.build_memory_review_prompt(memory_sub_arg))
                return
            result = await self._run_status_task(
                activity="reviewing",
                active_tool="memory",
                boundary="tui.memory",
                worker_fn=lambda: self.resolve_memory_command(command_arg),
            )
            if result is not _TASK_FAILED:
                self._append("system", str(result))
            return
        if command == "/worktree":
            result = await self._run_status_task(
                activity="checking",
                active_tool="worktree",
                boundary="tui.worktree",
                worker_fn=lambda: self.resolve_worktree_command(command_arg),
            )
            if result is not _TASK_FAILED:
                self._append("system", str(result))
            if command_arg.split(maxsplit=1)[0:1] in (["apply"], ["discard"]):
                self._schedule_git_refresh()
            return
        if command == "/work-loop":
            result = await self._run_status_task(
                activity="checking",
                active_tool="work-loop",
                boundary="tui.work_loop",
                worker_fn=lambda: self.resolve_work_loop_command(command_arg),
            )
            if result is not _TASK_FAILED:
                self._append("system", str(result))
            return
        if text == "/undo":
            await self._handle_undo()
            return
        if command == "/model":
            self._handle_model(command_arg)
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

        if self._reject_if_active("Agent input"):
            return
        await self._start_agent_turn(text)

    def _clear_session(self) -> str:
        self.agent.session.clear()
        self.session_manager.save(self.agent.session)
        return "Session cleared."

    async def _handle_goal(self, command_arg: str):
        subcommand, sub_arg = _parse_goal_command(command_arg)
        session_key = self.agent.session.key
        if subcommand == "help":
            self._append("system", GOAL_COMMAND_HELP)
            return
        if subcommand in ("", "status"):
            goal = await self._run_status_task(
                activity="loading",
                active_tool="goal",
                boundary="tui.goal",
                worker_fn=lambda: self.goal_store.load(session_key),
            )
            if goal is _TASK_FAILED:
                return
            self._append("system", self.format_goal_status(goal))
            self._apply_goal_state(goal)
            return
        if subcommand == "infer":
            try:
                inferred = await self._run_status_task(
                    activity="loading",
                    active_tool="goal",
                    boundary="tui.goal",
                    worker_fn=lambda: infer_goal_from_thread(self.agent.llm, self.agent.session.messages),
                    user_error_exceptions=(ValueError,),
                )
            except ValueError as exc:
                self._append("error", str(exc))
                return
            if inferred is _TASK_FAILED:
                return
            goal = await self._run_status_task(
                activity="loading",
                active_tool="goal",
                boundary="tui.goal",
                worker_fn=lambda: self.goal_store.start(
                    session_key,
                    inferred.objective,
                    acceptance_criteria=inferred.acceptance_criteria,
                ),
                user_error_exceptions=(ValueError,),
            )
            if goal is _TASK_FAILED:
                return
            self._append("system", _format_inferred_goal_started(goal, inferred))
            self._apply_goal_state(goal)
            return
        if subcommand == "start":
            if not sub_arg:
                self._append("system", GOAL_COMMAND_HELP)
                return
            goal = await self._run_status_task(
                activity="loading",
                active_tool="goal",
                boundary="tui.goal",
                worker_fn=lambda: self.goal_store.start(session_key, sub_arg),
                user_error_exceptions=(ValueError,),
            )
            if goal is _TASK_FAILED:
                return
            self._append("system", _format_goal_started(goal))
            self._apply_goal_state(goal)
            return
        if subcommand == "complete":
            goal = await self._run_goal_update(session_key, "complete", sub_arg)
            if goal is _TASK_FAILED:
                return
            self._append("system", self.format_goal_status(goal))
            self._apply_goal_state(goal)
            return
        if subcommand == "block":
            goal = await self._run_goal_update(session_key, "blocked", sub_arg)
            if goal is _TASK_FAILED:
                return
            self._append("system", self.format_goal_status(goal))
            self._apply_goal_state(goal)
            return
        if subcommand == "clear":
            removed = await self._run_status_task(
                activity="clearing",
                active_tool="goal",
                boundary="tui.goal",
                worker_fn=lambda: self.goal_store.clear(session_key),
            )
            if removed is _TASK_FAILED:
                return
            self._append("system", "Goal cleared." if removed else "No goal was set.")
            self._apply_goal_state(None)
            return
        if subcommand == "run":
            try:
                max_turns = self.parse_goal_run_count(sub_arg)
            except Exception as exc:
                self._append("error", str(exc))
                return
            goal = await self._load_goal(session_key)
            if goal is _TASK_FAILED:
                return
            if goal is None or goal.status != "active":
                self._append("system", "No active goal to run.")
                self._apply_goal_state(goal)
                return
            for turn_index in range(max_turns):
                goal = await self._load_goal(session_key)
                if goal is _TASK_FAILED:
                    return
                if goal is None or goal.status != "active":
                    break
                self._append("system", f"Goal turn {turn_index + 1}/{max_turns}")
                await self._start_agent_turn(self.build_goal_loop_prompt())
                goal = await self._load_goal(session_key)
                if goal is _TASK_FAILED:
                    return
                if goal is None:
                    self._append("system", "Goal cleared.")
                    break
                if goal.status != "active":
                    self._append("system", self.format_goal_status(goal))
                    break
            self._apply_goal_state(goal)
            return
        self._append("system", GOAL_COMMAND_HELP)

    async def _load_goal(self, session_key: str):
        return await self._run_status_task(
            activity="loading",
            active_tool="goal",
            boundary="tui.goal",
            worker_fn=lambda: self.goal_store.load(session_key),
        )

    async def _run_goal_update(self, session_key: str, status: str, note: str):
        return await self._run_status_task(
            activity="loading",
            active_tool="goal",
            boundary="tui.goal",
            worker_fn=lambda: self.goal_store.update(session_key, status=status, note=note),
            user_error_exceptions=(ValueError,),
        )

    async def _handle_remember(self, command_arg: str):
        if not command_arg:
            self._append("system", "Usage: /remember <text>")
            return
        result = await self._run_status_task(
            activity="storing",
            active_tool="memory",
            boundary="tui.remember",
            worker_fn=lambda: self.memory_store_tool.execute(content=command_arg),
        )
        if result is not _TASK_FAILED:
            self._append("system", str(result))

    async def _handle_remember_thread(self):
        self._append(
            "system",
            "Exporting current thread to memory. This can take a while on long sessions.",
        )
        result = await self._run_status_task(
            activity="exporting",
            active_tool="memory",
            boundary="tui.remember_thread",
            worker_fn=lambda: self.session_export_hook({
                "session_key": self.agent.session.key,
                "session": self.agent.session,
            }),
        )
        if result is not _TASK_FAILED:
            self._append("system", "Current thread exported to memory.")

    async def _handle_undo(self):
        result = await self._run_status_task(
            activity="undoing",
            active_tool="checkpoint",
            boundary="tui.undo",
            worker_fn=lambda: self.checkpoint_store.undo_last(session_key=self.agent.session.key),
        )
        if result is _TASK_FAILED:
            return
        self._append("system" if result.ok else "error", _format_undo_result(result))
        self._schedule_git_refresh()

    async def _open_approval_review(self, *, quiet_when_empty: bool = False):
        requests = await self._load_pending_approvals()
        if requests is _TASK_FAILED:
            return
        pending_requests = list(requests or [])
        if not pending_requests:
            self._close_approval_review()
            if not quiet_when_empty:
                self._append("system", "No pending approval requests.")
            return
        was_visible = self.state.approval_review_visible
        self.state.approval_review_items = pending_requests
        self.state.approval_review_index = min(
            self.state.approval_review_index,
            max(0, len(self.state.approval_review_items) - 1),
        )
        self.state.approval_choice_index = min(
            self.state.approval_choice_index,
            max(0, len(self._approval_options()) - 1),
        )
        self.state.approval_review_visible = True
        if not was_visible:
            self._append(
                "system",
                "Approval required. Use Up/Down to choose an option, Enter to select, Esc to leave pending.",
            )
        self._invalidate()

    async def _load_pending_approvals(self):
        return await self._run_status_task(
            activity="approving",
            active_tool="approval",
            boundary="tui.approval",
            worker_fn=lambda: self.approval_store.list(self.agent.session.key, status="pending"),
        )

    def _selected_approval(self) -> ApprovalRequest | None:
        if not self.state.approval_review_items:
            return None
        index = min(
            max(0, self.state.approval_review_index),
            len(self.state.approval_review_items) - 1,
        )
        self.state.approval_review_index = index
        return self.state.approval_review_items[index]

    def _move_approval_selection(self, delta: int):
        if not self.state.approval_review_items:
            return
        count = len(self.state.approval_review_items)
        self.state.approval_review_index = (self.state.approval_review_index + delta) % count
        self.state.approval_choice_index = 0
        self._invalidate()

    def _approval_options(self) -> tuple[tuple[str, str, str], ...]:
        options = list(APPROVAL_REVIEW_OPTIONS)
        if len(self.state.approval_review_items) > 1:
            options.insert(4, ("next", "Review next pending request", "Switch to the next approval request."))
        return tuple(options)

    def _selected_approval_option(self) -> tuple[str, str, str]:
        options = self._approval_options()
        if not options:
            return ("close", "Close", "Leave the request pending.")
        index = min(max(0, self.state.approval_choice_index), len(options) - 1)
        self.state.approval_choice_index = index
        return options[index]

    def _move_approval_choice(self, delta: int):
        options = self._approval_options()
        if not options:
            return
        self.state.approval_choice_index = (self.state.approval_choice_index + delta) % len(options)
        self._invalidate()

    def _close_approval_review(self):
        self.state.approval_review_visible = False
        self.state.approval_review_index = 0
        self.state.approval_choice_index = 0
        self.state.approval_review_items = []
        self._invalidate()

    async def _choose_selected_approval_option(self):
        option, _label, _description = self._selected_approval_option()
        if option == "approve":
            await self._resolve_selected_approval("approve")
            return
        if option == "deny":
            await self._resolve_selected_approval("deny")
            return
        if option == "detail":
            await self._show_selected_approval_detail()
            return
        if option == "info":
            self._close_approval_review()
            self._append(
                "system",
                "Approval left pending. Type the extra context or ask what information is needed.",
            )
            return
        if option == "next":
            self._move_approval_selection(1)
            return
        self._close_approval_review()
        self._append("system", "Approval request left pending.")

    async def _show_selected_approval_detail(self):
        request = self._selected_approval()
        if request is None:
            self._append("system", "No pending approval requests.")
            return
        result = await self._run_status_task(
            activity="approving",
            active_tool="approval",
            boundary="tui.approval",
            worker_fn=lambda: format_approval_detail(
                self.approval_store,
                self.agent.session.key,
                request.id,
            ),
        )
        if result is not _TASK_FAILED:
            self._append("system", str(result))

    async def _resolve_selected_approval(self, action: str):
        request = self._selected_approval()
        if request is None:
            self._append("system", "No pending approval requests.")
            return
        if action not in {"approve", "deny"}:
            self._append("error", f"Unsupported approval action: {action}")
            return
        if action == "approve":
            worker_fn = lambda: self.approval_store.approve(self.agent.session.key, request.id)
        else:
            worker_fn = lambda: self.approval_store.deny(self.agent.session.key, request.id)
        resolved = await self._run_status_task(
            activity="approving",
            active_tool="approval",
            boundary="tui.approval",
            worker_fn=worker_fn,
            user_error_exceptions=(KeyError,),
        )
        if resolved is _TASK_FAILED:
            return
        if action == "approve":
            self._append("system", f"Approved {resolved.id}. Retry the same tool call to continue.")
        else:
            self._append("system", f"Denied {resolved.id}.")
        refreshed = await self._load_pending_approvals()
        if refreshed is _TASK_FAILED:
            return
        if not refreshed:
            self._close_approval_review()
            self._append("system", "No pending approval requests.")
            return
        self.state.approval_review_items = list(refreshed)
        self.state.approval_review_index = min(
            self.state.approval_review_index,
            len(self.state.approval_review_items) - 1,
        )
        self.state.approval_choice_index = min(
            self.state.approval_choice_index,
            len(self._approval_options()) - 1,
        )
        self.state.approval_review_visible = True
        self._invalidate()

    async def _start_agent_turn(self, prompt: str):
        if self._agent_task is not None and not self._agent_task.done():
            self._append("system", "Agent is already running.")
            return
        self._agent_task = asyncio.create_task(self._run_agent_turn(prompt))
        await self._agent_task

    async def _run_agent_turn(self, prompt: str):
        if self._ui_loop is None:
            self._ui_loop = asyncio.get_running_loop()
        self.state.run_state = "running"
        self.state.active_tool = "idle"
        self.state.activity = "running"
        self._pending_llm_output = ""
        assistant_entry = TranscriptEntry(kind="assistant", title="smolclaw", text="")
        self.state.transcript.append(assistant_entry)
        self._invalidate()

        async def on_output(chunk: str):
            await self._run_on_ui(lambda: self._handle_output_chunk(chunk))

        async def on_event(event: dict):
            await self._run_on_ui(lambda: self._handle_agent_event(event))

        try:
            response = await self._run_in_worker(
                lambda: self.agent.process(
                    prompt,
                    on_output=on_output,
                    on_event=on_event,
                )
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
            await self._refresh_goal_state()
            await self._open_approval_review(quiet_when_empty=True)
            self._schedule_git_refresh()
            self._invalidate()

    async def _handle_output_chunk(self, chunk: str):
        self._pending_llm_output += chunk
        self._invalidate_throttled()

    async def _run_on_ui(self, coro_factory: Callable[[], Awaitable]):
        ui_loop = self._ui_loop
        if ui_loop is None:
            return await coro_factory()
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is ui_loop:
            return await coro_factory()
        future = asyncio.run_coroutine_threadsafe(coro_factory(), ui_loop)
        return await asyncio.wrap_future(future)

    async def _run_in_worker(self, coro_factory: Callable[[], object]):
        if self._worker_loop is None:
            self._worker_loop = _WorkerLoop()

        async def _call():
            result = coro_factory()
            if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                return await result
            return result

        future = self._worker_loop.submit(_call())
        return await asyncio.wrap_future(future)

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
                session_cost = event.get("session_estimated_cost")
                if isinstance(session_cost, dict):
                    self.state.session_cost = session_cost
                model = event.get("model")
                if model:
                    self.state.model = str(model)
                self.state.reasoning_effort = get_reasoning_effort(self.agent.llm) or ""
                self._flush_pending_llm_output(has_tool_calls=bool(event.get("has_tool_calls")))
            line = self.format_action_event(event)
            if line:
                self._record_activity("system", line)
            self._invalidate_throttled()
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
            self._invalidate_throttled()

    def _begin_exit(self):
        if self._shutdown_task is not None and not self._shutdown_task.done():
            self._set_shutdown_phase("Shutdown already in progress. Press Ctrl+C to force exit.")
            return
        self._shutdown_task = asyncio.create_task(self._graceful_exit())

    async def _graceful_exit(self):
        self._set_shutdown_phase("Shutdown requested.")
        try:
            await self._shutdown()
        finally:
            if self._app is not None:
                self._app.exit()

    def _force_exit(self):
        self._shutdown_forced = True
        self._shutdown_complete = True
        WorkLoopJobSupervisor.for_workspace(WorkspaceContext.from_root(self.workspace_root)).stop(
            "all",
            reason="Terminal force exit.",
            grace_seconds=0.5,
        )
        terminate_active_work_loop_processes()
        for task in (self._agent_task, self._shutdown_task):
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()
                task.add_done_callback(self._drain_task)
        self.state.run_state = "idle"
        self.state.activity = "idle"
        self.state.active_tool = "idle"
        self._record_activity("system", "Forced exit requested; cleanup was abandoned.")
        self._append("system", "Forced exit requested; cleanup was abandoned.")
        if self._app is not None:
            self._app.exit()
        self._invalidate()

    def _set_shutdown_phase(self, message: str, *, active_tool: str = "shutdown"):
        self.state.run_state = "shutting_down"
        self.state.activity = "shutting down"
        self.state.active_tool = active_tool
        self._record_activity("system", message)
        self._append("system", message)

    async def _shutdown(self):
        if self._shutdown_forced or self._shutdown_complete:
            return
        if self._shutdown_started:
            return
        self._shutdown_started = True
        if self._goal_refresh_task is not None and not self._goal_refresh_task.done():
            self._goal_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._goal_refresh_task
        if self._git_refresh_task is not None and not self._git_refresh_task.done():
            self._git_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._git_refresh_task
        if self._agent_task is not None and not self._agent_task.done():
            request_stop = getattr(self.agent, "request_stop", None)
            if callable(request_stop):
                request_stop()
            self._agent_task.cancel()
            await self._await_shutdown_step(
                "Stopping active agent turn.",
                self._agent_task,
                active_tool="agent",
            )
        try:
            await self._await_shutdown_step(
                "Closing agent session and hooks.",
                self._run_in_worker(lambda: self.agent.close()),
                active_tool="agent",
            )
        finally:
            if callable(getattr(self.smol_rag, "close", None)):
                await self._await_shutdown_step(
                    "Closing memory stores.",
                    self._run_in_worker(self._close_smol_rag),
                    active_tool="memory",
                )
            WorkLoopJobSupervisor.for_workspace(WorkspaceContext.from_root(self.workspace_root)).stop(
                "all",
                reason="Terminal shutdown.",
                grace_seconds=1.0,
            )
            terminate_active_work_loop_processes()
            if self._worker_loop is not None:
                self._worker_loop.stop()
                self._worker_loop = None
            if not self._shutdown_forced:
                self._shutdown_complete = True
                self.state.run_state = "idle"
                self.state.active_tool = "idle"
                self.state.activity = "idle"
                self._record_activity("system", "Shutdown complete.")
                self._invalidate()

    async def _close_smol_rag(self):
        close_fn = getattr(self.smol_rag, "close", None)
        if not callable(close_fn):
            return
        result = close_fn()
        if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
            await result

    async def _await_shutdown_step(self, message: str, awaitable, *, active_tool: str) -> bool:
        if self._shutdown_forced:
            return False
        self._set_shutdown_phase(message, active_tool=active_tool)
        task = awaitable if isinstance(awaitable, asyncio.Future) else asyncio.create_task(awaitable)
        done, _pending = await asyncio.wait({task}, timeout=self.shutdown_phase_timeout)
        if task not in done:
            task.cancel()
            task.add_done_callback(self._drain_task)
            self._set_shutdown_phase(
                f"Timed out while {message[0].lower() + message[1:].rstrip('.')}; continuing shutdown.",
                active_tool=active_tool,
            )
            return False
        try:
            await task
            return True
        except asyncio.CancelledError:
            return False
        except Exception as exc:
            incident_id = diagnostics.record_exception(
                exc,
                boundary="tui.shutdown",
                session_key=getattr(getattr(self.agent, "session", None), "key", ""),
            )
            self._append("error", diagnostics.user_error_message(incident_id, str(exc)))
            return False

    @staticmethod
    def _drain_task(task: asyncio.Future):
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.exception()

    def _invalidate_transcript_cache(self):
        self._transcript_cache.clear()

    def _invalidate_activity_cache(self):
        self._activity_cache.clear()

    def _append(self, kind: str, text: str, title: str = ""):
        self._scroll_offset = 0
        self.state.transcript.append(TranscriptEntry(kind=kind, text=text, title=title))
        self._invalidate_transcript_cache()
        self._invalidate()

    def _record_activity(self, kind: str, text: str):
        self.state.activity_log.append(ActivityEntry(kind=kind, text=text))
        if len(self.state.activity_log) > MAX_ACTIVITY_ENTRIES:
            del self.state.activity_log[: len(self.state.activity_log) - MAX_ACTIVITY_ENTRIES]
        self._invalidate_activity_cache()

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
            self._invalidate_transcript_cache()

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
        try:
            apply_runtime_model_selection(self.agent.llm, selection, getattr(self.agent, "model_settings", None))
        except ValueError as exc:
            self._append("error", f"Error: {exc}")
            return
        self.state.model = selection.model
        self.state.reasoning_effort = get_reasoning_effort(self.agent.llm) or ""
        self._append("system", f"Switched {model_status(self.agent.llm)}")

    async def _refresh_goal_state(self):
        try:
            goal = await self._run_in_worker(lambda: self.goal_store.load(self.agent.session.key))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            incident_id = diagnostics.record_exception(
                exc,
                boundary="tui.goal_refresh",
                session_key=getattr(getattr(self.agent, "session", None), "key", ""),
            )
            self._record_activity("error", diagnostics.user_error_message(incident_id, str(exc)))
            self._invalidate()
            return
        self._apply_goal_state(goal)
        self._invalidate()

    def _apply_goal_state(self, goal):
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
        cost_text = format_costs(self.state.session_cost, compact=True)
        parts = [
            self.state.input_mode,
            tokens,
            f"tools:{self.state.active_tool}",
            self.state.safety_state,
            f"spin:{self._spinner_frame()}",
            f"details:{'on' if self.state.details_visible else 'off'}",
            f"status:{self.state.activity}",
        ]
        if cost_text != "cost:0":
            parts.insert(2, cost_text)
        return [("", _fit_line("  " + "  ".join(parts), width))]

    def _render_approval_review(self) -> StyleAndTextTuples:
        width = self._terminal_width()
        items = self.state.approval_review_items
        count = len(items)
        title = _fit_line(f"  approval required  {count} pending", width)
        output: StyleAndTextTuples = [("class:approval.title", f"{title}\n")]
        if not items:
            output.append(("class:approval", f"{_fit_line('  No pending approval requests.', width)}\n"))
            output.append(("class:approval", "\n" * (APPROVAL_PANEL_HEIGHT - 2)))
            return output

        selected_request_index = min(max(0, self.state.approval_review_index), count - 1)
        selected_request = items[selected_request_index]
        request_line = format_approval_review_option(selected_request) if selected_request is not None else ""
        output.append(("class:approval", f"{_fit_line('  Request: ' + request_line, width)}\n"))
        output.append(("class:approval", f"{_fit_line('  Use Up/Down to choose. Enter selects. Esc leaves pending.', width)}\n"))

        options = self._approval_options()
        selected_choice = min(max(0, self.state.approval_choice_index), len(options) - 1)
        visible_rows = APPROVAL_PANEL_HEIGHT - 5
        start = max(0, min(selected_choice - visible_rows // 2, len(options) - visible_rows))
        end = min(len(options), start + visible_rows)
        for index in range(start, end):
            option, label, description = options[index]
            marker = ">" if index == selected_choice else " "
            line = f" {marker} {label} - {description}"
            style = "class:approval.selected" if index == selected_choice else "class:approval"
            if option == "deny":
                style = "class:approval.danger" if index == selected_choice else "class:approval"
            if option == "approve":
                style = "class:approval.action" if index == selected_choice else "class:approval"
            output.append((style, f"{_fit_line(line, width)}\n"))
        missing_rows = visible_rows - (end - start)
        if missing_rows > 0:
            output.append(("class:approval", "\n" * missing_rows))
        _option, label, description = options[selected_choice]
        output.append(("class:approval", f"{_fit_line('  Selected: ' + label + ' - ' + description, width)}\n"))
        output.append(("class:approval", _fit_line("  Exact-call approvals are one-shot; approved calls must be retried.", width)))
        return output

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
        if self._scroll_offset == 0:
            lines = self._transcript_tail_lines(width, height + TRANSCRIPT_RENDER_MARGIN)
        else:
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
            lines.extend(self._transcript_entry_lines(entry, text_width))
        return lines

    def _transcript_tail_lines(self, width: int, min_lines: int) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        text_width = max(1, width)
        for entry in reversed(self.state.transcript):
            entry_lines = self._transcript_entry_lines(entry, text_width)
            lines[0:0] = entry_lines
            if len(lines) >= min_lines:
                break
        return lines

    def _activity_lines(self, width: int) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        text_width = max(1, width)
        for entry in self.state.activity_log:
            lines.extend(self._activity_entry_lines(entry, text_width))
        return lines

    def _transcript_entry_lines(self, entry: TranscriptEntry, width: int) -> list[tuple[str, str]]:
        signature = (entry.kind, entry.title, entry.text)
        cached = self._transcript_cache.get(id(entry))
        if cached is not None and cached.width == width and cached.signature == signature:
            return cached.lines
        style = {
            "user": "class:role.user",
            "assistant": "class:role.assistant",
            "system": "class:role.system",
            "tool": "class:role.tool",
            "error": "class:role.error",
        }.get(entry.kind, "")
        title = entry.title or entry.kind
        if entry.kind == "tool":
            lines = self._wrap_lines(entry.text, width, style)
        elif entry.kind == "system":
            lines = [*self._wrap_lines(entry.text, width, style), ("", "")]
        else:
            lines = [(style, title), *self._wrap_lines(entry.text.rstrip(), width, ""), ("", "")]
        self._transcript_cache[id(entry)] = _WrappedEntryCache(signature=signature, width=width, lines=lines)
        return lines

    def _activity_entry_lines(self, entry: ActivityEntry, width: int) -> list[tuple[str, str]]:
        signature = (entry.kind, "", entry.text)
        cached = self._activity_cache.get(id(entry))
        if cached is not None and cached.width == width and cached.signature == signature:
            return cached.lines
        style = {
            "system": "class:details",
            "tool": "class:details.tool",
            "error": "class:details.error",
        }.get(entry.kind, "class:details")
        if entry.text.startswith("failed:"):
            style = "class:details.error"
        lines = self._wrap_lines(entry.text, width, style)
        self._activity_cache[id(entry)] = _WrappedEntryCache(signature=signature, width=width, lines=lines)
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
        return max(1, int(self.terminal_size_provider((120, 24)).columns))

    def _terminal_height(self) -> int:
        if self._app is not None:
            with contextlib.suppress(Exception):
                return max(1, int(self._app.output.get_size().rows))
        return max(1, int(self.terminal_size_provider((100, 24)).lines))

    def _transcript_height(self) -> int:
        details_height = DETAILS_HEIGHT if self.state.details_visible else 0
        approval_height = APPROVAL_PANEL_HEIGHT if self.state.approval_review_visible else 0
        return max(1, self._terminal_height() - 5 - details_height - approval_height)

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
        return _format_diagnostics_paths(self.log_dir)

    @contextlib.contextmanager
    def _suppress_terminal_logs(self):
        loggers = [
            logging.getLogger("app"),
            logging.getLogger("smolclaw"),
            logging.getLogger("smolclaw.rag"),
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
