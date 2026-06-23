"""Durable run traces for agent trajectories."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app import diagnostics
from app.storage_paths import atomic_write_json, contained_storage_path


TRACE_SCHEMA_VERSION = 1
TraceStatus = Literal["complete", "blocked", "error", "stopped", "unknown"]


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def new_event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:12]}"


def _json_safe(value: Any) -> Any:
    redacted = diagnostics.redact(value)
    try:
        return json.loads(json.dumps(redacted, default=str))
    except (TypeError, ValueError):
        return str(redacted)


@dataclass(frozen=True)
class RunTraceEvent:
    event: str
    run_id: str
    session_key: str
    data: dict[str, Any] = field(default_factory=dict)
    turn_index: int | None = None
    iteration: int | None = None
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=new_event_id)
    schema_version: int = TRACE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "session_key": self.session_key,
            "turn_index": self.turn_index,
            "iteration": self.iteration,
            "timestamp": self.timestamp,
            "event": self.event,
            "data": _json_safe(self.data),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunTraceEvent":
        return cls(
            schema_version=int(data.get("schema_version") or TRACE_SCHEMA_VERSION),
            event_id=str(data.get("event_id") or new_event_id()),
            run_id=str(data.get("run_id") or ""),
            session_key=str(data.get("session_key") or ""),
            turn_index=data.get("turn_index"),
            iteration=data.get("iteration"),
            timestamp=float(data.get("timestamp") or time.time()),
            event=str(data.get("event") or ""),
            data=dict(data.get("data") or {}),
        )


@dataclass
class RunTraceSummary:
    run_id: str
    session_key: str
    goal_id: str | None = None
    status: TraceStatus = "unknown"
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    model: str = "unknown"
    tool_calls: int = 0
    denied_tool_calls: int = 0
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    verification: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    trace_path: str | None = None
    malformed_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "session_key": self.session_key,
            "goal_id": self.goal_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "model": self.model,
            "tool_calls": self.tool_calls,
            "denied_tool_calls": self.denied_tool_calls,
            "files_changed": list(self.files_changed),
            "commands_run": list(self.commands_run),
            "checkpoints": list(self.checkpoints),
            "verification": _json_safe(list(self.verification)),
            "stop_reason": self.stop_reason,
            "trace_path": self.trace_path,
            "malformed_events": self.malformed_events,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunTraceSummary":
        return cls(
            run_id=str(data.get("run_id") or ""),
            session_key=str(data.get("session_key") or ""),
            goal_id=data.get("goal_id"),
            status=str(data.get("status") or "unknown"),  # type: ignore[arg-type]
            started_at=float(data.get("started_at") or time.time()),
            ended_at=data.get("ended_at"),
            model=str(data.get("model") or "unknown"),
            tool_calls=int(data.get("tool_calls") or 0),
            denied_tool_calls=int(data.get("denied_tool_calls") or 0),
            files_changed=list(data.get("files_changed") or []),
            commands_run=list(data.get("commands_run") or []),
            checkpoints=list(data.get("checkpoints") or []),
            verification=list(data.get("verification") or []),
            stop_reason=data.get("stop_reason"),
            trace_path=data.get("trace_path"),
            malformed_events=int(data.get("malformed_events") or 0),
        )


class RunTraceRecorder:
    """Append-only writer for a single run trace."""

    def __init__(self, store: "RunTraceStore", summary: RunTraceSummary):
        self.store = store
        self.summary = summary
        self.run_id = summary.run_id
        self.session_key = summary.session_key

    def append(
        self,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        turn_index: int | None = None,
        iteration: int | None = None,
    ) -> RunTraceEvent:
        trace_event = RunTraceEvent(
            event=event,
            run_id=self.run_id,
            session_key=self.session_key,
            data=data or {},
            turn_index=turn_index,
            iteration=iteration,
        )
        self.store.append(trace_event)
        self._update_summary(trace_event)
        return trace_event

    def finish(self, status: TraceStatus, *, stop_reason: str | None = None) -> RunTraceSummary:
        self.summary.status = status
        self.summary.stop_reason = stop_reason or self.summary.stop_reason
        self.summary.ended_at = time.time()
        self.append("run.ended", {
            "status": self.summary.status,
            "stop_reason": self.summary.stop_reason,
        })
        self.store.save_summary(self.summary)
        return self.summary

    def _update_summary(self, event: RunTraceEvent):
        data = event.data
        if event.event == "llm.ended":
            model = data.get("model")
            if model:
                self.summary.model = str(model)
        elif event.event == "tool.started":
            self.summary.tool_calls += 1
            command = data.get("command")
            if command:
                self._append_unique(self.summary.commands_run, str(command))
        elif event.event in {"tool.denied", "safety.blocked"}:
            self.summary.denied_tool_calls += 1
        elif event.event == "checkpoint.created":
            checkpoint_id = data.get("checkpoint_id")
            if checkpoint_id:
                self._append_unique(self.summary.checkpoints, str(checkpoint_id))
            for path in data.get("changed_paths") or []:
                self._append_unique(self.summary.files_changed, str(path))
        elif event.event == "verification.recorded":
            self.summary.verification.append(_json_safe(data))

    def _append_unique(self, values: list[str], value: str):
        if value not in values:
            values.append(value)


class RunTraceStore:
    """Stores run traces under the workspace state root's stores/traces tree."""

    def __init__(self, traces_dir: str):
        self.traces_dir = traces_dir
        os.makedirs(traces_dir, exist_ok=True)

    def session_dir(self, session_key: str) -> str:
        path = contained_storage_path(self.traces_dir, session_key, "")
        os.makedirs(path, exist_ok=True)
        return path

    def trace_path(self, session_key: str, run_id: str) -> str:
        return contained_storage_path(self.session_dir(session_key), run_id, ".jsonl")

    def summary_path(self, session_key: str, run_id: str) -> str:
        return contained_storage_path(self.session_dir(session_key), run_id, ".summary.json")

    def start_run(
        self,
        session_key: str,
        *,
        goal_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunTraceRecorder:
        run_id = new_run_id()
        summary = RunTraceSummary(
            run_id=run_id,
            session_key=session_key,
            goal_id=goal_id,
            trace_path=self.trace_path(session_key, run_id),
        )
        recorder = RunTraceRecorder(self, summary)
        recorder.append("run.started", metadata or {})
        self.save_summary(summary)
        return recorder

    def append(self, event: RunTraceEvent):
        path = self.trace_path(event.session_key, event.run_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

    def save_summary(self, summary: RunTraceSummary):
        atomic_write_json(
            self.summary_path(summary.session_key, summary.run_id),
            summary.to_dict(),
        )

    def load_events(
        self,
        session_key: str,
        run_id: str,
        *,
        tolerate_malformed: bool = True,
    ) -> list[RunTraceEvent]:
        path = self.trace_path(session_key, run_id)
        events: list[RunTraceEvent] = []
        if not os.path.exists(path):
            return events
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
        for index, line in enumerate(lines):
            try:
                events.append(RunTraceEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError):
                is_trailing = index == len(lines) - 1
                if not tolerate_malformed or not is_trailing:
                    raise
        return events

    def load_summary(self, session_key: str, run_id: str) -> RunTraceSummary | None:
        path = self.summary_path(session_key, run_id)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as handle:
            return RunTraceSummary.from_dict(json.load(handle))

    def list_summaries(self, session_key: str) -> list[RunTraceSummary]:
        session_dir = self.session_dir(session_key)
        summaries: list[RunTraceSummary] = []
        for name in os.listdir(session_dir):
            if not name.endswith(".summary.json"):
                continue
            summary = self.load_summary(session_key, name.removesuffix(".summary.json"))
            if summary is not None:
                summaries.append(summary)
        return sorted(summaries, key=lambda item: item.started_at)

    def latest_summary(self, session_key: str) -> RunTraceSummary | None:
        summaries = self.list_summaries(session_key)
        return summaries[-1] if summaries else None
