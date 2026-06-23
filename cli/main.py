import asyncio
import inspect
import json
import logging
import os
import select
import sys
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

import typer

# Suppress noisy loggers from printing to console
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
from rich.console import Console
from rich.markdown import Markdown
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from app import diagnostics
from app.agent_loop import AgentLoop
from app.approvals import ApprovalRequestStore, format_approval_detail, format_approval_status
from app.bootstrap import init_project_guidance
from app.checkpoints import CheckpointStore
from app.definitions import (
    AGENT_MODEL, WORKSPACE_DIR, build_workspace_paths,
)
from app.goal import GoalState
from app.goal_ledger import GoalLedgerStore
from app.logger import clear_logs
from app.model_settings import (
    apply_subagent_model_selection,
    apply_runtime_model_selection,
    model_help,
    model_list,
    model_status,
    parse_model_selection,
    subagent_model_status,
)
from app.run_views import (
    compact_trace_value,
    format_goal_status,
    format_trace_event_line,
    format_trace_events,
    format_trace_list,
    format_trace_replay,
    format_trace_status,
)
from app.runtime_builder import build_runtime_services
from app.session_export_hook import SessionExportHook
from app.runtime import RuntimeEnvironment, build_configured_agent, build_master_registry
from app.session import SessionManager
from app.smol_rag import SmolRag
from app.tools.memory_tools import ContradictionReviewTool, MemoryRecallTool, MemoryStoreTool
from app.utilities import ensure_dir
from app.workspace import WorkspaceContext
from app.run_trace import RunTraceStore
from app.worktree import WorktreeRunner

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - non-POSIX fallback
    termios = None
    tty = None


def _get_param_metavar(param, ctx):
    try:
        return param.type.get_metavar(param=param, ctx=ctx)
    except TypeError:
        return param.type.get_metavar(param)


def _patch_typer_click_compat():
    # Typer 0.15.x still calls make_metavar() with the pre-Click 8.2 signature.
    if tuple(inspect.signature(typer.core.TyperArgument.make_metavar).parameters) == ("self",):
        def _argument_make_metavar(self, ctx=None):
            if self.metavar is not None:
                return self.metavar
            var = (self.name or "").upper()
            if not self.required:
                var = f"[{var}]"
            type_var = _get_param_metavar(self, ctx)
            if type_var:
                var += f":{type_var}"
            if self.nargs != 1:
                var += "..."
            return var

        typer.core.TyperArgument.make_metavar = _argument_make_metavar

    if tuple(inspect.signature(typer.core.TyperOption.make_metavar).parameters) == ("self", "ctx"):
        def _option_make_metavar(self, ctx=None):
            if self.metavar is not None:
                return self.metavar

            metavar = _get_param_metavar(self, ctx)
            if metavar is None:
                metavar = self.type.name.upper()
            if self.nargs != 1:
                metavar += "..."
            return metavar

        typer.core.TyperOption.make_metavar = _option_make_metavar


_patch_typer_click_compat()


app = typer.Typer(
    help="SmolClaw — agentic assistant with persistent memory",
    rich_markup_mode=None,
)
console = Console()

DEFAULT_AGENTS_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.yaml")
SLASH_COMMANDS_HELP = "\n".join([
    "Slash commands:",
    "  / or /help or /commands  Show this command list",
    "  /remember <text>         Store a memory immediately",
    "  /remember-thread         Export the current chat thread to memory",
    "  /memory list             List pending memory contradictions",
    "  /memory review           Discuss pending memory contradictions with the agent",
    "  /memory detail <id>      Show a memory contradiction",
    "  /memory resolve <id> <keep_existing|keep_new|merge|dismiss> [note]",
    "  /init                    Create or update AGENTS.md guidance",
    "  /logs                    Show workspace diagnostics log paths",
    "  /trace                   Show the latest run trace summary",
    "  /trace list              List run trace summaries",
    "  /trace events [run] [n]  Show recent run trace events",
    "  /trace replay [run]      Replay a compact run trajectory",
    "  /worktree status         Show isolated worktree status",
    "  /worktree diff           Show isolated changes",
    "  /worktree apply          Apply isolated changes to the base repo",
    "  /worktree discard        Discard isolated changes when the session exits",
    "  /approval status         Show pending approval requests",
    "  /approval detail <id>    Show one approval request in detail",
    "  /approval approve <id>   Approve one exact pending tool call",
    "  /approval deny <id>      Deny one pending tool call",
    "  /details                 Toggle recent tool/thinking activity",
    "  /model [model] [effort]  Show or switch gpt-5.4/gpt-5.5 model",
    "  /undo                    Undo the last SmolClaw file checkpoint",
    "  /goal status             Show the current session goal",
    "  /goal start <objective>  Set the session goal",
    "  /goal run [max_turns]    Continue the goal loop (default: 3)",
    "  /goal complete [note]    Mark the goal complete",
    "  /goal block [note]       Mark the goal blocked",
    "  /goal clear              Clear the session goal",
    "  /clear                   Clear the current chat session",
    "  /quit or /exit           Exit chat",
])


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    from app.tracing import init_tracing
    init_tracing()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


async def _close_async_resource(resource):
    close_fn = getattr(resource, "close", None)
    if not callable(close_fn):
        return
    result = close_fn()
    if inspect.isawaitable(result):
        await result


def _format_action_event(event: dict) -> str | None:
    event_type = event.get("type")

    if event_type == "llm":
        if event.get("phase") == "start":
            return "thinking..."
        if event.get("phase") == "end":
            duration_s = max(0, event.get("duration_ms", 0)) / 1000
            tokens = event.get("total_tokens", 0)
            return f"thought: {tokens:,} tokens ({duration_s:.1f}s)"
        return None

    if event_type != "tool":
        return None

    name = event.get("name", "tool")
    if event.get("phase") == "start":
        summary = event.get("summary") or name
        return f"action: {summary}"

    if event.get("phase") == "end":
        duration_ms = max(0, int(event.get("duration_ms", 0)))
        duration_s = duration_ms / 1000
        if event.get("ok", True):
            return f"done: {name} ({duration_s:.1f}s)"
        result_preview = event.get("result_preview") or "Error"
        return f"failed: {name} ({duration_s:.1f}s) - {result_preview}"

    return None


def _print_usage_summary(console, session_usage):
    from app.usage import SessionUsage
    if not isinstance(session_usage, SessionUsage) or not session_usage.turns:
        return
    console.print()
    console.print("[bold]Session Usage[/bold]")
    console.print(
        f"  Tokens: {session_usage.total_tokens:,} "
        f"(prompt: {session_usage.total_prompt_tokens:,}, "
        f"completion: {session_usage.total_completion_tokens:,})"
    )
    console.print(
        f"  LLM time: {session_usage.total_duration_ms / 1000:.1f}s "
        f"across {len(session_usage.turns)} turn(s)"
    )
    by_cat = session_usage.by_category()
    if len(by_cat) > 1:
        for cat, data in sorted(by_cat.items(), key=lambda x: x[1]["total_tokens"], reverse=True):
            console.print(
                f"    {cat}: {data['total_tokens']:,} tokens "
                f"({data['count']} call{'s' if data['count'] != 1 else ''}, "
                f"{data['duration_ms'] / 1000:.1f}s)"
            )


def _format_goal_status(goal: GoalState | None) -> str:
    return format_goal_status(goal)


def _format_trace_status(traces_dir: str, session_key: str, *, goal_store=None) -> str:
    return format_trace_status(RunTraceStore(traces_dir), session_key, goal_store=goal_store)


def _format_bootstrap_result(result) -> str:
    if result.created:
        return f"Created {result.path}"
    if result.updated:
        return f"Updated {result.path}"
    return f"AGENTS.md is already up to date: {result.path}"


def _format_trace_list(traces_dir: str, session_key: str, *, limit: int = 10) -> str:
    return format_trace_list(RunTraceStore(traces_dir), session_key, limit=limit)


def _compact_trace_value(value: object, *, max_length: int = 120) -> str:
    return compact_trace_value(value, max_length=max_length)


def _format_trace_event_line(event) -> str:
    return format_trace_event_line(event)


def _format_trace_events(
    traces_dir: str,
    session_key: str,
    *,
    run_id: str | None = None,
    limit: int = 20,
) -> str:
    return format_trace_events(
        RunTraceStore(traces_dir),
        session_key,
        run_id=run_id,
        limit=limit,
    )


def _format_trace_replay(
    traces_dir: str,
    session_key: str,
    *,
    run_id: str | None = None,
) -> str:
    return format_trace_replay(RunTraceStore(traces_dir), session_key, run_id=run_id)


def _parse_trace_events_args(command_arg: str) -> tuple[str | None, int]:
    parts = command_arg.split()
    run_id: str | None = None
    limit = 20
    if not parts:
        return run_id, limit
    if parts[0].isdigit():
        return run_id, int(parts[0])
    run_id = parts[0]
    if len(parts) > 1:
        if not parts[1].isdigit():
            raise ValueError("Usage: /trace events [run_id] [limit]")
        limit = int(parts[1])
    return run_id, limit


def _resolve_trace_command(
    traces_dir: str,
    session_key: str,
    command_arg: str,
    *,
    goal_store=None,
) -> str:
    parts = command_arg.split(maxsplit=1)
    subcommand = parts[0] if parts else "status"
    sub_arg = parts[1].strip() if len(parts) > 1 else ""
    if subcommand in ("", "status"):
        return _format_trace_status(traces_dir, session_key, goal_store=goal_store)
    if subcommand == "list":
        return _format_trace_list(traces_dir, session_key)
    if subcommand == "events":
        try:
            run_id, limit = _parse_trace_events_args(sub_arg)
        except ValueError as exc:
            return str(exc)
        return _format_trace_events(traces_dir, session_key, run_id=run_id, limit=limit)
    if subcommand == "replay":
        return _format_trace_replay(traces_dir, session_key, run_id=sub_arg or None)
    return "Usage: /trace status|list|events [run_id] [limit]|replay [run_id]"


def _resolve_approval_command(
    approval_store: ApprovalRequestStore,
    session_key: str,
    command_arg: str,
) -> str:
    parts = command_arg.split(maxsplit=1)
    subcommand = parts[0] if parts else "status"
    approval_id = parts[1].strip() if len(parts) > 1 else ""
    if subcommand in ("", "status"):
        return format_approval_status(approval_store, session_key)
    if subcommand == "detail":
        if not approval_id:
            return "Usage: /approval detail <id>"
        return format_approval_detail(approval_store, session_key, approval_id)
    if subcommand not in {"approve", "deny"}:
        return "Usage: /approval status|detail <id>|approve <id>|deny <id>"
    if not approval_id:
        return f"Usage: /approval {subcommand} <id>"
    try:
        if subcommand == "approve":
            request = approval_store.approve(session_key, approval_id)
            return f"Approved {request.id}. Retry the same tool call to continue."
        request = approval_store.deny(session_key, approval_id)
        return f"Denied {request.id}."
    except KeyError as exc:
        return f"Error: {exc}"


async def _resolve_memory_command(smol_rag, command_arg: str) -> str:
    detector = getattr(smol_rag, "contradiction_detector", None)
    if detector is None:
        return "Memory contradiction review is unavailable; no contradiction detector is configured."

    parts = command_arg.split(maxsplit=1)
    subcommand = parts[0] if parts else "status"
    sub_arg = parts[1].strip() if len(parts) > 1 else ""
    tool = ContradictionReviewTool(detector)

    if subcommand in ("", "status", "list"):
        return await tool.execute(action="list")
    if subcommand == "detail":
        if not sub_arg:
            return "Usage: /memory detail <contradiction_id>"
        return await tool.execute(action="detail", contradiction_id=sub_arg)
    if subcommand == "resolve":
        resolve_parts = sub_arg.split(maxsplit=2)
        if len(resolve_parts) < 2:
            return "Usage: /memory resolve <contradiction_id> <keep_existing|keep_new|merge|dismiss> [note]"
        contradiction_id, resolution = resolve_parts[0], resolve_parts[1]
        note = resolve_parts[2] if len(resolve_parts) > 2 else None
        return await tool.execute(
            action="resolve",
            contradiction_id=contradiction_id,
            resolution=resolution,
            note=note,
        )
    return (
        "Usage: /memory status|list|review|detail <contradiction_id>|"
        "resolve <contradiction_id> <keep_existing|keep_new|merge|dismiss> [note]"
    )


@dataclass
class _InteractiveWorktreeState:
    context: object
    state_root: str
    keep_on_exit: bool = False
    discard_on_exit: bool = False
    applied_count: int = 0


def _worktree_mode_name(worktree_ctx) -> str:
    return "git-worktree" if worktree_ctx.created_by_git_worktree else "dirty-copy"


def _format_worktree_status(worktree_state: _InteractiveWorktreeState | None) -> str:
    if worktree_state is None:
        return "No active isolated worktree."
    ctx = worktree_state.context
    return "\n".join([
        "Worktree: active",
        f"Mode: {_worktree_mode_name(ctx)}",
        f"Run id: {ctx.run_id}",
        f"Source root: {ctx.path}",
        f"State root: {worktree_state.state_root}",
        f"Base repo: {ctx.base_repo}",
        f"Keep on exit: {'yes' if worktree_state.keep_on_exit else 'no'}",
        f"Discard on exit: {'yes' if worktree_state.discard_on_exit else 'no'}",
        f"Apply count: {worktree_state.applied_count}",
    ])


def _resolve_worktree_command(
    worktree_state: _InteractiveWorktreeState | None,
    command_arg: str,
) -> str:
    parts = command_arg.split(maxsplit=1)
    subcommand = parts[0] if parts else "status"
    if subcommand in ("", "status"):
        return _format_worktree_status(worktree_state)
    if worktree_state is None:
        return "No active isolated worktree."
    ctx = worktree_state.context
    if subcommand == "diff":
        diff = ctx.diff()
        return diff if diff.strip() else "No isolated changes."
    if subcommand == "apply":
        result = ctx.apply_back()
        if result.startswith("Applied "):
            worktree_state.applied_count += 1
        return result
    if subcommand == "discard":
        worktree_state.discard_on_exit = True
        return "Discard scheduled. The isolated worktree will be removed when the session exits."
    return "Usage: /worktree status|diff|apply|discard"


def _parse_goal_run_count(value: str) -> int:
    if not value:
        return 3
    try:
        turns = int(value)
    except ValueError as exc:
        raise typer.BadParameter("/goal run expects a positive integer max_turns") from exc
    if turns <= 0:
        raise typer.BadParameter("/goal run expects a positive integer max_turns")
    return min(turns, 20)


def _build_memory_review_prompt(command_arg: str = "") -> str:
    scope = command_arg.strip()
    scope_line = f"\nFocus or note from the user: {scope}" if scope else ""
    return (
        "Review pending memory contradictions conversationally.\n"
        "Use contradiction_review with action=list first. For each pending contradiction, "
        "use action=detail when it is relevant to explain the conflict. Group likely "
        "duplicates, metadata noise, broad tag conflicts, and real semantic conflicts. "
        "Explain your reasoning and propose resolutions in plain language. Do not call "
        "contradiction_review with action=resolve during this initial review turn. Ask "
        "concise targeted questions where user judgement or confirmation is needed. "
        "Do not modify files or run shell commands for this memory maintenance task."
        f"{scope_line}"
    )


def _build_goal_loop_prompt() -> str:
    return (
        "Continue working toward the active session goal. "
        "Use git_status, or run_command with git status if git_status is unavailable, plus the available read/search tools to inspect the codebase before editing. "
        "Read any existing target file before changing it. "
        "If the user asks to make something the active goal, call goal_start with the concrete objective. "
        "If the goal is complete or blocked, call goal_update with the appropriate status and a brief note."
    )


def _format_undo_result(result) -> str:
    if not result.ok:
        if result.conflicts:
            return "\n".join([result.message, *result.conflicts])
        return result.message
    lines = [result.message]
    if result.restored_paths:
        lines.extend(f"- {path}" for path in result.restored_paths)
    return "\n".join(lines)


def _workspace_context(workspace_root: str) -> WorkspaceContext:
    return WorkspaceContext.from_root(workspace_root).ensure_dirs()


def _state_root_for_workspace(workspace_root: str) -> str:
    return build_workspace_paths(workspace_root).state_root_dir


def _resolve_user_path(workspace: WorkspaceContext, path: str) -> str:
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return os.path.realpath(expanded)
    return workspace.resolve_path(expanded)


def _resolve_workspace_path(workspace: WorkspaceContext, path: str) -> str:
    resolved, error = workspace.resolve_contained_path(path)
    if error:
        raise typer.BadParameter(error)
    return resolved


def _build_cli_runtime(
    workspace: str | WorkspaceContext,
    *,
    agent_configs=None,
    enable_subagents: bool = False,
    llm=None,
    smol_rag=None,
    session_manager=None,
):
    return build_runtime_services(
        workspace,
        transport="direct",
        agent_configs=agent_configs,
        enable_subagents=enable_subagents,
        llm=llm,
        smol_rag=smol_rag,
        session_manager=session_manager,
    )


def _make_session_end_hook_registrar(paths, memory_dir: str, auto_export: bool):
    from app.hooks import ON_SESSION_END
    from app.usage import UsagePersistHook

    def register_session_end_hooks(loop: AgentLoop):
        loop.hook_runner.on(ON_SESSION_END, UsagePersistHook(paths.sessions_dir))
        rag = getattr(loop, "smol_rag", None)
        if not auto_export or rag is None:
            return

        from app.lifecycle_hooks import ContradictionExpiryHook

        loop.hook_runner.on(
            ON_SESSION_END,
            SessionExportHook(
                smol_rag=rag,
                llm=loop.llm,
                memory_dir=memory_dir,
            ),
        )
        if getattr(rag, "contradiction_detector", None):
            loop.hook_runner.on(
                ON_SESSION_END,
                ContradictionExpiryHook(rag.contradiction_detector),
            )

    return register_session_end_hooks


class _ResearchLoopStopController:
    def __init__(self):
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()
        self._reason: str | None = None
        self._lock = threading.Lock()

    @property
    def stop_requested(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason or "Stop requested."

    def request_stop(self, reason: str):
        with self._lock:
            if self._reason is None:
                self._reason = reason
        self._loop.call_soon_threadsafe(self._event.set)

    async def wait(self, timeout: float | None = None) -> bool:
        if timeout is None:
            await self._event.wait()
            return True
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


class _EscKeyWatcher:
    def __init__(self, stop_controller: _ResearchLoopStopController):
        self._stop_controller = stop_controller
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return self._thread is not None

    def start(self):
        if self._thread is not None:
            return
        if os.name != "posix" or termios is None or tty is None:
            return
        if not sys.stdin.isatty():
            return

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):  # pragma: no cover - exercised indirectly in manual CLI use
        fd = sys.stdin.fileno()
        original = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self._shutdown.is_set():
                ready, _, _ = select.select([fd], [], [], 0.2)
                if not ready:
                    continue
                ch = os.read(fd, 1)
                if ch == b"\x1b":
                    self._stop_controller.request_stop("Stopped: Escape pressed.")
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original)

    def close(self):
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)


def _create_research_loop_stop_controller():
    controller = _ResearchLoopStopController()
    watcher = _EscKeyWatcher(controller)
    watcher.start()
    return controller, watcher


def _build_research_loop_prompt(goal: str, iteration: int) -> str:
    run_number = iteration + 1
    if iteration == 0:
        return "\n\n".join([
            f"Ongoing research goal: {goal}",
            f"Run number: {run_number}",
            "Search memory first, then use the web only when needed.",
            "Store verified findings and durable references to memory.",
            "Return a concise research update with key findings, what changed, and open questions.",
        ])

    return "\n\n".join([
        f"Ongoing research goal: {goal}",
        f"Run number: {run_number}",
        "Review prior session context and memory first.",
        "Focus on new, changed, or still-unresolved information instead of repeating prior work.",
        "Store verified findings and durable references to memory.",
        "Return only the important delta, plus any open questions that still need research.",
    ])


def _format_research_loop_exit(
    reason: str | None,
    *,
    runs_completed: int,
    reached_run_limit: bool,
) -> str:
    if reason:
        if runs_completed:
            return f"{reason} Completed {runs_completed} cycle(s)."
        return reason
    if reached_run_limit:
        return f"Completed requested run limit after {runs_completed} cycle(s)."
    if runs_completed:
        return f"Research loop finished after {runs_completed} cycle(s)."
    return "Research loop finished."


def _build_cli_tool_registry(smol_rag: SmolRag, workspace: str | WorkspaceContext, llm=None,
                              agent_configs=None, session_manager=None, enable_subagents: bool = False):
    runtime = _build_cli_runtime(
        workspace,
        agent_configs=agent_configs,
        enable_subagents=enable_subagents,
        llm=llm,
        smol_rag=smol_rag,
        session_manager=session_manager,
    )
    return build_master_registry(runtime.env)


def _build_multiagent(
    agent_name: str,
    agents_config_path: str,
    session_key: str,
    smol_rag: SmolRag,
    workspace: str | WorkspaceContext,
    session_manager: SessionManager,
    auto_export: bool,
    child_loop_registrar=None,
) -> AgentLoop:
    from app.agent_config import AgentConfigLoader

    configs = AgentConfigLoader.load(agents_config_path)
    if agent_name not in configs:
        available = ", ".join(sorted(configs.keys()))
        raise typer.BadParameter(f"Unknown agent '{agent_name}'. Available: {available}")

    env = _build_cli_runtime(
        workspace,
        agent_configs=configs,
        enable_subagents=True,
        smol_rag=smol_rag,
        session_manager=session_manager,
    ).env
    return build_configured_agent(
        config=configs[agent_name],
        env=env,
        session_key_prefix=session_key,
        child_loop_registrar=child_loop_registrar,
    )


def _build_default_chat_agent(
    agents_config_path: str,
    session_key: str,
    model: str,
    smol_rag: SmolRag,
    workspace: str | WorkspaceContext,
    session_manager: SessionManager,
    child_loop_registrar=None,
) -> AgentLoop:
    from app.agent_config import AgentConfigLoader

    configs = AgentConfigLoader.load(agents_config_path)
    if "default" not in configs:
        raise typer.BadParameter(
            f"Agents config '{agents_config_path}' must define a 'default' agent for chat."
        )

    env = _build_cli_runtime(
        workspace,
        agent_configs=configs,
        enable_subagents=True,
        smol_rag=smol_rag,
        session_manager=session_manager,
    ).env
    return build_configured_agent(
        config=configs["default"],
        env=env,
        session_key=session_key,
        model_override=model,
        child_loop_registrar=child_loop_registrar,
    )


@app.command()
def chat(
    session_key: str = typer.Option("default", "--session", "-s", help="Session key"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
    model: str = typer.Option(AGENT_MODEL, "--model", "-m", help="LLM model to use"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name from agents.yaml"),
    agents_config: str = typer.Option(DEFAULT_AGENTS_CONFIG, "--agents-config", help="Path to agents YAML config"),
    auto_export: bool = typer.Option(False, "--auto-export/--no-auto-export", help="Auto-export session to memory on close"),
    show_actions: bool = typer.Option(False, "--show-actions/--hide-actions", help="Show recent tool activity details while the agent works"),
    worktree: bool = typer.Option(False, "--worktree", help="Run chat in an isolated git worktree"),
    copy_dirty_worktree: bool = typer.Option(False, "--copy-dirty-worktree", help="Copy a dirty workspace instead of refusing worktree mode"),
    keep_worktree: bool = typer.Option(False, "--keep-worktree", help="Keep the isolated worktree after chat exits"),
):
    """Start an interactive chat session."""
    asyncio.run(_tui_chat_loop(
        session_key,
        workspace,
        model,
        agent,
        agents_config,
        auto_export,
        show_actions,
        worktree=worktree,
        copy_dirty_worktree=copy_dirty_worktree,
        keep_worktree=keep_worktree,
    ))


@app.command(name="run")
def run_once(
    prompt: str = typer.Argument(..., help="Prompt to run non-interactively"),
    session_key: str = typer.Option("default", "--session", "-s", help="Session key"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
    model: str = typer.Option(AGENT_MODEL, "--model", "-m", help="LLM model to use"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name from agents.yaml"),
    agents_config: str = typer.Option(DEFAULT_AGENTS_CONFIG, "--agents-config", help="Path to agents YAML config"),
    max_turns: int = typer.Option(1, "--max-turns", help="Maximum goal-loop turns when --goal is set"),
    goal: bool = typer.Option(False, "--goal", help="Treat the prompt as a goal and run goal-loop turns"),
    auto_export: bool = typer.Option(False, "--auto-export/--no-auto-export", help="Auto-export session to memory on close"),
    worktree: bool = typer.Option(False, "--worktree", help="Run in an isolated git worktree"),
    copy_dirty_worktree: bool = typer.Option(False, "--copy-dirty-worktree", help="Copy a dirty workspace instead of refusing worktree mode"),
    keep_worktree: bool = typer.Option(False, "--keep-worktree", help="Keep the isolated worktree after the run"),
):
    """Run one non-interactive agent prompt and print a JSON result."""
    if max_turns < 1:
        raise typer.BadParameter("--max-turns must be greater than 0")
    result = asyncio.run(_run_once(
        prompt=prompt,
        session_key=session_key,
        workspace=workspace,
        model=model,
        agent_name=agent,
        agents_config=agents_config,
        max_turns=max_turns,
        goal=goal,
        auto_export=auto_export,
        worktree=worktree,
        copy_dirty_worktree=copy_dirty_worktree,
        keep_worktree=keep_worktree,
    ))
    console.print(json.dumps(result, indent=2, sort_keys=True))


@app.command(name="init")
def init_command(
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """Create or update SmolClaw guidance in AGENTS.md."""
    result = init_project_guidance(_workspace_context(workspace))
    console.print(_format_bootstrap_result(result))


async def _run_once(
    *,
    prompt: str,
    session_key: str,
    workspace: str,
    model: str,
    agent_name: Optional[str] = None,
    agents_config: str = DEFAULT_AGENTS_CONFIG,
    max_turns: int = 1,
    goal: bool = False,
    auto_export: bool = False,
    worktree: bool = False,
    copy_dirty_worktree: bool = False,
    keep_worktree: bool = False,
) -> dict:
    worktree_ctx = None
    active_workspace: str | WorkspaceContext = workspace
    if worktree:
        worktree_ctx = WorktreeRunner().create(
            workspace,
            f"smolclaw-{uuid.uuid4().hex[:12]}",
            copy_dirty=copy_dirty_worktree,
        )
        active_workspace = WorkspaceContext.from_root(worktree_ctx.path, state_root=_state_root_for_workspace(workspace))
    agent = None
    smol_rag = None
    responses: list[str] = []
    try:
        runtime = _build_cli_runtime(active_workspace)
        workspace_ctx = runtime.workspace
        paths = workspace_ctx.paths
        smol_rag = runtime.smol_rag
        session_manager = runtime.session_manager
        goal_store = GoalLedgerStore(paths.ledgers_dir, legacy_sessions_dir=paths.sessions_dir)
        if agent_name:
            agent = _build_multiagent(
                agent_name,
                agents_config,
                session_key,
                smol_rag,
                active_workspace,
                session_manager,
                auto_export,
            )
        else:
            agent = _build_default_chat_agent(
                agents_config_path=agents_config,
                session_key=session_key,
                model=model,
                smol_rag=smol_rag,
                workspace=active_workspace,
                session_manager=session_manager,
            )
        if goal:
            current_goal = goal_store.load(agent.session.key)
            if current_goal is None or current_goal.status != "active":
                goal_store.start(agent.session.key, prompt)
            for _ in range(max_turns):
                current_goal = goal_store.load(agent.session.key)
                if current_goal is None or current_goal.status != "active":
                    break
                responses.append(await agent.process(_build_goal_loop_prompt()))
        else:
            responses.append(await agent.process(prompt))
        trace_store = RunTraceStore(paths.traces_dir)
        latest_trace = trace_store.latest_summary(agent.session.key)
        current_goal = goal_store.load(agent.session.key)
        return {
            "session_key": agent.session.key,
            "status": current_goal.status if current_goal is not None else "complete",
            "response": responses[-1] if responses else "",
            "responses": responses,
            "turns": len(responses),
            "trace_path": latest_trace.trace_path if latest_trace is not None else None,
            "trace_summary_path": (
                trace_store.summary_path(agent.session.key, latest_trace.run_id)
                if latest_trace is not None else None
            ),
            "ledger_path": (
                os.path.join(paths.ledgers_dir, f"{agent.session.key}.ledger.json")
                if current_goal is not None else None
            ),
            "stop_reason": latest_trace.stop_reason if latest_trace is not None else None,
            "worktree_path": worktree_ctx.path if worktree_ctx is not None else None,
            "worktree_diff": worktree_ctx.diff() if worktree_ctx is not None else None,
        }
    finally:
        if agent is not None:
            await agent.close()
        try:
            await _close_async_resource(smol_rag)
        finally:
            if worktree_ctx is not None and not keep_worktree:
                worktree_ctx.cleanup()


async def _tui_chat_loop(
    session_key: str,
    workspace: str,
    model: str,
    agent_name: Optional[str] = None,
    agents_config: str = DEFAULT_AGENTS_CONFIG,
    auto_export: bool = False,
    show_actions: bool = False,
    display_label: Optional[str] = None,
    worktree: bool = False,
    copy_dirty_worktree: bool = False,
    keep_worktree: bool = False,
):
    worktree_state: _InteractiveWorktreeState | None = None
    active_workspace: str | WorkspaceContext = workspace
    if worktree:
        worktree_ctx = WorktreeRunner().create(
            workspace,
            f"smolclaw-{uuid.uuid4().hex[:12]}",
            copy_dirty=copy_dirty_worktree,
        )
        active_workspace = WorkspaceContext.from_root(worktree_ctx.path, state_root=_state_root_for_workspace(workspace))
        worktree_state = _InteractiveWorktreeState(
            context=worktree_ctx,
            state_root=_state_root_for_workspace(workspace),
            keep_on_exit=keep_worktree,
        )
    runtime = _build_cli_runtime(active_workspace)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    smol_rag = runtime.smol_rag
    session_manager = runtime.session_manager
    goal_store = GoalLedgerStore(paths.ledgers_dir, legacy_sessions_dir=paths.sessions_dir)
    checkpoint_store = CheckpointStore(paths.checkpoints_dir)
    approval_store = ApprovalRequestStore(paths.approvals_dir)
    memory_dir = ensure_dir(paths.memory_docs_dir)
    register_session_end_hooks = _make_session_end_hook_registrar(paths, memory_dir, auto_export)

    if agent_name:
        agent = _build_multiagent(
            agent_name,
            agents_config,
            session_key,
            smol_rag,
            active_workspace,
            session_manager,
            auto_export,
            child_loop_registrar=register_session_end_hooks,
        )
        label = display_label or agent_name.capitalize()
    else:
        agent = _build_default_chat_agent(
            agents_config_path=agents_config,
            session_key=session_key,
            model=model,
            smol_rag=smol_rag,
            workspace=active_workspace,
            session_manager=session_manager,
            child_loop_registrar=register_session_end_hooks,
        )
        label = display_label or "SmolClaw"

    register_session_end_hooks(agent)

    memory_store_tool = MemoryStoreTool(
        smol_rag=smol_rag,
        memory_docs_dir=memory_dir,
        llm=agent.llm,
    )
    session_export_hook = SessionExportHook(
        smol_rag=smol_rag,
        llm=agent.llm,
        memory_dir=memory_dir,
    )

    from cli.tui import CoderTui

    tui = CoderTui(
        agent=agent,
        goal_store=goal_store,
        session_manager=session_manager,
        memory_store_tool=memory_store_tool,
        session_export_hook=session_export_hook,
        smol_rag=smol_rag,
        checkpoint_store=checkpoint_store,
        approval_store=approval_store,
        workspace_root=workspace_ctx.root_dir,
        log_dir=paths.log_dir,
        model=model,
        auto_export=auto_export,
        show_actions=show_actions,
        slash_commands_help=SLASH_COMMANDS_HELP,
        format_goal_status=_format_goal_status,
        parse_goal_run_count=_parse_goal_run_count,
        build_goal_loop_prompt=_build_goal_loop_prompt,
        build_memory_review_prompt=_build_memory_review_prompt,
        format_trace_status=lambda session_key, command_arg: _resolve_trace_command(
            paths.traces_dir,
            session_key,
            command_arg,
            goal_store=goal_store,
        ),
        resolve_approval_command=lambda session_key, arg: _resolve_approval_command(approval_store, session_key, arg),
        resolve_memory_command=lambda arg: _resolve_memory_command(smol_rag, arg),
        resolve_worktree_command=lambda arg: _resolve_worktree_command(worktree_state, arg),
        initialize_project=lambda: _format_bootstrap_result(init_project_guidance(workspace_ctx)),
        format_action_event=_format_action_event,
        label=label,
    )
    try:
        await tui.run()
    finally:
        if worktree_state is not None and (worktree_state.discard_on_exit or not worktree_state.keep_on_exit):
            worktree_state.context.cleanup()


async def _chat_loop(
    session_key: str,
    workspace: str,
    model: str,
    agent_name: Optional[str] = None,
    agents_config: str = DEFAULT_AGENTS_CONFIG,
    auto_export: bool = False,
    show_actions: bool = True,
    display_label: Optional[str] = None,
    worktree: bool = False,
    copy_dirty_worktree: bool = False,
    keep_worktree: bool = False,
):
    worktree_state: _InteractiveWorktreeState | None = None
    active_workspace: str | WorkspaceContext = workspace
    if worktree:
        worktree_ctx = WorktreeRunner().create(
            workspace,
            f"smolclaw-{uuid.uuid4().hex[:12]}",
            copy_dirty=copy_dirty_worktree,
        )
        active_workspace = WorkspaceContext.from_root(worktree_ctx.path, state_root=_state_root_for_workspace(workspace))
        worktree_state = _InteractiveWorktreeState(
            context=worktree_ctx,
            state_root=_state_root_for_workspace(workspace),
            keep_on_exit=keep_worktree,
        )
    runtime = _build_cli_runtime(active_workspace)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    smol_rag = runtime.smol_rag
    session_manager = runtime.session_manager
    goal_store = GoalLedgerStore(paths.ledgers_dir, legacy_sessions_dir=paths.sessions_dir)
    checkpoint_store = CheckpointStore(paths.checkpoints_dir)
    approval_store = ApprovalRequestStore(paths.approvals_dir)
    memory_dir = ensure_dir(paths.memory_docs_dir)
    register_session_end_hooks = _make_session_end_hook_registrar(paths, memory_dir, auto_export)

    if agent_name:
        agent = _build_multiagent(
            agent_name,
            agents_config,
            session_key,
            smol_rag,
            active_workspace,
            session_manager,
            auto_export,
            child_loop_registrar=register_session_end_hooks,
        )
        label = display_label or agent_name.capitalize()
    else:
        agent = _build_default_chat_agent(
            agents_config_path=agents_config,
            session_key=session_key,
            model=model,
            smol_rag=smol_rag,
            workspace=active_workspace,
            session_manager=session_manager,
            child_loop_registrar=register_session_end_hooks,
        )
        label = display_label or "SmolClaw"

    register_session_end_hooks(agent)

    memory_store_tool = MemoryStoreTool(
        smol_rag=smol_rag,
        memory_docs_dir=memory_dir,
        llm=agent.llm,
    )
    session_export_hook = SessionExportHook(
        smol_rag=smol_rag,
        llm=agent.llm,
        memory_dir=memory_dir,
    )

    history_file = paths.prompt_history_path
    prompt_session = PromptSession(history=FileHistory(history_file))

    console.print(f"[bold green]{label}[/bold green] ready. Type /help for commands, /quit to exit.\n")

    async def _run_agent_turn(prompt: str) -> str:
        streamed = False

        async def on_output(chunk: str):
            nonlocal streamed
            if not streamed:
                console.print()  # blank line before response
                streamed = True
            console.file.write(chunk)
            console.file.flush()

        async def on_event(event: dict):
            if not show_actions:
                return
            line = _format_action_event(event)
            if line:
                console.print(f"[dim]{line}[/dim]")

        if show_actions:
            response = await agent.process(prompt, on_output=on_output, on_event=on_event)
        else:
            response = await agent.process(prompt, on_output=on_output)

        if streamed:
            console.file.write("\n")
            console.file.flush()
            console.print()
        else:
            console.print()
            console.print(Markdown(response))
            console.print()
        return response

    try:
        while True:
            try:
                user_input = await prompt_session.prompt_async("you> ")
            except (EOFError, KeyboardInterrupt):
                break

            user_input = user_input.strip()
            if not user_input:
                continue
            command_parts = user_input.split(maxsplit=1)
            command = command_parts[0]
            command_arg = command_parts[1].strip() if len(command_parts) > 1 else ""
            if command in ("/", "/help", "/commands"):
                console.print(f"[dim]{SLASH_COMMANDS_HELP}[/dim]")
                continue
            if user_input in ("/quit", "/exit"):
                break
            if user_input == "/clear":
                agent.session.clear()
                session_manager.save(agent.session)
                console.print("[dim]Session cleared.[/dim]")
                continue
            if user_input == "/init":
                console.print(f"[dim]{_format_bootstrap_result(init_project_guidance(workspace_ctx))}[/dim]")
                continue
            if user_input == "/undo":
                result = checkpoint_store.undo_last(session_key=agent.session.key)
                style = "dim" if result.ok else "red"
                console.print(f"[{style}]{_format_undo_result(result)}[/{style}]")
                continue
            if command == "/trace":
                trace_output = _resolve_trace_command(
                    paths.traces_dir,
                    agent.session.key,
                    command_arg,
                    goal_store=goal_store,
                )
                console.print(
                    f"[dim]{trace_output}[/dim]"
                )
                continue
            if command == "/approval":
                console.print(
                    f"[dim]{_resolve_approval_command(approval_store, agent.session.key, command_arg)}[/dim]"
                )
                continue
            if command == "/memory":
                memory_parts = command_arg.split(maxsplit=1)
                memory_subcommand = memory_parts[0] if memory_parts else "status"
                memory_sub_arg = memory_parts[1].strip() if len(memory_parts) > 1 else ""
                if memory_subcommand in {"review", "reconcile"}:
                    if getattr(smol_rag, "contradiction_detector", None) is None:
                        console.print(f"[dim]{await _resolve_memory_command(smol_rag, command_arg)}[/dim]")
                        continue
                    await _run_agent_turn(_build_memory_review_prompt(memory_sub_arg))
                    continue
                console.print(f"[dim]{await _resolve_memory_command(smol_rag, command_arg)}[/dim]")
                continue
            if command == "/worktree":
                console.print(
                    f"[dim]{_resolve_worktree_command(worktree_state, command_arg)}[/dim]"
                )
                continue
            if command == "/model":
                if not command_arg:
                    console.print(f"[dim]{model_help(agent.llm, getattr(agent, 'model_settings', None))}[/dim]")
                    continue
                if command_arg == "list":
                    console.print(f"[dim]{model_list()}[/dim]")
                    continue
                subagent_parts = command_arg.split(maxsplit=1)
                if subagent_parts[0] == "subagents":
                    if len(subagent_parts) == 1:
                        console.print(f"[dim]{subagent_model_status(getattr(agent, 'model_settings', None))}[/dim]")
                        continue
                    try:
                        selection = parse_model_selection(subagent_parts[1])
                    except ValueError as exc:
                        console.print(f"[dim]Error: {exc}[/dim]")
                        continue
                    apply_subagent_model_selection(selection, getattr(agent, "model_settings", None))
                    console.print(f"[dim]Switched {subagent_model_status(getattr(agent, 'model_settings', None))}[/dim]")
                    continue
                try:
                    selection = parse_model_selection(command_arg)
                except ValueError as exc:
                    console.print(f"[dim]Error: {exc}[/dim]")
                    continue
                apply_runtime_model_selection(agent.llm, selection, getattr(agent, "model_settings", None))
                console.print(f"[dim]Switched {model_status(agent.llm)}[/dim]")
                continue
            if command == "/goal":
                sub_parts = command_arg.split(maxsplit=1)
                subcommand = sub_parts[0] if sub_parts else "status"
                sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""
                if subcommand in ("", "status"):
                    console.print(f"[dim]{_format_goal_status(goal_store.load(agent.session.key))}[/dim]")
                    continue
                if subcommand == "start":
                    if not sub_arg:
                        console.print("[dim]Usage: /goal start <objective>[/dim]")
                        continue
                    goal = goal_store.start(agent.session.key, sub_arg)
                    console.print(f"[dim]Goal set: {goal.objective}[/dim]")
                    continue
                if subcommand == "complete":
                    try:
                        goal = goal_store.update(agent.session.key, status="complete", note=sub_arg)
                    except ValueError as exc:
                        console.print(f"[dim]Error: {exc}[/dim]")
                        continue
                    console.print(f"[dim]{_format_goal_status(goal)}[/dim]")
                    continue
                if subcommand == "block":
                    try:
                        goal = goal_store.update(agent.session.key, status="blocked", note=sub_arg)
                    except ValueError as exc:
                        console.print(f"[dim]Error: {exc}[/dim]")
                        continue
                    console.print(f"[dim]{_format_goal_status(goal)}[/dim]")
                    continue
                if subcommand == "clear":
                    removed = goal_store.clear(agent.session.key)
                    message = "Goal cleared." if removed else "No goal was set."
                    console.print(f"[dim]{message}[/dim]")
                    continue
                if subcommand == "run":
                    try:
                        max_turns = _parse_goal_run_count(sub_arg)
                    except typer.BadParameter as exc:
                        console.print(f"[dim]{exc}[/dim]")
                        continue
                    goal = goal_store.load(agent.session.key)
                    if goal is None or goal.status != "active":
                        console.print("[dim]No active goal to run.[/dim]")
                        continue
                    for turn_index in range(max_turns):
                        goal = goal_store.load(agent.session.key)
                        if goal is None or goal.status != "active":
                            break
                        console.print(f"[bold cyan]Goal turn {turn_index + 1}/{max_turns}[/bold cyan]")
                        await _run_agent_turn(_build_goal_loop_prompt())
                        goal = goal_store.load(agent.session.key)
                        if goal is None:
                            console.print("[dim]Goal cleared.[/dim]")
                            break
                        if goal.status != "active":
                            console.print(f"[dim]{_format_goal_status(goal)}[/dim]")
                            break
                    continue
                console.print("[dim]Usage: /goal status|start|run|complete|block|clear[/dim]")
                continue
            if command == "/remember":
                if not command_arg:
                    console.print("[dim]Usage: /remember <text>[/dim]")
                    continue
                with console.status("[bold cyan]storing memory...[/bold cyan]"):
                    result = await memory_store_tool.execute(content=command_arg)
                console.print(f"[dim]{result}[/dim]")
                continue
            if command == "/remember-thread":
                console.print("[dim]Exporting current thread to memory. This can take a while on long sessions.[/dim]")
                try:
                    with console.status("[bold cyan]remembering current thread...[/bold cyan]"):
                        await session_export_hook({
                            "session_key": agent.session.key,
                            "session": agent.session,
                        })
                    console.print("[dim]Current thread exported to memory.[/dim]")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    incident_id = diagnostics.record_exception(
                        exc,
                        boundary="cli.remember_thread",
                        session_key=getattr(getattr(agent, "session", None), "key", ""),
                    )
                    console.print(f"[red]{diagnostics.user_error_message(incident_id, str(exc))}[/red]")
                continue

            await _run_agent_turn(user_input)
    finally:
        try:
            if auto_export:
                with console.status("[bold cyan]exporting session...[/bold cyan]"):
                    await agent.close()
                console.print("[dim]Session exported.[/dim]")
            else:
                await agent.close()
            _print_usage_summary(console, agent.session_usage)
        finally:
            try:
                await _close_async_resource(smol_rag)
            finally:
                if worktree_state is not None and (worktree_state.discard_on_exit or not worktree_state.keep_on_exit):
                    worktree_state.context.cleanup()


@app.command(name="research-loop")
def research_loop(
    goal: str = typer.Argument(..., help="Recurring research goal"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
    agent: str = typer.Option("researcher", "--agent", "-a", help="Agent name from agents.yaml"),
    agents_config: str = typer.Option(DEFAULT_AGENTS_CONFIG, "--agents-config", help="Path to agents YAML config"),
    session_key: str = typer.Option("research-loop", "--session", "-s", help="Session key used across research runs"),
    interval: float = typer.Option(300.0, "--interval", "-i", help="Seconds to wait between research runs"),
    max_runs: Optional[int] = typer.Option(None, "--max-runs", help="Optional limit on research cycles"),
    auto_export: bool = typer.Option(False, "--auto-export/--no-auto-export", help="Auto-export session to memory on close"),
    show_actions: bool = typer.Option(True, "--show-actions/--hide-actions", help="Show live tool activity while the agent works"),
):
    """Run recurring automated research until stopped."""
    if interval <= 0:
        raise typer.BadParameter("--interval must be greater than 0")
    if max_runs is not None and max_runs <= 0:
        raise typer.BadParameter("--max-runs must be greater than 0")
    asyncio.run(
        _research_loop(
            goal=goal,
            workspace=workspace,
            agent_name=agent,
            agents_config=agents_config,
            session_key=session_key,
            interval=interval,
            max_runs=max_runs,
            auto_export=auto_export,
            show_actions=show_actions,
        )
    )


async def _research_loop(
    goal: str,
    workspace: str,
    agent_name: str,
    agents_config: str = DEFAULT_AGENTS_CONFIG,
    session_key: str = "research-loop",
    interval: float = 300.0,
    max_runs: Optional[int] = None,
    auto_export: bool = False,
    show_actions: bool = True,
):
    runtime = _build_cli_runtime(workspace)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    smol_rag = runtime.smol_rag
    session_manager = runtime.session_manager
    memory_dir = ensure_dir(paths.memory_docs_dir)
    register_session_end_hooks = _make_session_end_hook_registrar(paths, memory_dir, auto_export)

    agent = _build_multiagent(
        agent_name,
        agents_config,
        session_key,
        smol_rag,
        workspace,
        session_manager,
        auto_export,
        child_loop_registrar=register_session_end_hooks,
    )
    register_session_end_hooks(agent)

    stop_controller, esc_watcher = _create_research_loop_stop_controller()
    esc_hint = " Press Esc or Ctrl+C to stop." if getattr(esc_watcher, "active", False) else " Press Ctrl+C to stop."
    console.print(f"[bold green]{agent_name.capitalize()}[/bold green] research loop ready.{esc_hint}\n")
    exit_reason: str | None = None

    async def _run_cycle(prompt: str) -> str:
        streamed = False

        async def on_output(chunk: str):
            nonlocal streamed
            if not streamed:
                console.print()
                streamed = True
            console.file.write(chunk)
            console.file.flush()

        async def on_event(event: dict):
            if stop_controller.stop_requested:
                agent.request_stop()
            if not show_actions:
                return
            line = _format_action_event(event)
            if line:
                console.print(f"[dim]{line}[/dim]")

        process_task = asyncio.create_task(
            agent.process(
                prompt,
                on_output=on_output,
                on_event=on_event,
            )
        )
        stop_task = asyncio.create_task(stop_controller.wait())
        announced_stop = False
        try:
            while not process_task.done():
                done, _ = await asyncio.wait({process_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                if process_task in done:
                    break
                if stop_task in done and not announced_stop:
                    agent.request_stop()
                    console.print("[dim]Stop requested. Finishing the current research cycle...[/dim]")
                    announced_stop = True
            response = await process_task
        finally:
            if not stop_task.done():
                stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)

        if streamed:
            console.file.write("\n")
            console.file.flush()
            console.print()
        else:
            console.print()
            console.print(Markdown(response))
            console.print()
        return response

    runs_completed = 0
    try:
        while True:
            if stop_controller.stop_requested:
                exit_reason = stop_controller.reason
                break
            if max_runs is not None and runs_completed >= max_runs:
                break

            cycle_number = runs_completed + 1
            console.print(f"[bold cyan]Research cycle {cycle_number}[/bold cyan]")
            await _run_cycle(_build_research_loop_prompt(goal, runs_completed))
            runs_completed += 1

            if stop_controller.stop_requested:
                break
            if max_runs is not None and runs_completed >= max_runs:
                break

            console.print(
                f"[dim]Sleeping {interval:.1f}s before the next cycle.{esc_hint}[/dim]"
            )
            should_stop = await stop_controller.wait(timeout=interval)
            if should_stop:
                exit_reason = stop_controller.reason
                break
    except KeyboardInterrupt:
        stop_controller.request_stop("Stopped: Ctrl+C pressed.")
        agent.request_stop()
        exit_reason = stop_controller.reason
        console.print("[dim]Stop requested. Closing research loop...[/dim]")
    finally:
        try:
            esc_watcher.close()
            if auto_export:
                with console.status("[bold cyan]exporting session...[/bold cyan]"):
                    await agent.close()
                console.print("[dim]Session exported.[/dim]")
            else:
                await agent.close()
            exit_summary = _format_research_loop_exit(
                exit_reason or (stop_controller.reason if stop_controller.stop_requested else None),
                runs_completed=runs_completed,
                reached_run_limit=max_runs is not None and runs_completed >= max_runs,
            )
            console.print(f"[dim]{exit_summary}[/dim]")
            _print_usage_summary(console, agent.session_usage)
        finally:
            await _close_async_resource(smol_rag)


@app.command()
def ingest(
    path: str = typer.Argument(..., help="File or directory to ingest"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
):
    """Ingest documents into memory."""
    asyncio.run(_ingest(path, workspace))


async def _ingest(path: str, workspace: str):
    from app.utilities import get_docs, make_hash
    runtime = _build_cli_runtime(workspace)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    smol_rag = runtime.smol_rag
    try:
        path = _resolve_user_path(workspace_ctx, path)
        if os.path.isfile(path):
            files = [path]
        elif os.path.isdir(path):
            files = get_docs(path)
        else:
            console.print(f"[red]Not found:[/red] {path}")
            return

        ingested = 0
        skipped = 0
        for file_path in files:
            with open(file_path) as f:
                content = f.read()

            doc_id = make_hash(content, "doc_")
            if await smol_rag.source_doc_map.has_left(file_path) and await smol_rag.source_doc_map.equal_right(file_path, doc_id):
                console.print(f"[dim]Skipped (unchanged):[/dim] {file_path}")
                skipped += 1
                continue

            await smol_rag.ingest_text(content, source_id=file_path, save=False)
            console.print(f"[green]Ingested:[/green] {file_path}")
            ingested += 1

        if ingested > 0:
            await smol_rag._save_stores()
        console.print(f"\n[bold]Done:[/bold] {ingested} ingested, {skipped} skipped")
    finally:
        await _close_async_resource(smol_rag)


@app.command()
def watch(
    path: Optional[str] = typer.Option(
        None, "--path", "--memory-dir", "-p", "-d", help="Directory to watch (defaults to <workspace>/research)",
    ),
    interval: float = typer.Option(5.0, "--interval", "-i", help="Poll interval in seconds"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
):
    """Watch a workspace directory for changes and re-ingest."""
    asyncio.run(_watch(path, interval, workspace))


async def _watch(path: Optional[str], interval: float, workspace: str):
    from app.watcher import MemoryFileWatcher
    runtime = _build_cli_runtime(workspace)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    smol_rag = runtime.smol_rag
    watch_path = paths.research_dir if path is None else _resolve_workspace_path(workspace_ctx, path)
    watcher = MemoryFileWatcher(watch_path, smol_rag, poll_interval=interval)
    console.print(f"[bold green]Watching[/bold green] {watch_path} (poll every {interval}s)")
    try:
        await watcher.start()
    except KeyboardInterrupt:
        watcher.stop()
        console.print("[dim]Watcher stopped.[/dim]")
    finally:
        await _close_async_resource(smol_rag)


@app.command()
def serve(
    port: int = typer.Option(18789, "--port", "-p", help="WebSocket port"),
    token_issuer: str = typer.Option(
        "http://client:3000/mcp-tokens", "--token-issuer", help="MCP token issuer URL",
    ),
    gateway: str = typer.Option(
        "http://mcp-gateway:3200/mcp", "--gateway", help="MCP gateway URL",
    ),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
):
    """Start the WebSocket gateway server."""
    asyncio.run(_serve(port, token_issuer, gateway, workspace))


async def _serve(port: int, token_issuer: str, gateway_url: str, workspace: str):
    from app.gateway import Gateway
    gw = Gateway(port=port, token_issuer_url=token_issuer, gateway_url=gateway_url, workspace=workspace)
    await gw.start()


@app.command()
def recall(
    query: str = typer.Argument(..., help="Search query for past sessions"),
    mode: str = typer.Option("topic", "--mode", "-m", help="Search mode: topic or temporal"),
    days: float = typer.Option(7, "--days", "-d", help="For temporal mode: how many days back"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
):
    """Search past sessions using BM25 + semantic search."""
    asyncio.run(_recall(query, mode, days, workspace))


async def _recall(query: str, mode: str, days: float, workspace: str):
    runtime = _build_cli_runtime(workspace)
    smol_rag = runtime.smol_rag
    try:
        tool = MemoryRecallTool(smol_rag)
        result = await tool.execute(query=query, mode=mode, days=days)
        console.print(Markdown(result))
    finally:
        await _close_async_resource(smol_rag)


@app.command(name="index-sessions")
def index_sessions(
    sessions_dir: Optional[str] = typer.Option(None, "--sessions-dir", help="Sessions directory (defaults to <workspace>/.smolclaw/stores/sessions)"),
    memory_dir: Optional[str] = typer.Option(None, "--memory-dir", help="Memory docs directory (defaults to <workspace>/.smolclaw/memory)"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
):
    """Index all past sessions into SmolRAG for recall."""
    asyncio.run(_index_sessions(sessions_dir, memory_dir, workspace))


async def _index_sessions(sessions_dir: Optional[str], memory_dir: Optional[str], workspace: str):
    from app.session_indexer import index_all_sessions
    runtime = _build_cli_runtime(workspace)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    resolved_sessions_dir = paths.sessions_dir if sessions_dir is None else _resolve_workspace_path(workspace_ctx, sessions_dir)
    resolved_memory_dir = paths.memory_docs_dir if memory_dir is None else _resolve_workspace_path(workspace_ctx, memory_dir)
    smol_rag = runtime.smol_rag
    try:
        results = await index_all_sessions(resolved_sessions_dir, smol_rag, memory_dir=resolved_memory_dir)
        for key, source_id in results.items():
            console.print(f"[green]Indexed:[/green] {key} -> {source_id}")
        console.print(f"\n[bold]Done:[/bold] {len(results)} sessions indexed")
    finally:
        await _close_async_resource(smol_rag)


@app.command()
def reset(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
    logs: bool = typer.Option(False, "--logs", help="Clear workspace logs only"),
    memories: bool = typer.Option(False, "--memories", help="Clear memory documents except journals"),
    journals: bool = typer.Option(False, "--journals", help="Clear journal memory documents"),
    rag: bool = typer.Option(False, "--rag", help="Clear SmolRAG SQLite state"),
    kg: bool = typer.Option(False, "--kg", help="Clear knowledge graph state"),
    all_state: bool = typer.Option(False, "--all", help="Clear all mutable workspace state"),
):
    """Wipe all persistent data, or selected state such as logs, memories, RAG, and KG."""
    components = {
        name
        for name, enabled in (
            ("logs", logs),
            ("memories", memories),
            ("journals", journals),
            ("rag", rag),
            ("kg", kg),
        )
        if enabled
    }
    full_reset = all_state or not components
    target = "all mutable workspace state" if full_reset else ", ".join(sorted(components))
    if not force:
        confirm = typer.confirm(
            f"This will delete {target}. Continue?"
        )
        if not confirm:
            raise typer.Abort()
    asyncio.run(_reset(workspace, components=None if full_reset else components))


async def _reset(workspace: str, components: set[str] | None = None):
    from app.reset import reset_workspace, reset_workspace_components

    workspace_ctx = _workspace_context(workspace)
    deleted = (
        await reset_workspace(workspace_ctx)
        if components is None
        else await reset_workspace_components(workspace_ctx, components)
    )
    if deleted:
        for line in deleted:
            console.print(f"  [red]{line}[/red]")
        console.print(f"\n[bold]Reset complete.[/bold] {len(deleted)} action(s).")
    else:
        console.print("[dim]Nothing to reset — stores already clean.[/dim]")


@app.command(name="clear-logs")
def clear_logs_command(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    logs_dir: Optional[str] = typer.Option(None, "--logs-dir", help="Logs directory (defaults to <workspace>/.smolclaw/stores/logs)"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
):
    """Delete log files without touching memories, sessions, or indexes."""
    workspace_ctx = _workspace_context(workspace)
    paths = workspace_ctx.paths
    resolved_logs_dir = paths.log_dir if logs_dir is None else _resolve_workspace_path(workspace_ctx, logs_dir)
    if not force:
        confirm = typer.confirm(
            f"This will delete log files under '{resolved_logs_dir}'. Continue?"
        )
        if not confirm:
            raise typer.Abort()

    deleted = clear_logs(resolved_logs_dir)
    if deleted:
        for path in deleted:
            console.print(f"  [red]Deleted {path}[/red]")
        console.print(f"\n[bold]Log cleanup complete.[/bold] {len(deleted)} file(s) removed.")
    else:
        console.print("[dim]No log files to delete.[/dim]")


def _smolclaw_main(
    session_key: str = typer.Option("default", "--session", "-s", help="Session key"),
    workspace: str = typer.Option(".", "--workspace", "-w", help="Workspace root"),
    model: str = typer.Option(AGENT_MODEL, "--model", "-m", help="LLM model to use"),
    agents_config: str = typer.Option(DEFAULT_AGENTS_CONFIG, "--agents-config", help="Path to agents YAML config"),
    auto_export: bool = typer.Option(False, "--auto-export/--no-auto-export", help="Auto-export session to memory on close"),
    show_actions: bool = typer.Option(False, "--show-actions/--hide-actions", help="Show recent tool activity details while the agent works"),
):
    """Start SmolClaw's coding harness in the current workspace."""
    asyncio.run(
        _tui_chat_loop(
            session_key=session_key,
            workspace=workspace,
            model=model,
            agent_name="coder",
            agents_config=agents_config,
            auto_export=auto_export,
            show_actions=show_actions,
            display_label="SmolClaw",
        )
    )


def _should_start_default_harness(argv: list[str] | None = None) -> bool:
    args = list(sys.argv if argv is None else argv)
    return len(args) == 1


def entrypoint():
    if _should_start_default_harness():
        typer.run(_smolclaw_main)
        return
    app()


def code_entrypoint():
    typer.run(_smolclaw_main)


if __name__ == "__main__":
    entrypoint()
