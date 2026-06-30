import inspect
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import typer

from app.approvals import (
    ApprovalRequestStore,
    PermissionController,
    format_approval_detail,
    format_approval_review,
    format_approval_status,
)
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
from app.utilities import extract_json_from_text


APPROVAL_CONTINUATION_PROMPT = (
    "The requested approval was granted. Continue from the pending tool call, "
    "retry the approved exact call if still needed, and proceed with the user's task."
)


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
    "  /work-loop list          List task-source items and GitHub PRs worked by the agent",
    "  /work-loop status <id>   Show one work-loop item or PR",
    "  /work-loop create-task \"Title\" --project KEY    Create a task in the configured task source",
    "  /work-loop start         Run review follow-up, then start configured task-source work",
    "  /work-loop tasks         Start configured task-source work",
    "  /work-loop reviews       Check GitHub review feedback for open agent PRs",
    "  /work-loop run           Run reviews first, then task-source work",
    "  /work-loop stop          Stop work-loop subprocesses before the next step",
    "  /work-loop pause|resume|state     Control or inspect work-loop kill state",
    "  /approval status         Show pending approval requests",
    "  /approval review         Open selectable approval dialog",
    "  /approval detail <id>    Show one approval request in detail",
    "  /approval approve <id>   Approve one exact pending tool call",
    "  /approval deny <id>      Deny one pending tool call",
    "  /details                 Toggle recent tool/thinking activity",
    "  /model [model] [effort]  Show/switch gpt-5.4 or gpt-5.5 model",
    "  /undo                    Undo the last SmolClaw file checkpoint",
    "  /goal                    Show the current goal and loop state",
    "  /goal <objective>        Start a goal",
    "  /goal infer              Infer a goal from this chat",
    "  /goal run [turns]        Continue the goal loop (default: 3)",
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


GOAL_COMMAND_HELP = "\n".join([
    "Goal commands:",
    "  /goal                    Show current goal status",
    "  /goal <objective>        Start a new goal",
    "  /goal infer              Infer a goal from the preceding chat",
    "  /goal start <objective>  Start a new goal explicitly",
    "  /goal run [turns]        Continue the goal loop, default 3 turns",
    "  /goal complete [note]    Mark complete",
    "  /goal block [note]       Mark blocked",
    "  /goal clear              Clear the goal",
])

_GOAL_COMMANDS = {
    "help": "help",
    "status": "status",
    "infer": "infer",
    "start": "start",
    "run": "run",
    "complete": "complete",
    "block": "block",
    "clear": "clear",
}


def _parse_goal_command(command_arg: str) -> tuple[str, str]:
    text = command_arg.strip()
    if not text:
        return "status", ""
    parts = text.split(maxsplit=1)
    first = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    subcommand = _GOAL_COMMANDS.get(first)
    if subcommand is None:
        return "start", text
    return subcommand, rest


def _format_goal_started(goal) -> str:
    return (
        f"Goal set: {goal.objective}\n"
        "Next: use /goal run to continue it."
    )


def _format_inferred_goal_started(goal, inferred: "InferredGoal") -> str:
    lines = [_format_goal_started(goal)]
    if inferred.acceptance_criteria:
        lines.append("Acceptance criteria:")
        lines.extend(f"- {item}" for item in inferred.acceptance_criteria)
    if inferred.rationale:
        lines.append(f"Inferred from: {inferred.rationale}")
    return "\n".join(lines)


@dataclass(frozen=True)
class InferredGoal:
    objective: str
    acceptance_criteria: list[str] = field(default_factory=list)
    rationale: str = ""


async def infer_goal_from_thread(llm, messages: list[dict], *, max_messages: int = 30) -> InferredGoal:
    transcript = _format_goal_inference_thread(messages, max_messages=max_messages)
    if not transcript.strip():
        raise ValueError("No prior chat messages are available to infer a goal.")
    prompt = _build_goal_inference_prompt(transcript)
    raw = await llm.get_completion(prompt)
    payload = extract_json_from_text(str(raw or "")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Could not infer a goal from the chat thread.")
    objective = str(payload.get("objective") or "").strip()
    if not objective:
        raise ValueError("Could not infer a clear goal from the chat thread.")
    criteria = payload.get("acceptance_criteria") or []
    if not isinstance(criteria, list):
        criteria = []
    return InferredGoal(
        objective=objective,
        acceptance_criteria=[str(item).strip() for item in criteria if str(item).strip()],
        rationale=str(payload.get("rationale") or "").strip(),
    )


def _format_goal_inference_thread(messages: list[dict], *, max_messages: int = 30, max_chars: int = 12000) -> str:
    lines = []
    for message in messages[-max_messages:]:
        role = str(message.get("role") or "unknown")
        if role == "tool":
            continue
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    transcript = "\n\n".join(lines)
    if len(transcript) <= max_chars:
        return transcript
    return transcript[-max_chars:]


def _build_goal_inference_prompt(transcript: str) -> str:
    return (
        "Infer the current working goal from the preceding chat transcript.\n"
        "Use only goals, decisions, constraints, and acceptance criteria that were explicitly stated or agreed in the thread. "
        "Do not invent new scope. Prefer the latest user direction when the thread changes direction.\n\n"
        "Return only JSON with this shape:\n"
        "{\n"
        '  "objective": "one concise goal statement",\n'
        '  "acceptance_criteria": ["observable completion criterion", "..."],\n'
        '  "rationale": "short explanation of which agreed decisions shaped the goal"\n'
        "}\n\n"
        f"Transcript:\n{transcript}"
    )


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
    approval_controller: PermissionController | None = None,
) -> str:
    parts = command_arg.split(maxsplit=1)
    subcommand = parts[0] if parts else "status"
    approval_id = parts[1].strip() if len(parts) > 1 else ""
    if subcommand in ("", "status"):
        if approval_controller is not None:
            pending = approval_controller.list_pending(session_key)
            if not pending:
                return "No pending approval requests."
            lines = ["Pending approvals:"]
            lines.extend(f"- {item.id}: {item.tool_name} - {item.reason}" for item in pending)
            return "\n".join(lines)
        return format_approval_status(approval_store, session_key)
    if subcommand == "review":
        if approval_controller is not None:
            pending = approval_controller.list_pending(session_key)
            if not pending:
                return "No pending approval requests."
            lines = ["Approval review:"]
            lines.extend(f"{index}. {item.id}: {item.tool_name} - {item.reason}" for index, item in enumerate(pending, 1))
            return "\n".join(lines)
        return format_approval_review(approval_store, session_key)
    if subcommand == "detail":
        if not approval_id:
            return "Usage: /approval detail <id>"
        return format_approval_detail(approval_store, session_key, approval_id)
    if subcommand not in {"approve", "deny"}:
        return "Usage: /approval status|review|detail <id>|approve <id>|deny <id>"
    if not approval_id:
        return f"Usage: /approval {subcommand} <id>"
    try:
        if approval_controller is not None:
            request = approval_controller.reply(approval_id, "once" if subcommand == "approve" else "reject")
            return f"Approved {request.id}." if subcommand == "approve" else f"Denied {request.id}."
        if subcommand == "approve":
            request = approval_store.approve(session_key, approval_id)
            return f"Approved {request.id}."
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
    metadata = getattr(ctx, "isolation_metadata", None)
    lines = [
        "Worktree: active",
        f"Mode: {_worktree_mode_name(ctx)}",
        f"Run id: {ctx.run_id}",
        f"Source root: {ctx.path}",
        f"State root: {worktree_state.state_root}",
        f"Base repo: {ctx.base_repo}",
        f"Keep on exit: {'yes' if worktree_state.keep_on_exit else 'no'}",
        f"Discard on exit: {'yes' if worktree_state.discard_on_exit else 'no'}",
        f"Apply count: {worktree_state.applied_count}",
    ]
    if metadata is not None and getattr(metadata, "dirty_copy", False):
        lines.extend([
            f"Copied files: {getattr(metadata, 'copied_file_count', 0)}",
            f"Copied bytes: {getattr(metadata, 'copied_byte_count', 0)}",
            f"Excluded paths: {getattr(metadata, 'excluded_path_count', 0)}",
            f"Warnings: {getattr(metadata, 'warning_count', 0)}",
        ])
        for warning in list(getattr(metadata, "warnings", ()) or ())[:5]:
            lines.append(f"- {warning}")
    return "\n".join(lines)


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
        options = parts[1].split() if len(parts) > 1 else []
        confirm = "--confirm" in options or "confirm" in options
        result = ctx.apply_back(confirm=confirm)
        if result.startswith("Applied "):
            worktree_state.applied_count += 1
        return result
    if subcommand == "discard":
        worktree_state.discard_on_exit = True
        return "Discard scheduled. The isolated worktree will be removed when the session exits."
    return "Usage: /worktree status|diff|apply [--confirm]|discard"


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
