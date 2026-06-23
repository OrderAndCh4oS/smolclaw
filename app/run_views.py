"""Shared renderers for run, trace, and ledger state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.goal_ledger import GoalLedger
from app.run_trace import RunTraceEvent, RunTraceStore, RunTraceSummary


@dataclass(frozen=True)
class RunStatusView:
    session_key: str
    trace_run_id: str | None = None
    trace_status: str | None = None
    stop_reason: str | None = None
    trace_path: str | None = None
    summary_path: str | None = None
    model: str | None = None
    tool_calls: int = 0
    denied_tool_calls: int = 0
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    verification_count: int = 0
    ledger_path: str | None = None
    goal_objective: str | None = None
    goal_status: str | None = None
    goal_turns: int = 0
    changed_files: list[str] = field(default_factory=list)
    verification_summaries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_run_status_view(
    *,
    session_key: str,
    trace_store: RunTraceStore | None = None,
    goal_store=None,
) -> RunStatusView:
    summary = trace_store.latest_summary(session_key) if trace_store is not None else None
    ledger = goal_store.load(session_key) if goal_store is not None else None
    summary_path = (
        trace_store.summary_path(session_key, summary.run_id)
        if trace_store is not None and summary is not None
        else None
    )
    ledger_path = (
        getattr(goal_store, "_file_path")(session_key)
        if goal_store is not None and hasattr(goal_store, "_file_path") and ledger is not None
        else None
    )
    return RunStatusView(
        session_key=session_key,
        trace_run_id=summary.run_id if summary else None,
        trace_status=summary.status if summary else None,
        stop_reason=summary.stop_reason if summary else None,
        trace_path=summary.trace_path if summary else None,
        summary_path=summary_path,
        model=summary.model if summary else None,
        tool_calls=summary.tool_calls if summary else 0,
        denied_tool_calls=summary.denied_tool_calls if summary else 0,
        files_changed=list(summary.files_changed) if summary else [],
        commands_run=list(summary.commands_run) if summary else [],
        checkpoints=list(summary.checkpoints) if summary else [],
        verification_count=len(summary.verification) if summary else 0,
        ledger_path=ledger_path,
        goal_objective=ledger.objective if ledger else None,
        goal_status=ledger.status if ledger else None,
        goal_turns=ledger.turn_count if ledger else 0,
        changed_files=[item.path for item in ledger.changed_files if item.path] if ledger else [],
        verification_summaries=[
            item.summary or item.command
            for item in ledger.verification
            if item.summary or item.command
        ] if ledger else [],
    )


def build_run_status_view_from_artifacts(
    *,
    session_key: str,
    trace_summary: RunTraceSummary | None = None,
    ledger: GoalLedger | None = None,
    summary_path: str | None = None,
    ledger_path: str | None = None,
) -> RunStatusView:
    verification = getattr(trace_summary, "verification", []) if trace_summary else []
    return RunStatusView(
        session_key=session_key,
        trace_run_id=getattr(trace_summary, "run_id", None) if trace_summary else None,
        trace_status=getattr(trace_summary, "status", None) if trace_summary else None,
        stop_reason=getattr(trace_summary, "stop_reason", None) if trace_summary else None,
        trace_path=getattr(trace_summary, "trace_path", None) if trace_summary else None,
        summary_path=summary_path,
        model=getattr(trace_summary, "model", None) if trace_summary else None,
        tool_calls=getattr(trace_summary, "tool_calls", 0) if trace_summary else 0,
        denied_tool_calls=getattr(trace_summary, "denied_tool_calls", 0) if trace_summary else 0,
        files_changed=list(getattr(trace_summary, "files_changed", [])) if trace_summary else [],
        commands_run=list(getattr(trace_summary, "commands_run", [])) if trace_summary else [],
        checkpoints=list(getattr(trace_summary, "checkpoints", [])) if trace_summary else [],
        verification_count=len(verification),
        ledger_path=ledger_path,
        goal_objective=ledger.objective if ledger else None,
        goal_status=ledger.status if ledger else None,
        goal_turns=ledger.turn_count if ledger else 0,
        changed_files=[item.path for item in ledger.changed_files if item.path] if ledger else [],
        verification_summaries=[
            item.summary or item.command
            for item in ledger.verification
            if item.summary or item.command
        ] if ledger else [],
    )

def format_goal_status(goal: GoalLedger | None) -> str:
    if goal is None:
        return "No goal is set for this session."
    lines = [
        f"Goal: {goal.objective}",
        f"Status: {goal.status}",
        f"Turns: {goal.turn_count}",
    ]
    if goal.note:
        lines.append(f"Note: {goal.note}")
    if getattr(goal, "acceptance_criteria", None):
        lines.append("Acceptance criteria:")
        for item in goal.acceptance_criteria:
            lines.append(f"- [{item.status}] {item.description}")
    if getattr(goal, "changed_files", None):
        changed = ", ".join(item.path for item in goal.changed_files[-5:] if item.path)
        if changed:
            lines.append(f"Changed files: {changed}")
    if getattr(goal, "verification", None):
        lines.append("Verification:")
        for item in goal.verification[-3:]:
            summary = item.summary or item.command or item.status
            lines.append(f"- {summary}")
    return "\n".join(lines)


def format_trace_status(
    trace_store: RunTraceStore,
    session_key: str,
    *,
    goal_store=None,
) -> str:
    view = build_run_status_view(
        session_key=session_key,
        trace_store=trace_store,
        goal_store=goal_store,
    )
    if view.trace_run_id is None:
        return "No run trace is available for this session."
    lines = [
        f"Trace: {view.trace_run_id}",
        f"Status: {view.trace_status}",
        f"Stop reason: {view.stop_reason or 'unknown'}",
        f"Model: {view.model}",
        f"Tool calls: {view.tool_calls}",
        f"Denied tool calls: {view.denied_tool_calls}",
    ]
    if view.files_changed:
        lines.append(f"Files changed: {', '.join(view.files_changed)}")
    if view.commands_run:
        lines.append(f"Commands: {'; '.join(view.commands_run)}")
    if view.checkpoints:
        lines.append(f"Checkpoints: {', '.join(view.checkpoints)}")
    if view.verification_count:
        lines.append(f"Verification records: {view.verification_count}")
    if view.goal_objective:
        lines.extend([
            f"Goal: {view.goal_objective}",
            f"Goal status: {view.goal_status}",
        ])
    if view.ledger_path:
        lines.append(f"Ledger path: {view.ledger_path}")
    lines.extend([
        f"Trace path: {view.trace_path}",
        f"Summary path: {view.summary_path}",
    ])
    return "\n".join(lines)


def format_trace_list(
    trace_store: RunTraceStore,
    session_key: str,
    *,
    limit: int = 10,
) -> str:
    summaries = trace_store.list_summaries(session_key)
    if not summaries:
        return "No run trace is available for this session."
    recent = summaries[-limit:]
    lines = [f"Run traces ({len(recent)}/{len(summaries)}):"]
    for summary in reversed(recent):
        stopped = summary.stop_reason or "unknown"
        lines.append(
            f"- {summary.run_id}: {summary.status}, "
            f"tools={summary.tool_calls}, denied={summary.denied_tool_calls}, stop={stopped}"
        )
    return "\n".join(lines)


def compact_trace_value(value: object, *, max_length: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, default=str)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def format_trace_event_line(event: RunTraceEvent) -> str:
    parts = [event.event]
    if event.turn_index is not None:
        parts.append(f"turn={event.turn_index}")
    if event.iteration is not None:
        parts.append(f"iter={event.iteration}")
    data = event.data or {}
    details: list[str] = []
    for key in (
        "status",
        "stop_reason",
        "name",
        "tool_name",
        "command",
        "summary",
        "reason",
        "checkpoint_id",
        "tool_trace_event_id",
        "model",
    ):
        if key in data and data[key] not in (None, "", []):
            details.append(f"{key}={compact_trace_value(data[key])}")
    if details:
        parts.append(" ".join(details))
    return "- " + " ".join(parts)


def format_trace_events(
    trace_store: RunTraceStore,
    session_key: str,
    *,
    run_id: str | None = None,
    limit: int = 20,
) -> str:
    summary = trace_store.load_summary(session_key, run_id) if run_id else trace_store.latest_summary(session_key)
    if summary is None:
        return "No run trace is available for this session."
    events = trace_store.load_events(session_key, summary.run_id)
    if not events:
        return f"Trace events: {summary.run_id}\nNo events recorded."
    bounded_limit = max(1, min(limit, 200))
    shown = events[-bounded_limit:]
    lines = [
        f"Trace events: {summary.run_id}",
        f"Showing {len(shown)}/{len(events)} event(s)",
    ]
    lines.extend(format_trace_event_line(event) for event in shown)
    return "\n".join(lines)


def format_trace_replay(
    trace_store: RunTraceStore,
    session_key: str,
    *,
    run_id: str | None = None,
) -> str:
    summary = trace_store.load_summary(session_key, run_id) if run_id else trace_store.latest_summary(session_key)
    if summary is None:
        return "No run trace is available for this session."
    events = trace_store.load_events(session_key, summary.run_id)
    if not events:
        return f"Trace replay: {summary.run_id}\nNo events recorded."
    lines = [
        f"Trace replay: {summary.run_id}",
        f"Status: {summary.status}",
        f"Stop reason: {summary.stop_reason or 'unknown'}",
    ]
    for event in events:
        if event.event in {"run.started", "turn.started", "turn.ended", "run.ended"}:
            lines.append(format_trace_event_line(event))
            continue
        if event.event.startswith("llm.") or event.event.startswith("tool."):
            lines.append(format_trace_event_line(event))
            continue
        if event.event in {
            "verification.recorded",
            "checkpoint.created",
            "ledger.updated",
            "permission.decided",
            "approval.requested",
            "approval.resolved",
            "safety.blocked",
            "error",
        }:
            lines.append(format_trace_event_line(event))
    return "\n".join(lines)


def format_run_status_view(view: RunStatusView) -> str:
    lines = [f"Session: {view.session_key}"]
    if view.trace_run_id:
        lines.extend([
            f"Trace: {view.trace_run_id}",
            f"Status: {view.trace_status}",
            f"Stop reason: {view.stop_reason or 'unknown'}",
        ])
    else:
        lines.append("Trace: none")
    if view.goal_objective:
        lines.extend([
            f"Goal: {view.goal_objective}",
            f"Goal status: {view.goal_status}",
            f"Goal turns: {view.goal_turns}",
        ])
    else:
        lines.append("Goal: none")
    changed = view.changed_files or view.files_changed
    if changed:
        lines.append(f"Changed files: {', '.join(changed)}")
    if view.verification_summaries:
        lines.append("Verification:")
        lines.extend(f"- {item}" for item in view.verification_summaries[-3:])
    elif view.verification_count:
        lines.append(f"Verification records: {view.verification_count}")
    if view.ledger_path:
        lines.append(f"Ledger path: {view.ledger_path}")
    if view.trace_path:
        lines.append(f"Trace path: {view.trace_path}")
    return "\n".join(lines)
