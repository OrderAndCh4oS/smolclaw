import inspect
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

import typer

from app.approvals import ApprovalRequestStore, format_approval_detail, format_approval_status
from app.goal import GoalState
from app.run_trace import RunTraceStore
from app.run_views import (
    compact_trace_value,
    format_goal_status,
    format_trace_event_line,
    format_trace_events,
    format_trace_list,
    format_trace_replay,
    format_trace_status,
)
from app.tools.memory_tools import ContradictionReviewTool


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
    "  /model [model] [effort]  Show/switch gpt-5.4 or gpt-5.5 model",
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


@dataclass(frozen=True)
class ParsedSlashCommand:
    raw: str
    name: str
    arg: str = ""
    is_slash: bool = False


SlashCommandHandler = Callable[[ParsedSlashCommand], bool | Awaitable[bool]]


class SlashCommandDispatcher:
    def __init__(self):
        self._handlers: dict[str, SlashCommandHandler] = {}

    def register(self, *names: str):
        def _decorator(handler: SlashCommandHandler):
            for name in names:
                self._handlers[name] = handler
            return handler

        return _decorator

    async def dispatch(self, command: str | ParsedSlashCommand) -> bool:
        parsed = command if isinstance(command, ParsedSlashCommand) else parse_slash_command(command)
        if not parsed.is_slash:
            return False
        handler = self._handlers.get(parsed.name)
        if handler is None:
            return False
        result = handler(parsed)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)


def parse_slash_command(text: str) -> ParsedSlashCommand:
    raw = text.strip()
    if not raw:
        return ParsedSlashCommand(raw="", name="", is_slash=False)
    parts = raw.split(maxsplit=1)
    name = parts[0]
    arg = parts[1].strip() if len(parts) > 1 else ""
    return ParsedSlashCommand(raw=raw, name=name, arg=arg, is_slash=name.startswith("/"))


def _format_goal_status(goal: GoalState | None) -> str:
    return format_goal_status(goal)


def _format_diagnostics_paths(log_dir: str) -> str:
    return "\n".join([
        f"Diagnostics logs: {log_dir}",
        f"Events: {os.path.join(log_dir, 'events.jsonl')}",
        f"Text log: {os.path.join(log_dir, 'smolclaw.log')}",
    ])


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
