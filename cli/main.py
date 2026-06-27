import asyncio
import contextlib
import contextvars
import inspect
import json
import logging
import os
import select
import shlex
import sys
import threading
import uuid
from dataclasses import dataclass, replace
from collections.abc import Callable
from typing import Optional

import typer
import yaml

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markdown import Markdown

from app import diagnostics
from app.agent_loop import AgentLoop
from app.approvals import (
    ApprovalRequestStore,
    format_approval_detail,
    format_approval_review_option,
)
from app.bootstrap import init_project_guidance
from app.checkpoints import CheckpointStore
from app.command_adapters import build_command_adapter_bundle
from app.definitions import (
    AGENT_MODEL, WORKSPACE_DIR, build_workspace_paths,
)
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
from app.runtime_builder import build_runtime_services
from app.runtime_config import RuntimeAdapterConfig, load_runtime_config
from app.session_export_hook import SessionExportHook
from app.runtime import build_configured_agent, build_master_registry
from app.session import SessionManager
from app.smol_rag import SmolRag
from app.tools.memory_tools import MemoryRecallTool, MemoryStoreTool
from app.utilities import ensure_dir
from app.workspace import WorkspaceContext
from app.run_trace import RunTraceStore
from app.run_views import build_run_status_view
from app.worktree import WorktreeRunner
from app.work_loop import (
    DEFAULT_WORK_LOOP_CONFIG,
    WorkLoopControl,
    WorkLoopConfig,
    WorkLoopJobStore,
    WorkLoopJobSupervisor,
    WorkLoopLedger,
    WorkLoopRunner,
    WorkLoopStopped,
    format_work_loop_jobs,
    format_work_item_status,
    format_work_items,
    terminate_active_work_loop_processes,
)
from cli.commands import (
    APPROVAL_CONTINUATION_PROMPT,
    SLASH_COMMANDS_HELP,
    SlashCommandDispatcher,
    _InteractiveWorktreeState,
    _build_goal_loop_prompt,
    _build_memory_review_prompt,
    _format_bootstrap_result,
    _format_diagnostics_paths,
    _format_goal_status,
    _format_goal_started,
    _format_inferred_goal_started,
    GOAL_COMMAND_HELP,
    infer_goal_from_thread,
    _parse_goal_command,
    _format_undo_result,
    _parse_goal_run_count,
    _resolve_approval_command,
    _resolve_memory_command,
    _resolve_trace_command,
    _resolve_worktree_command,
    parse_slash_command,
)

# Suppress noisy loggers from printing to console
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

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
work_loop_app = typer.Typer(
    help="Run Jira task automation and GitHub PR review follow-up loops.",
    rich_markup_mode=None,
)
app.add_typer(work_loop_app, name="work-loop")
console = Console()

DEFAULT_AGENTS_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.yaml")


@dataclass
class CliDependencies:
    console: Console = console
    prompt_session_factory: Callable = PromptSession
    async_runner: Callable = asyncio.run
    runtime_builder: Callable = build_runtime_services
    agent_builder: Callable = build_configured_agent
    tool_registry_builder: Callable = build_master_registry
    worktree_runner_factory: Callable = WorktreeRunner
    default_chat_agent_builder: Callable | None = None
    multiagent_builder: Callable | None = None
    memory_store_tool_factory: Callable = MemoryStoreTool
    session_export_hook_factory: Callable = SessionExportHook
    goal_store_factory: Callable = GoalLedgerStore
    checkpoint_store_factory: Callable = CheckpointStore
    approval_store_factory: Callable = ApprovalRequestStore
    tui_factory: Callable | None = None
    run_once_runner: Callable | None = None
    tui_chat_loop_runner: Callable | None = None
    research_loop_runner: Callable | None = None
    work_loop_supervisor_factory: Callable = WorkLoopJobSupervisor.for_workspace
    work_loop_runner_factory: Callable = WorkLoopRunner
    research_stop_controller_factory: Callable | None = None


_CLI_DEPENDENCIES: contextvars.ContextVar[CliDependencies | None] = contextvars.ContextVar(
    "smolclaw_cli_dependencies",
    default=None,
)


def get_cli_dependencies(deps: CliDependencies | None = None) -> CliDependencies:
    return deps or _CLI_DEPENDENCIES.get() or CliDependencies()


@contextlib.contextmanager
def override_cli_dependencies(**overrides):
    token = _CLI_DEPENDENCIES.set(replace(get_cli_dependencies(), **overrides))
    try:
        yield _CLI_DEPENDENCIES.get()
    finally:
        _CLI_DEPENDENCIES.reset(token)


def _accepts_deps(func: Callable) -> bool:
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return "deps" in params or any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())


def _call_with_optional_deps(func: Callable, *args, deps: CliDependencies, **kwargs):
    if _accepts_deps(func):
        return func(*args, deps=deps, **kwargs)
    return func(*args, **kwargs)


def _call_factory_with_supported_kwargs(factory: Callable, **kwargs):
    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return factory(**kwargs)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return factory(**kwargs)
    supported = {name: value for name, value in kwargs.items() if name in params}
    return factory(**supported)


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
    from app.pricing import format_costs

    event_type = event.get("type")

    if event_type == "llm":
        if event.get("phase") == "start":
            return "thinking..."
        if event.get("phase") == "end":
            duration_s = max(0, event.get("duration_ms", 0)) / 1000
            tokens = event.get("total_tokens", 0)
            costs = event.get("estimated_cost") or {}
            suffix = f", {format_costs(costs, compact=True)}" if costs else ""
            return f"thought: {tokens:,} tokens ({duration_s:.1f}s{suffix})"
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
    from app.pricing import format_costs

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
    console.print(f"  Estimated cost: {format_costs(session_usage.cost_summary())}")
    by_cat = session_usage.by_category()
    if len(by_cat) > 1:
        for cat, data in sorted(by_cat.items(), key=lambda x: x[1]["total_tokens"], reverse=True):
            console.print(
                f"    {cat}: {data['total_tokens']:,} tokens "
                f"({data['count']} call{'s' if data['count'] != 1 else ''}, "
                f"{data['duration_ms'] / 1000:.1f}s, {format_costs(data.get('estimated_cost') or {})})"
            )


def _workspace_context(workspace_root: str) -> WorkspaceContext:
    return WorkspaceContext.from_root(workspace_root).ensure_dirs()


def _workspace_for_config(workspace: str | WorkspaceContext) -> WorkspaceContext:
    return workspace if isinstance(workspace, WorkspaceContext) else WorkspaceContext.from_root(workspace)


def _command_adapters_for_workspace(workspace: str | WorkspaceContext):
    workspace_ctx = _workspace_for_config(workspace)
    adapter_config = load_runtime_config(workspace_ctx)
    return build_command_adapter_bundle(adapter_config.command, workspace=workspace_ctx)


def _command_provider_for_workspace(workspace: str | WorkspaceContext) -> str:
    adapter_config = load_runtime_config(_workspace_for_config(workspace))
    return adapter_config.command.provider


def _requires_sandbox_source_isolation(workspace: str | WorkspaceContext) -> bool:
    return _command_provider_for_workspace(workspace) == "docker"


def _prepare_isolated_workspace(
    workspace: str,
    *,
    deps: CliDependencies,
    worktree: bool,
    copy_dirty_worktree: bool,
) -> tuple[object | None, str | WorkspaceContext]:
    sandbox_isolation = _requires_sandbox_source_isolation(workspace)
    if not (worktree or sandbox_isolation):
        return None, workspace
    worktree_ctx = _build_worktree_runner(workspace, deps).create(
        workspace,
        f"smolclaw-{uuid.uuid4().hex[:12]}",
        copy_dirty=copy_dirty_worktree or sandbox_isolation,
    )
    return worktree_ctx, WorkspaceContext.from_root(
        worktree_ctx.path,
        state_root=_state_root_for_workspace(workspace),
    )


def _build_worktree_runner(workspace: str | WorkspaceContext, deps: CliDependencies):
    command_adapters = _command_adapters_for_workspace(workspace)
    return _call_factory_with_supported_kwargs(
        deps.worktree_runner_factory,
        command_runner=command_adapters.infrastructure_runner,
    )


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
    deps: CliDependencies | None = None,
):
    deps = get_cli_dependencies(deps)
    return deps.runtime_builder(
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
                              agent_configs=None, session_manager=None, enable_subagents: bool = False,
                              deps: CliDependencies | None = None):
    deps = get_cli_dependencies(deps)
    runtime = _build_cli_runtime(
        workspace,
        agent_configs=agent_configs,
        enable_subagents=enable_subagents,
        llm=llm,
        smol_rag=smol_rag,
        session_manager=session_manager,
        deps=deps,
    )
    return deps.tool_registry_builder(runtime.env)


def _build_multiagent(
    agent_name: str,
    agents_config_path: str,
    session_key: str,
    smol_rag: SmolRag,
    workspace: str | WorkspaceContext,
    session_manager: SessionManager,
    auto_export: bool,
    child_loop_registrar=None,
    model_override: Optional[str] = None,
    deps: CliDependencies | None = None,
) -> AgentLoop:
    deps = get_cli_dependencies(deps)
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
        deps=deps,
    ).env
    return deps.agent_builder(
        config=configs[agent_name],
        env=env,
        session_key_prefix=session_key,
        child_loop_registrar=child_loop_registrar,
        model_override=model_override if model_override != AGENT_MODEL else None,
    )


def _build_default_chat_agent(
    agents_config_path: str,
    session_key: str,
    model: str,
    smol_rag: SmolRag,
    workspace: str | WorkspaceContext,
    session_manager: SessionManager,
    child_loop_registrar=None,
    deps: CliDependencies | None = None,
) -> AgentLoop:
    deps = get_cli_dependencies(deps)
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
        deps=deps,
    ).env
    return deps.agent_builder(
        config=configs["default"],
        env=env,
        session_key=session_key,
        model_override=model if model != AGENT_MODEL else None,
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
    deps = get_cli_dependencies()
    runner = deps.tui_chat_loop_runner or _tui_chat_loop
    deps.async_runner(_call_with_optional_deps(
        runner,
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
        deps=deps,
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
    deps = get_cli_dependencies()
    runner = deps.run_once_runner or _run_once
    result = deps.async_runner(_call_with_optional_deps(
        runner,
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
        deps=deps,
    ))
    deps.console.print(json.dumps(result, indent=2, sort_keys=True))


def _load_work_loop_config(
    config_path: str,
    project: str = "",
    *,
    max_concurrency: int | None = None,
    adapter_config: RuntimeAdapterConfig | None = None,
) -> WorkLoopConfig:
    config = WorkLoopConfig.load(config_path, project=project)
    if adapter_config is not None:
        explicit_task_source, explicit_code_review = _work_loop_explicit_adapter_types(config_path)
        config = WorkLoopConfig(
            **{
                **config.__dict__,
                "task_source_type": config.task_source_type if explicit_task_source else adapter_config.task_source.provider,
                "code_review_type": config.code_review_type if explicit_code_review else adapter_config.code_review.provider,
            }
        )
    if max_concurrency is not None:
        config = WorkLoopConfig(
            **{
                **config.__dict__,
                "max_concurrency": max_concurrency,
            }
        )
    return config


def _work_loop_explicit_adapter_types(config_path: str) -> tuple[bool, bool]:
    if not config_path or not os.path.exists(config_path):
        return False, False
    with open(config_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return False, False
    task_source = data.get("task_source")
    code_review = data.get("code_review")
    return (
        "task_source_type" in data or (isinstance(task_source, dict) and "type" in task_source),
        "code_review_type" in data or (isinstance(code_review, dict) and "type" in code_review),
    )


def _build_work_loop_runner(
    *,
    workspace: str,
    config_path: str,
    project: str = "",
    max_concurrency: int | None = None,
    deps: CliDependencies | None = None,
) -> WorkLoopRunner:
    deps = get_cli_dependencies(deps)
    workspace_ctx = _workspace_context(workspace)
    adapter_config = load_runtime_config(workspace_ctx)
    config = _load_work_loop_config(
        config_path,
        project=project,
        max_concurrency=max_concurrency,
        adapter_config=adapter_config,
    )
    command_adapters = build_command_adapter_bundle(adapter_config.command)
    return _call_factory_with_supported_kwargs(
        deps.work_loop_runner_factory,
        workspace=workspace_ctx,
        config=config,
        command_runner=command_adapters.infrastructure_runner,
    )


def _work_loop_worker_args(
    *,
    workspace: str,
    config_path: str,
    project: str = "",
    limit: int | None = None,
    max_concurrency: int | None = None,
    dry_run: bool = False,
) -> list[str]:
    args = ["--workspace", workspace, "--config", config_path]
    if project:
        args.extend(["--project", project])
    if limit is not None:
        args.extend(["--limit", str(limit)])
    if max_concurrency is not None:
        args.extend(["--max-concurrency", str(max_concurrency)])
    if dry_run:
        args.append("--dry-run")
    return args


def _start_work_loop_job(
    *,
    workspace: str,
    mode: str,
    worker_args: list[str],
    deps: CliDependencies | None = None,
) -> str:
    deps = get_cli_dependencies(deps)
    workspace_ctx = _workspace_context(workspace)
    job = deps.work_loop_supervisor_factory(workspace_ctx).start(mode, worker_args)
    return f"Started work-loop job {job.job_id} [{job.state}] pid:{job.pid or '<none>'} mode:{mode}"


def _run_work_loop_mode(
    *,
    mode: str,
    workspace: str,
    config_path: str,
    project: str = "",
    limit: int | None = None,
    max_concurrency: int | None = None,
    dry_run: bool = False,
    job_id: str | None = None,
    deps: CliDependencies | None = None,
) -> str:
    deps = get_cli_dependencies(deps)
    workspace_ctx = _workspace_context(workspace)
    adapter_config = load_runtime_config(workspace_ctx)
    config = _load_work_loop_config(
        config_path,
        project=project,
        max_concurrency=max_concurrency,
        adapter_config=adapter_config,
    )
    command_adapters = build_command_adapter_bundle(adapter_config.command)
    runner = _call_factory_with_supported_kwargs(
        deps.work_loop_runner_factory,
        workspace=workspace_ctx,
        config=config,
        job_id=job_id,
        command_runner=command_adapters.infrastructure_runner,
    )
    if mode == "tasks":
        return format_work_items(runner.run_tasks(limit=limit, dry_run=dry_run))
    if mode == "reviews":
        return format_work_items(runner.run_reviews(dry_run=dry_run))
    if mode == "run":
        review_items, task_items = runner.run_all(limit=limit, dry_run=dry_run)
        return "\n\n".join([
            "Review follow-up:",
            format_work_items(review_items),
            "Jira tasks:",
            format_work_items(task_items),
        ])
    raise ValueError(f"Unsupported work-loop mode: {mode}")


def _pop_flag(args: list[str], *names: str, default: str | None = None) -> str | None:
    for name in names:
        if name not in args:
            continue
        index = args.index(name)
        if index == len(args) - 1:
            raise ValueError(f"{name} expects a value")
        value = args[index + 1]
        del args[index:index + 2]
        return value
    return default


def _pop_bool_flag(args: list[str], *names: str) -> bool:
    found = False
    for name in names:
        while name in args:
            args.remove(name)
            found = True
    return found


def _int_option(value: str | None, *, label: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} expects an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{label} expects a positive integer")
    return parsed


def _resolve_work_loop_command(
    workspace: WorkspaceContext,
    command_arg: str,
    *,
    deps: CliDependencies | None = None,
) -> str:
    deps = get_cli_dependencies(deps)
    try:
        parts = shlex.split(command_arg)
    except ValueError as exc:
        return f"Error: {exc}"
    if not parts or parts[0] in {"help", "-h", "--help"}:
        return "\n".join([
            "Work-loop commands:",
            "  /work-loop list [--state STATE]",
            "  /work-loop jobs",
            "  /work-loop status <JIRA_KEY_OR_PR_NUMBER>",
            "  /work-loop tasks --project KEY [--limit N] [--max-concurrency N] [--config PATH] [--dry-run] [--foreground]",
            "  /work-loop reviews [--config PATH] [--dry-run] [--foreground]",
            "  /work-loop run --project KEY [--limit N] [--max-concurrency N] [--config PATH] [--dry-run] [--foreground]",
            "  /work-loop stop [job-id|all] [reason]",
            "  /work-loop pause [job-id|all] [reason]",
            "  /work-loop resume [job-id|all]",
            "  /work-loop state",
        ])
    subcommand = parts.pop(0)
    try:
        control = WorkLoopControl.for_workspace(workspace)
        if subcommand == "stop":
            target = parts.pop(0) if parts and (parts[0] == "all" or parts[0].startswith("job-")) else "all"
            reason = " ".join(parts).strip() or "User requested stop."
            if target == "all":
                control.stop(reason)
                terminate_active_work_loop_processes()
            jobs = deps.work_loop_supervisor_factory(workspace).stop(target, reason=reason)
            suffix = f" ({len(jobs)} job(s))" if jobs else ""
            return f"Work-loop stop requested for {target}: {reason}{suffix}"
        if subcommand == "pause":
            target = parts.pop(0) if parts and (parts[0] == "all" or parts[0].startswith("job-")) else "all"
            reason = " ".join(parts).strip() or "User requested pause."
            if target == "all":
                control.pause(reason)
            jobs = deps.work_loop_supervisor_factory(workspace).pause(target, reason=reason)
            suffix = f" ({len(jobs)} job(s))" if jobs else ""
            return f"Work-loop pause requested for {target}: {reason}{suffix}"
        if subcommand == "resume":
            target = parts.pop(0) if parts and (parts[0] == "all" or parts[0].startswith("job-")) else "all"
            if parts:
                return f"Error: unexpected arguments for /work-loop resume: {' '.join(parts)}"
            if target == "all":
                control.resume()
            jobs = deps.work_loop_supervisor_factory(workspace).resume(target)
            suffix = f" ({len(jobs)} job(s))" if jobs else ""
            return f"Work-loop resumed for {target}; stop and pause files cleared.{suffix}"
        if subcommand in {"state", "control"}:
            if parts:
                return f"Error: unexpected arguments for /work-loop state: {' '.join(parts)}"
            return f"Work-loop state: {control.status()}"
        if subcommand == "jobs":
            if parts:
                return f"Error: unexpected arguments for /work-loop jobs: {' '.join(parts)}"
            return format_work_loop_jobs(WorkLoopJobStore.for_workspace(workspace).list())
        config_path = _pop_flag(parts, "--config", default=DEFAULT_WORK_LOOP_CONFIG) or DEFAULT_WORK_LOOP_CONFIG
        dry_run = _pop_bool_flag(parts, "--dry-run")
        foreground = _pop_bool_flag(parts, "--foreground")
        if subcommand == "list":
            state = _pop_flag(parts, "--state", default="all") or "all"
            if parts:
                return f"Error: unexpected arguments for /work-loop list: {' '.join(parts)}"
            return format_work_items(WorkLoopLedger.for_workspace(workspace).list(state))
        if subcommand == "status":
            target = parts.pop(0) if parts else ""
            if not target:
                return "Usage: /work-loop status <JIRA_KEY_OR_PR_NUMBER>"
            if parts:
                return f"Error: unexpected arguments for /work-loop status: {' '.join(parts)}"
            if target.startswith("job-"):
                job = WorkLoopJobStore.for_workspace(workspace).load(target)
                return format_work_loop_jobs([job] if job else [])
            ledger = WorkLoopLedger.for_workspace(workspace)
            item = ledger.load(target)
            if item is None and target.isdigit():
                pr_number = int(target)
                item = next((candidate for candidate in ledger.list("all") if candidate.pr_number == pr_number), None)
            return format_work_item_status(item)
        if subcommand in {"tasks", "run"}:
            project = _pop_flag(parts, "--project", "-p")
            if not project:
                return f"Usage: /work-loop {subcommand} --project KEY"
            limit = _int_option(_pop_flag(parts, "--limit"), label="--limit")
            max_concurrency = _int_option(_pop_flag(parts, "--max-concurrency"), label="--max-concurrency")
            if parts:
                return f"Error: unexpected arguments for /work-loop {subcommand}: {' '.join(parts)}"
            worker_args = _work_loop_worker_args(
                workspace=workspace.root_dir,
                config_path=config_path,
                project=project,
                limit=limit,
                max_concurrency=max_concurrency,
                dry_run=dry_run,
            )
            if not foreground:
                return _start_work_loop_job(workspace=workspace.root_dir, mode=subcommand, worker_args=worker_args, deps=deps)
            return _run_work_loop_mode(
                mode=subcommand,
                workspace=workspace.root_dir,
                config_path=config_path,
                project=project,
                limit=limit,
                max_concurrency=max_concurrency,
                dry_run=dry_run,
                deps=deps,
            )
        if subcommand == "reviews":
            if parts:
                return f"Error: unexpected arguments for /work-loop reviews: {' '.join(parts)}"
            worker_args = _work_loop_worker_args(
                workspace=workspace.root_dir,
                config_path=config_path,
                dry_run=dry_run,
            )
            if not foreground:
                return _start_work_loop_job(workspace=workspace.root_dir, mode="reviews", worker_args=worker_args, deps=deps)
            return _run_work_loop_mode(
                mode="reviews",
                workspace=workspace.root_dir,
                config_path=config_path,
                dry_run=dry_run,
                deps=deps,
            )
    except RuntimeError as exc:
        return f"Error: {exc}"
    except ValueError as exc:
        return f"Error: {exc}"
    return "Usage: /work-loop list|status|tasks|reviews|run"


@work_loop_app.command(name="worker", hidden=True)
def work_loop_worker(
    job_id: str = typer.Option(..., "--job-id", help="Work-loop job id"),
    mode: str = typer.Option(..., "--mode", help="Worker mode: tasks, reviews, or run"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
    config_path: str = typer.Option(DEFAULT_WORK_LOOP_CONFIG, "--config", help="Work-loop YAML config"),
    project: str = typer.Option("", "--project", "-p", help="Jira project key to search"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum tickets to start"),
    max_concurrency: Optional[int] = typer.Option(None, "--max-concurrency", help="Override configured concurrency"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Exercise discovery without changing branches"),
):
    """Internal worker process entrypoint."""
    workspace_ctx = _workspace_context(workspace)
    store = WorkLoopJobStore.for_workspace(workspace_ctx)
    job = store.load(job_id)
    if job is not None:
        job.state = "running"
        job.message = "Worker started."
        store.save(job)
    try:
        output = _run_work_loop_mode(
            mode=mode,
            workspace=workspace,
            config_path=config_path,
            project=project,
            limit=limit,
            max_concurrency=max_concurrency,
            dry_run=dry_run,
            job_id=job_id,
        )
        if job is not None:
            job.state = "complete"
            job.exit_code = 0
            job.message = output[:1000]
            store.save(job)
        console.print(output, markup=False)
    except WorkLoopStopped as exc:
        if job is not None:
            job.state = "stopped"
            job.exit_code = 130
            job.message = str(exc)
            store.save(job)
        console.print(f"Stopped: {exc}", markup=False)
        raise typer.Exit(130) from exc
    except Exception as exc:
        if job is not None:
            job.state = "failed"
            job.exit_code = 1
            job.message = str(exc)
            store.save(job)
        console.print(f"Error: {exc}", markup=False)
        raise typer.Exit(1) from exc


@work_loop_app.command(name="tasks")
def work_loop_tasks(
    project: str = typer.Option(..., "--project", "-p", help="Jira project key to search"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
    config_path: str = typer.Option(DEFAULT_WORK_LOOP_CONFIG, "--config", help="Work-loop YAML config"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum tickets to start"),
    max_concurrency: Optional[int] = typer.Option(None, "--max-concurrency", help="Override configured concurrency"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Select and record candidates without starting implementation"),
    foreground: bool = typer.Option(False, "--foreground", help="Run synchronously instead of starting a background job"),
):
    """Search Jira, start suitable coding tasks, push branches, and create PRs."""
    try:
        if foreground:
            output = _run_work_loop_mode(
                mode="tasks",
                workspace=workspace,
                config_path=config_path,
                project=project,
                limit=limit,
                max_concurrency=max_concurrency,
                dry_run=dry_run,
            )
        else:
            output = _start_work_loop_job(
                workspace=workspace,
                mode="tasks",
                worker_args=_work_loop_worker_args(
                    workspace=workspace,
                    config_path=config_path,
                    project=project,
                    limit=limit,
                    max_concurrency=max_concurrency,
                    dry_run=dry_run,
                ),
            )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(output, markup=False)


@work_loop_app.command(name="reviews")
def work_loop_reviews(
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
    config_path: str = typer.Option(DEFAULT_WORK_LOOP_CONFIG, "--config", help="Work-loop YAML config"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report PRs needing action without changing branches"),
    foreground: bool = typer.Option(False, "--foreground", help="Run synchronously instead of starting a background job"),
):
    """Check GitHub review feedback for PRs created by the work loop and fix actionable comments."""
    try:
        if foreground:
            output = _run_work_loop_mode(
                mode="reviews",
                workspace=workspace,
                config_path=config_path,
                dry_run=dry_run,
            )
        else:
            output = _start_work_loop_job(
                workspace=workspace,
                mode="reviews",
                worker_args=_work_loop_worker_args(
                    workspace=workspace,
                    config_path=config_path,
                    dry_run=dry_run,
                ),
            )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(output, markup=False)


@work_loop_app.command(name="run")
def work_loop_run(
    project: str = typer.Option(..., "--project", "-p", help="Jira project key to search"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
    config_path: str = typer.Option(DEFAULT_WORK_LOOP_CONFIG, "--config", help="Work-loop YAML config"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum new tickets to start after reviews"),
    max_concurrency: Optional[int] = typer.Option(None, "--max-concurrency", help="Override configured concurrency"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Exercise selection/review discovery without changing branches"),
    foreground: bool = typer.Option(False, "--foreground", help="Run synchronously instead of starting a background job"),
):
    """Run one combined cycle: PR review follow-up first, then new Jira work."""
    try:
        if foreground:
            output = _run_work_loop_mode(
                mode="run",
                workspace=workspace,
                config_path=config_path,
                project=project,
                limit=limit,
                max_concurrency=max_concurrency,
                dry_run=dry_run,
            )
        else:
            output = _start_work_loop_job(
                workspace=workspace,
                mode="run",
                worker_args=_work_loop_worker_args(
                    workspace=workspace,
                    config_path=config_path,
                    project=project,
                    limit=limit,
                    max_concurrency=max_concurrency,
                    dry_run=dry_run,
                ),
            )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(output, markup=False)


@work_loop_app.command(name="list")
def work_loop_list(
    state: str = typer.Option("all", "--state", help="Filter by state: active, blocked, open-pr, done, all"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """List tickets and PRs the work loop has worked on."""
    ledger = WorkLoopLedger.for_workspace(_workspace_context(workspace))
    console.print(format_work_items(ledger.list(state)), markup=False)


@work_loop_app.command(name="jobs")
def work_loop_jobs(
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """List work-loop background jobs."""
    jobs = WorkLoopJobStore.for_workspace(_workspace_context(workspace)).list()
    console.print(format_work_loop_jobs(jobs), markup=False)


@work_loop_app.command(name="status")
def work_loop_status(
    ticket_or_pr: str = typer.Argument(..., help="Jira key or PR number"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """Show one work-loop ticket/PR record."""
    workspace_ctx = _workspace_context(workspace)
    if ticket_or_pr.startswith("job-"):
        job = WorkLoopJobStore.for_workspace(workspace_ctx).load(ticket_or_pr)
        console.print(format_work_loop_jobs([job] if job else []), markup=False)
        return
    ledger = WorkLoopLedger.for_workspace(workspace_ctx)
    item = ledger.load(ticket_or_pr)
    if item is None and ticket_or_pr.isdigit():
        pr_number = int(ticket_or_pr)
        item = next((candidate for candidate in ledger.list("all") if candidate.pr_number == pr_number), None)
    console.print(format_work_item_status(item), markup=False)


@work_loop_app.command(name="stop")
def work_loop_stop(
    target: str = typer.Argument("all", help="Job id or all"),
    reason: str = typer.Argument("User requested stop.", help="Stop reason"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """Stop one or all work-loop jobs."""
    workspace_ctx = _workspace_context(workspace)
    if target == "all":
        WorkLoopControl.for_workspace(workspace_ctx).stop(reason)
        terminate_active_work_loop_processes()
    jobs = WorkLoopJobSupervisor.for_workspace(workspace_ctx).stop(target, reason=reason)
    console.print(f"Work-loop stop requested for {target}: {reason} ({len(jobs)} job(s))", markup=False)


@work_loop_app.command(name="pause")
def work_loop_pause(
    target: str = typer.Argument("all", help="Job id or all"),
    reason: str = typer.Argument("User requested pause.", help="Pause reason"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """Pause one or all work-loop jobs before their next step."""
    workspace_ctx = _workspace_context(workspace)
    if target == "all":
        WorkLoopControl.for_workspace(workspace_ctx).pause(reason)
    jobs = WorkLoopJobSupervisor.for_workspace(workspace_ctx).pause(target, reason=reason)
    console.print(f"Work-loop pause requested for {target}: {reason} ({len(jobs)} job(s))", markup=False)


@work_loop_app.command(name="resume")
def work_loop_resume(
    target: str = typer.Argument("all", help="Job id or all"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """Resume one or all paused work-loop jobs."""
    workspace_ctx = _workspace_context(workspace)
    if target == "all":
        WorkLoopControl.for_workspace(workspace_ctx).resume()
    jobs = WorkLoopJobSupervisor.for_workspace(workspace_ctx).resume(target)
    console.print(f"Work-loop resumed for {target}; stop and pause files cleared. ({len(jobs)} job(s))", markup=False)


@work_loop_app.command(name="state")
def work_loop_state(
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """Show work-loop global control state."""
    console.print(f"Work-loop state: {WorkLoopControl.for_workspace(_workspace_context(workspace)).status()}", markup=False)


@app.command(name="init")
def init_command(
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """Create or update SmolClaw guidance in AGENTS.md."""
    result = init_project_guidance(_workspace_context(workspace))
    console.print(_format_bootstrap_result(result))


@app.command(name="doctor")
def doctor_command(
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root"),
):
    """Check local runtime readiness."""
    from app.doctor import format_doctor_report, run_doctor

    console.print(format_doctor_report(run_doctor(workspace)))


@app.command(name="memory-eval")
def memory_eval_command(
    suite: list[str] = typer.Argument(..., help="One or more memory eval YAML suites"),
    mode: str = typer.Option("deterministic", "--mode", help="Eval mode: deterministic, rag, or answer"),
    output: Optional[str] = typer.Option(None, "--output", help="Directory for eval report JSON"),
    top_k: int = typer.Option(5, "--top-k", help="Number of corpus sources to retrieve per question"),
    model: Optional[str] = typer.Option(None, "--model", help="Completion model for --mode answer"),
    baseline: Optional[str] = typer.Option(None, "--baseline", help="Optional prior report/suite JSON for score deltas"),
    write_baseline: Optional[str] = typer.Option(None, "--write-baseline", help="Optional path to write the current suite JSON"),
    max_score_drop: Optional[float] = typer.Option(None, "--max-score-drop", help="Fail if any baseline score delta drops by more than this amount"),
):
    """Run a corpus-memory and knowledge-graph eval suite."""
    from app.memory_eval import (
        MemoryEvalRunner,
        build_memory_eval_suite_report,
        load_memory_eval_baseline_scores,
        memory_eval_regressions,
        memory_eval_report_to_json,
        memory_eval_suite_report_to_json,
    )

    if mode not in {"deterministic", "rag", "answer"}:
        raise typer.BadParameter("--mode must be one of: deterministic, rag, answer")
    runner = MemoryEvalRunner(
        mode=mode,  # type: ignore[arg-type]
        output_dir=output,
        top_k=top_k,
        answer_model=model,
    )
    reports = [runner.run(suite_path) for suite_path in suite]
    if len(reports) == 1 and not baseline and not write_baseline:
        typer.echo(memory_eval_report_to_json(reports[0]))
        raise typer.Exit(0 if reports[0].status == "passed" else 2)
    baseline_scores = load_memory_eval_baseline_scores(baseline) if baseline else {}
    suite_report = build_memory_eval_suite_report(reports, baseline=baseline_scores)
    regressions = (
        memory_eval_regressions(suite_report, max_score_drop=max_score_drop)
        if max_score_drop is not None
        else []
    )
    if regressions:
        suite_report["status"] = "failed"
        suite_report["regressions"] = regressions
    if write_baseline:
        with open(write_baseline, "w", encoding="utf-8") as handle:
            json.dump(suite_report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    typer.echo(memory_eval_suite_report_to_json(suite_report))
    raise typer.Exit(0 if suite_report["status"] == "passed" else 2)


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
    deps: CliDependencies | None = None,
) -> dict:
    deps = get_cli_dependencies(deps)
    worktree_ctx, active_workspace = _prepare_isolated_workspace(
        workspace,
        deps=deps,
        worktree=worktree,
        copy_dirty_worktree=copy_dirty_worktree,
    )
    agent = None
    smol_rag = None
    responses: list[str] = []
    try:
        runtime = _build_cli_runtime(active_workspace, deps=deps)
        workspace_ctx = runtime.workspace
        paths = workspace_ctx.paths
        smol_rag = runtime.smol_rag
        session_manager = runtime.session_manager
        goal_store = deps.goal_store_factory(paths.ledgers_dir)
        if agent_name:
            builder = deps.multiagent_builder or _build_multiagent
            agent = _call_with_optional_deps(
                builder,
                agent_name,
                agents_config,
                session_key,
                smol_rag,
                active_workspace,
                session_manager,
                auto_export,
                model_override=model,
                deps=deps,
            )
        else:
            builder = deps.default_chat_agent_builder or _build_default_chat_agent
            agent = _call_with_optional_deps(
                builder,
                agents_config_path=agents_config,
                session_key=session_key,
                model=model,
                smol_rag=smol_rag,
                workspace=active_workspace,
                session_manager=session_manager,
                deps=deps,
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
        current_goal = goal_store.load(agent.session.key)
        worktree_diff = worktree_ctx.diff() if worktree_ctx is not None else None
        worktree_metadata = (
            worktree_ctx.isolation_metadata.to_dict()
            if worktree_ctx is not None and hasattr(worktree_ctx, "isolation_metadata")
            else None
        )
        latest_trace = trace_store.latest_summary(agent.session.key)
        sandbox_metadata = getattr(getattr(runtime, "env", None), "sandbox_metadata", None)
        if latest_trace is not None and (worktree_metadata or sandbox_metadata):
            if worktree_metadata:
                latest_trace.metadata["worktree"] = worktree_metadata
            if sandbox_metadata:
                latest_trace.metadata["sandbox"] = sandbox_metadata
            trace_store.save_summary(latest_trace)
        run_status_view = build_run_status_view(
            session_key=agent.session.key,
            trace_store=trace_store,
            goal_store=goal_store,
            worktree_path=worktree_ctx.path if worktree_ctx is not None else None,
            worktree_diff=worktree_diff,
            worktree_metadata=worktree_metadata,
            sandbox_metadata=sandbox_metadata,
        )
        return {
            "session_key": agent.session.key,
            "status": current_goal.status if current_goal is not None else "complete",
            "loop_status": getattr(current_goal, "loop_status", None) if current_goal is not None else None,
            "goal_run_id": getattr(current_goal, "run_id", None) if current_goal is not None else None,
            "pending_approvals": getattr(current_goal, "pending_approvals", 0) if current_goal is not None else 0,
            "response": responses[-1] if responses else "",
            "responses": responses,
            "turns": len(responses),
            "trace_path": run_status_view.trace_path,
            "trace_summary_path": run_status_view.summary_path,
            "ledger_path": run_status_view.ledger_path,
            "stop_reason": run_status_view.stop_reason,
            "worktree_path": run_status_view.worktree_path,
            "worktree_diff": worktree_diff,
            "run_status": run_status_view.to_dict(),
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
    deps: CliDependencies | None = None,
):
    deps = get_cli_dependencies(deps)
    console = deps.console
    worktree_state: _InteractiveWorktreeState | None = None
    worktree_ctx, active_workspace = _prepare_isolated_workspace(
        workspace,
        deps=deps,
        worktree=worktree,
        copy_dirty_worktree=copy_dirty_worktree,
    )
    if worktree_ctx is not None:
        worktree_state = _InteractiveWorktreeState(
            context=worktree_ctx,
            state_root=_state_root_for_workspace(workspace),
            keep_on_exit=keep_worktree,
        )
    runtime = _build_cli_runtime(active_workspace, deps=deps)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    smol_rag = runtime.smol_rag
    session_manager = runtime.session_manager
    goal_store = deps.goal_store_factory(paths.ledgers_dir)
    checkpoint_store = deps.checkpoint_store_factory(paths.checkpoints_dir)
    approval_store = deps.approval_store_factory(paths.approvals_dir)
    memory_dir = ensure_dir(paths.memory_docs_dir)
    register_session_end_hooks = _make_session_end_hook_registrar(paths, memory_dir, auto_export)

    if agent_name:
        builder = deps.multiagent_builder or _build_multiagent
        agent = _call_with_optional_deps(
            builder,
            agent_name,
            agents_config,
            session_key,
            smol_rag,
            active_workspace,
            session_manager,
            auto_export,
            child_loop_registrar=register_session_end_hooks,
            model_override=model,
            deps=deps,
        )
        label = display_label or agent_name.capitalize()
    else:
        builder = deps.default_chat_agent_builder or _build_default_chat_agent
        agent = _call_with_optional_deps(
            builder,
            agents_config_path=agents_config,
            session_key=session_key,
            model=model,
            smol_rag=smol_rag,
            workspace=active_workspace,
            session_manager=session_manager,
            child_loop_registrar=register_session_end_hooks,
            deps=deps,
        )
        label = display_label or "SmolClaw"

    register_session_end_hooks(agent)

    memory_store_tool = deps.memory_store_tool_factory(
        smol_rag=smol_rag,
        memory_docs_dir=memory_dir,
        llm=agent.llm,
    )
    session_export_hook = deps.session_export_hook_factory(
        smol_rag=smol_rag,
        llm=agent.llm,
        memory_dir=memory_dir,
    )

    if deps.tui_factory is None:
        from cli.tui import CoderTui, _git_state
        tui_factory = CoderTui
        git_command_runner = getattr(runtime.env, "agent_command_runner", None)
        tui_extra_kwargs = {
            "git_state_provider": lambda cwd: _git_state(
                cwd,
                command_runner=git_command_runner,
            ) if git_command_runner is not None else _git_state(
                cwd,
            )
        }
    else:
        tui_factory = deps.tui_factory
        tui_extra_kwargs = {}

    tui = tui_factory(
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
        resolve_work_loop_command=lambda arg: _resolve_work_loop_command(workspace_ctx, arg, deps=deps),
        initialize_project=lambda: _format_bootstrap_result(init_project_guidance(workspace_ctx)),
        format_action_event=_format_action_event,
        label=label,
        **tui_extra_kwargs,
    )
    try:
        await tui.run()
    finally:
        if worktree_state is not None and (worktree_state.discard_on_exit or not worktree_state.keep_on_exit):
            worktree_state.context.cleanup()


async def _run_approval_review_prompt(
    approval_store,
    session_key: str,
    prompt_session,
    console,
    *,
    on_approved=None,
) -> None:
    while True:
        pending = approval_store.list(session_key, status="pending")
        if not pending:
            console.print("[dim]No pending approval requests.[/dim]")
            return
        console.print("[bold]Approval review[/bold]")
        for index, request in enumerate(pending, start=1):
            console.print(f"[dim]{index}. {format_approval_review_option(request)}[/dim]")
        selection = (await prompt_session.prompt_async("approval select [number/id/q]> ")).strip()
        if selection.lower() in {"", "q", "quit", "exit"}:
            console.print("[dim]Approval review closed.[/dim]")
            return
        request = None
        if selection.isdigit():
            index = int(selection) - 1
            if 0 <= index < len(pending):
                request = pending[index]
        if request is None:
            request = next((item for item in pending if item.id == selection), None)
        if request is None:
            console.print("[red]No matching approval request.[/red]")
            continue
        console.print(f"[dim]{format_approval_detail(approval_store, session_key, request.id)}[/dim]")
        action = (
            await prompt_session.prompt_async(
                "approval action [a]pprove/[d]eny/[i]nfo/[s]kip/[q]uit> "
            )
        ).strip().lower()
        if action in {"q", "quit", "exit"}:
            console.print("[dim]Approval review closed.[/dim]")
            return
        if action in {"i", "info", "information"}:
            console.print(
                "[dim]Approval left pending. Type the extra context or ask what information is needed.[/dim]"
            )
            return
        if action in {"", "s", "skip"}:
            continue
        try:
            if action in {"a", "approve"}:
                resolved = approval_store.approve(session_key, request.id)
                console.print(f"[dim]Approved {resolved.id}.[/dim]")
                if not approval_store.list(session_key, status="pending") and on_approved is not None:
                    console.print("[dim]Continuing after approval.[/dim]")
                    await on_approved()
                continue
            if action in {"d", "deny"}:
                resolved = approval_store.deny(session_key, request.id)
                console.print(f"[dim]Denied {resolved.id}.[/dim]")
                continue
        except KeyError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            continue
        console.print("[red]Choose approve, deny, skip, or quit.[/red]")


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
    deps: CliDependencies | None = None,
):
    deps = get_cli_dependencies(deps)
    console = deps.console
    worktree_state: _InteractiveWorktreeState | None = None
    worktree_ctx, active_workspace = _prepare_isolated_workspace(
        workspace,
        deps=deps,
        worktree=worktree,
        copy_dirty_worktree=copy_dirty_worktree,
    )
    if worktree_ctx is not None:
        worktree_state = _InteractiveWorktreeState(
            context=worktree_ctx,
            state_root=_state_root_for_workspace(workspace),
            keep_on_exit=keep_worktree,
        )
    runtime = _build_cli_runtime(active_workspace, deps=deps)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    smol_rag = runtime.smol_rag
    session_manager = runtime.session_manager
    goal_store = deps.goal_store_factory(paths.ledgers_dir)
    checkpoint_store = deps.checkpoint_store_factory(paths.checkpoints_dir)
    approval_store = deps.approval_store_factory(paths.approvals_dir)
    memory_dir = ensure_dir(paths.memory_docs_dir)
    register_session_end_hooks = _make_session_end_hook_registrar(paths, memory_dir, auto_export)

    if agent_name:
        builder = deps.multiagent_builder or _build_multiagent
        agent = _call_with_optional_deps(
            builder,
            agent_name,
            agents_config,
            session_key,
            smol_rag,
            active_workspace,
            session_manager,
            auto_export,
            child_loop_registrar=register_session_end_hooks,
            model_override=model,
            deps=deps,
        )
        label = display_label or agent_name.capitalize()
    else:
        builder = deps.default_chat_agent_builder or _build_default_chat_agent
        agent = _call_with_optional_deps(
            builder,
            agents_config_path=agents_config,
            session_key=session_key,
            model=model,
            smol_rag=smol_rag,
            workspace=active_workspace,
            session_manager=session_manager,
            child_loop_registrar=register_session_end_hooks,
            deps=deps,
        )
        label = display_label or "SmolClaw"

    register_session_end_hooks(agent)

    memory_store_tool = deps.memory_store_tool_factory(
        smol_rag=smol_rag,
        memory_docs_dir=memory_dir,
        llm=agent.llm,
    )
    session_export_hook = deps.session_export_hook_factory(
        smol_rag=smol_rag,
        llm=agent.llm,
        memory_dir=memory_dir,
    )

    history_file = paths.prompt_history_path
    prompt_session = deps.prompt_session_factory(history=FileHistory(history_file))

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

    should_exit = False
    slash_dispatcher = SlashCommandDispatcher()

    @slash_dispatcher.register("/", "/help", "/commands")
    async def _dispatch_help(parsed):
        console.print(f"[dim]{SLASH_COMMANDS_HELP}[/dim]")
        return True

    @slash_dispatcher.register("/quit", "/exit")
    async def _dispatch_exit(parsed):
        nonlocal should_exit
        should_exit = True
        return True

    @slash_dispatcher.register("/logs")
    async def _dispatch_logs(parsed):
        console.print(f"[dim]{_format_diagnostics_paths(paths.log_dir)}[/dim]")
        return True

    @slash_dispatcher.register("/clear")
    async def _dispatch_clear(parsed):
        agent.session.clear()
        session_manager.save(agent.session)
        console.print("[dim]Session cleared.[/dim]")
        return True

    @slash_dispatcher.register("/init")
    async def _dispatch_init(parsed):
        console.print(f"[dim]{_format_bootstrap_result(init_project_guidance(workspace_ctx))}[/dim]")
        return True

    @slash_dispatcher.register("/undo")
    async def _dispatch_undo(parsed):
        result = checkpoint_store.undo_last(session_key=agent.session.key)
        style = "dim" if result.ok else "red"
        console.print(f"[{style}]{_format_undo_result(result)}[/{style}]")
        return True

    try:
        while True:
            try:
                user_input = await prompt_session.prompt_async("you> ")
            except (EOFError, KeyboardInterrupt):
                break

            user_input = user_input.strip()
            if not user_input:
                continue
            parsed = parse_slash_command(user_input)
            command = parsed.name
            command_arg = parsed.arg
            if await slash_dispatcher.dispatch(parsed):
                if should_exit:
                    break
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
                if command_arg.split(maxsplit=1)[0:1] == ["review"]:
                    await _run_approval_review_prompt(
                        approval_store,
                        agent.session.key,
                        prompt_session,
                        console,
                        on_approved=lambda: _run_agent_turn(APPROVAL_CONTINUATION_PROMPT),
                    )
                    continue
                approval_output = _resolve_approval_command(approval_store, agent.session.key, command_arg)
                console.print(f"[dim]{approval_output}[/dim]")
                if (
                    command_arg.split(maxsplit=1)[0:1] == ["approve"]
                    and approval_output.startswith("Approved ")
                    and not approval_store.list(agent.session.key, status="pending")
                ):
                    console.print("[dim]Continuing after approval.[/dim]")
                    await _run_agent_turn(APPROVAL_CONTINUATION_PROMPT)
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
            if command == "/work-loop":
                console.print(
                    _resolve_work_loop_command(workspace_ctx, command_arg, deps=deps),
                    markup=False,
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
                try:
                    apply_runtime_model_selection(agent.llm, selection, getattr(agent, "model_settings", None))
                except ValueError as exc:
                    console.print(f"[dim]Error: {exc}[/dim]")
                    continue
                console.print(f"[dim]Switched {model_status(agent.llm)}[/dim]")
                continue
            if command == "/goal":
                subcommand, sub_arg = _parse_goal_command(command_arg)
                if subcommand == "help":
                    console.print(f"[dim]{GOAL_COMMAND_HELP}[/dim]")
                    continue
                if subcommand in ("", "status"):
                    console.print(f"[dim]{_format_goal_status(goal_store.load(agent.session.key))}[/dim]")
                    continue
                if subcommand == "infer":
                    try:
                        inferred = await infer_goal_from_thread(agent.llm, agent.session.messages)
                        goal = goal_store.start(
                            agent.session.key,
                            inferred.objective,
                            acceptance_criteria=inferred.acceptance_criteria,
                        )
                    except ValueError as exc:
                        console.print(f"[dim]Error: {exc}[/dim]")
                        continue
                    console.print(f"[dim]{_format_inferred_goal_started(goal, inferred)}[/dim]")
                    continue
                if subcommand == "start":
                    if not sub_arg:
                        console.print(f"[dim]{GOAL_COMMAND_HELP}[/dim]")
                        continue
                    goal = goal_store.start(agent.session.key, sub_arg)
                    console.print(f"[dim]{_format_goal_started(goal)}[/dim]")
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
                console.print(f"[dim]{GOAL_COMMAND_HELP}[/dim]")
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
    deps = get_cli_dependencies()
    runner = deps.research_loop_runner or _research_loop
    deps.async_runner(
        _call_with_optional_deps(
            runner,
            goal=goal,
            workspace=workspace,
            agent_name=agent,
            agents_config=agents_config,
            session_key=session_key,
            interval=interval,
            max_runs=max_runs,
            auto_export=auto_export,
            show_actions=show_actions,
            deps=deps,
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
    deps: CliDependencies | None = None,
):
    deps = get_cli_dependencies(deps)
    console = deps.console
    runtime = _build_cli_runtime(workspace, deps=deps)
    workspace_ctx = runtime.workspace
    paths = workspace_ctx.paths
    smol_rag = runtime.smol_rag
    session_manager = runtime.session_manager
    memory_dir = ensure_dir(paths.memory_docs_dir)
    register_session_end_hooks = _make_session_end_hook_registrar(paths, memory_dir, auto_export)

    builder = deps.multiagent_builder or _build_multiagent
    agent = _call_with_optional_deps(
        builder,
        agent_name,
        agents_config,
        session_key,
        smol_rag,
        workspace,
        session_manager,
        auto_export,
        child_loop_registrar=register_session_end_hooks,
        deps=deps,
    )
    register_session_end_hooks(agent)

    stop_factory = deps.research_stop_controller_factory or _create_research_loop_stop_controller
    stop_controller, esc_watcher = stop_factory()
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
    from app.memory_documents import MemoryDocumentService
    runtime = _build_cli_runtime(workspace)
    workspace_ctx = runtime.workspace
    smol_rag = runtime.smol_rag
    document_service = MemoryDocumentService(smol_rag)
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
            source_id = document_service.external_source_id(file_path)
            if await smol_rag.source_doc_map.has_left(source_id) and await smol_rag.source_doc_map.equal_right(source_id, doc_id):
                console.print(f"[dim]Skipped (unchanged):[/dim] {file_path}")
                skipped += 1
                continue

            await document_service.ingest_external_text(
                content,
                source_id=source_id,
                save=False,
            )
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
    host: str = typer.Option("127.0.0.1", "--host", help="WebSocket bind host"),
    token: Optional[str] = typer.Option(None, "--token", help="Gateway auth token (or SMOLCLAW_GATEWAY_TOKEN)"),
    allow_remote: bool = typer.Option(False, "--allow-remote", help="Allow non-loopback gateway binds"),
    token_issuer: str = typer.Option(
        "http://client:3000/mcp-tokens", "--token-issuer", help="MCP token issuer URL",
    ),
    gateway: str = typer.Option(
        "http://mcp-gateway:3200/mcp", "--gateway", help="MCP gateway URL",
    ),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace root (isolated store, memory, research)"),
):
    """Start the WebSocket gateway server."""
    asyncio.run(_serve(port, host, token, allow_remote, token_issuer, gateway, workspace))


async def _serve(
    port: int,
    host: str,
    token: str | None,
    allow_remote: bool,
    token_issuer: str,
    gateway_url: str,
    workspace: str,
):
    from app.gateway import Gateway
    gw = Gateway(
        port=port,
        host=host,
        token_issuer_url=token_issuer,
        gateway_url=gateway_url,
        workspace=workspace,
        auth_token=token,
        allow_remote=allow_remote,
    )
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
    deps = get_cli_dependencies()
    runner = deps.tui_chat_loop_runner or _tui_chat_loop
    deps.async_runner(
        _call_with_optional_deps(
            runner,
            session_key=session_key,
            workspace=workspace,
            model=model,
            agent_name="coder",
            agents_config=agents_config,
            auto_export=auto_export,
            show_actions=show_actions,
            display_label="SmolClaw",
            deps=deps,
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
