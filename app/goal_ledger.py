"""Structured goal ledger state for inspectable agent work."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.goal import VALID_GOAL_STATUSES
from app.storage_paths import atomic_write_json, contained_storage_path, load_json_with_backup


GOAL_LEDGER_SCHEMA_VERSION = 1
CriterionStatus = Literal["pending", "satisfied", "not_applicable"]
GoalStatus = Literal["active", "complete", "blocked"]
EvidenceKind = Literal["read", "search", "status", "diff", "command", "test", "checkpoint"]
LoopStatus = Literal["idle", "running", "waiting", "paused", "complete", "blocked"]
VALID_LOOP_STATUSES = {"idle", "running", "waiting", "paused", "complete", "blocked"}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _legacy_loop_status(data: dict) -> str:
    status = str(data.get("status") or "active")
    if status == "complete":
        return "complete"
    if status == "blocked":
        return "blocked"
    if data.get("stop_reason") in {"max_iterations", "stop_requested", "error"}:
        return "paused"
    if data.get("stop_reason"):
        return "waiting"
    return "idle"


@dataclass
class AcceptanceCriterion:
    description: str
    id: str = field(default_factory=lambda: _new_id("crit"))
    status: CriterionStatus = "pending"
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "evidence": list(self.evidence),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AcceptanceCriterion":
        return cls(
            id=str(data.get("id") or _new_id("crit")),
            description=str(data.get("description") or ""),
            status=str(data.get("status") or "pending"),  # type: ignore[arg-type]
            evidence=list(data.get("evidence") or []),
        )


@dataclass
class PlanStep:
    description: str
    id: str = field(default_factory=lambda: _new_id("step"))
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanStep":
        return cls(
            id=str(data.get("id") or _new_id("step")),
            description=str(data.get("description") or ""),
            status=str(data.get("status") or "pending"),
        )


@dataclass
class EvidenceRef:
    kind: EvidenceKind
    summary: str
    id: str = field(default_factory=lambda: _new_id("evid"))
    path: str | None = None
    tool_call_id: str | None = None
    trace_event_id: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
            "tool_call_id": self.tool_call_id,
            "trace_event_id": self.trace_event_id,
            "summary": self.summary,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceRef":
        return cls(
            id=str(data.get("id") or _new_id("evid")),
            kind=str(data.get("kind") or "command"),  # type: ignore[arg-type]
            path=data.get("path"),
            tool_call_id=data.get("tool_call_id"),
            trace_event_id=data.get("trace_event_id"),
            summary=str(data.get("summary") or ""),
            timestamp=float(data.get("timestamp") or time.time()),
        )


@dataclass
class ChangedFileRef:
    path: str
    id: str = field(default_factory=lambda: _new_id("change"))
    trace_event_id: str | None = None
    tool_call_id: str | None = None
    tool_trace_event_id: str | None = None
    checkpoint_id: str | None = None
    summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "trace_event_id": self.trace_event_id,
            "tool_call_id": self.tool_call_id,
            "tool_trace_event_id": self.tool_trace_event_id,
            "checkpoint_id": self.checkpoint_id,
            "summary": self.summary,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChangedFileRef":
        return cls(
            id=str(data.get("id") or _new_id("change")),
            path=str(data.get("path") or ""),
            trace_event_id=data.get("trace_event_id"),
            tool_call_id=data.get("tool_call_id"),
            tool_trace_event_id=data.get("tool_trace_event_id"),
            checkpoint_id=data.get("checkpoint_id"),
            summary=str(data.get("summary") or ""),
            timestamp=float(data.get("timestamp") or time.time()),
        )


@dataclass
class CommandEvidence:
    command: str
    id: str = field(default_factory=lambda: _new_id("cmd"))
    status: str = "unknown"
    summary: str = ""
    trace_event_id: str | None = None
    tool_call_id: str | None = None
    tool_trace_event_id: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "status": self.status,
            "summary": self.summary,
            "trace_event_id": self.trace_event_id,
            "tool_call_id": self.tool_call_id,
            "tool_trace_event_id": self.tool_trace_event_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CommandEvidence":
        return cls(
            id=str(data.get("id") or _new_id("cmd")),
            command=str(data.get("command") or ""),
            status=str(data.get("status") or "unknown"),
            summary=str(data.get("summary") or ""),
            trace_event_id=data.get("trace_event_id"),
            tool_call_id=data.get("tool_call_id"),
            tool_trace_event_id=data.get("tool_trace_event_id"),
            timestamp=float(data.get("timestamp") or time.time()),
        )


@dataclass
class VerificationEvidence(CommandEvidence):
    pass


@dataclass
class Blocker:
    summary: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"summary": self.summary, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: dict) -> "Blocker":
        return cls(
            summary=str(data.get("summary") or ""),
            timestamp=float(data.get("timestamp") or time.time()),
        )


@dataclass
class LedgerNote:
    summary: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"summary": self.summary, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: dict) -> "LedgerNote":
        return cls(
            summary=str(data.get("summary") or ""),
            timestamp=float(data.get("timestamp") or time.time()),
        )


@dataclass(frozen=True)
class GoalLedgerEvidenceRecordResult:
    ledger: "GoalLedger"
    evidence_id: str
    ledger_path: str
    related_trace_event_id: str | None = None


@dataclass
class GoalLedger:
    session_key: str
    objective: str
    goal_id: str = field(default_factory=lambda: _new_id("goal"))
    run_id: str | None = None
    status: GoalStatus = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    turn_count: int = 0
    loop_status: LoopStatus = "idle"
    loop_started_at: float | None = None
    loop_finished_at: float | None = None
    pending_approvals: int = 0
    note: str = ""
    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
    plan: list[PlanStep] = field(default_factory=list)
    current_step_id: str | None = None
    inspected_files: list[EvidenceRef] = field(default_factory=list)
    changed_files: list[ChangedFileRef] = field(default_factory=list)
    commands: list[CommandEvidence] = field(default_factory=list)
    verification: list[VerificationEvidence] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    stop_reason: str | None = None
    notes: list[LedgerNote] = field(default_factory=list)
    schema_version: int = GOAL_LEDGER_SCHEMA_VERSION

    def __post_init__(self):
        if self.status not in VALID_GOAL_STATUSES:
            supported = ", ".join(sorted(VALID_GOAL_STATUSES))
            raise ValueError(f"Invalid goal status '{self.status}'. Expected one of: {supported}.")
        if self.loop_status not in VALID_LOOP_STATUSES:
            supported = ", ".join(sorted(VALID_LOOP_STATUSES))
            raise ValueError(f"Invalid loop status '{self.loop_status}'. Expected one of: {supported}.")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "session_key": self.session_key,
            "goal_id": self.goal_id,
            "run_id": self.run_id,
            "objective": self.objective,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turn_count": self.turn_count,
            "loop_status": self.loop_status,
            "loop_started_at": self.loop_started_at,
            "loop_finished_at": self.loop_finished_at,
            "pending_approvals": self.pending_approvals,
            "note": self.note,
            "acceptance_criteria": [item.to_dict() for item in self.acceptance_criteria],
            "plan": [item.to_dict() for item in self.plan],
            "current_step_id": self.current_step_id,
            "inspected_files": [item.to_dict() for item in self.inspected_files],
            "changed_files": [item.to_dict() for item in self.changed_files],
            "commands": [item.to_dict() for item in self.commands],
            "verification": [item.to_dict() for item in self.verification],
            "blockers": [item.to_dict() for item in self.blockers],
            "stop_reason": self.stop_reason,
            "notes": [item.to_dict() for item in self.notes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GoalLedger":
        return cls(
            schema_version=int(data.get("schema_version") or GOAL_LEDGER_SCHEMA_VERSION),
            session_key=str(data.get("session_key") or ""),
            goal_id=str(data.get("goal_id") or _new_id("goal")),
            run_id=data.get("run_id"),
            objective=str(data.get("objective") or ""),
            status=str(data.get("status") or "active"),  # type: ignore[arg-type]
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            turn_count=int(data.get("turn_count") or 0),
            loop_status=str(data.get("loop_status") or _legacy_loop_status(data)),  # type: ignore[arg-type]
            loop_started_at=float(data["loop_started_at"]) if data.get("loop_started_at") else None,
            loop_finished_at=float(data["loop_finished_at"]) if data.get("loop_finished_at") else None,
            pending_approvals=int(data.get("pending_approvals") or 0),
            note=str(data.get("note") or ""),
            acceptance_criteria=[
                AcceptanceCriterion.from_dict(item)
                for item in data.get("acceptance_criteria") or []
            ],
            plan=[PlanStep.from_dict(item) for item in data.get("plan") or []],
            current_step_id=data.get("current_step_id"),
            inspected_files=[
                EvidenceRef.from_dict(item)
                for item in data.get("inspected_files") or []
            ],
            changed_files=[
                ChangedFileRef.from_dict(item)
                for item in data.get("changed_files") or []
            ],
            commands=[
                CommandEvidence.from_dict(item)
                for item in data.get("commands") or []
            ],
            verification=[
                VerificationEvidence.from_dict(item)
                for item in data.get("verification") or []
            ],
            blockers=[Blocker.from_dict(item) for item in data.get("blockers") or []],
            stop_reason=data.get("stop_reason"),
            notes=[LedgerNote.from_dict(item) for item in data.get("notes") or []],
        )

    def render_for_prompt(self) -> str:
        lines = [
            "Current session goal:",
            f"- Objective: {self.objective}",
            f"- Status: {self.status}",
            f"- Loop status: {self.loop_status}",
            f"- Goal turns: {self.turn_count}",
        ]
        if self.run_id:
            lines.append(f"- Latest run id: {self.run_id}")
        if self.stop_reason:
            lines.append(f"- Last stop reason: {self.stop_reason}")
        if self.pending_approvals:
            lines.append(f"- Pending approvals: {self.pending_approvals}")
        if self.plan:
            current = next((step for step in self.plan if step.id == self.current_step_id), None)
            if current is not None:
                lines.append(f"- Current step: {current.description} ({current.status})")
        pending = [
            criterion.description
            for criterion in self.acceptance_criteria
            if criterion.status == "pending"
        ]
        if pending:
            lines.append("- Pending acceptance criteria:")
            lines.extend(f"  - {item}" for item in pending[:5])
        if self.inspected_files:
            paths = [item.path for item in self.inspected_files if item.path]
            if paths:
                lines.append(f"- Inspected files: {', '.join(paths[-5:])}")
        if self.changed_files:
            lines.append(
                "- Changed files: "
                + ", ".join(item.path for item in self.changed_files[-5:])
            )
        if self.verification:
            lines.append(
                "- Verification: "
                + "; ".join(item.summary or item.command for item in self.verification[-3:])
            )
        if self.blockers:
            lines.append(f"- Latest blocker: {self.blockers[-1].summary}")
        elif self.note:
            lines.append(f"- Note: {self.note}")
        lines.append(
            "Continue working toward this goal unless the user redirects. "
            "Use goal_update when it is complete or blocked."
        )
        return "\n".join(lines)


class GoalLedgerStore:
    """Stores one structured goal ledger sidecar per chat session."""

    def __init__(self, ledgers_dir: str):
        self.ledgers_dir = ledgers_dir
        os.makedirs(ledgers_dir, exist_ok=True)

    def _file_path(self, session_key: str) -> str:
        return contained_storage_path(self.ledgers_dir, session_key, ".ledger.json")

    def load(self, session_key: str) -> GoalLedger | None:
        path = self._file_path(session_key)
        data = load_json_with_backup(path)
        if data is not None:
            return GoalLedger.from_dict(data)
        return None

    def save(self, session_key: str, ledger: GoalLedger) -> GoalLedger:
        ledger.updated_at = time.time()
        atomic_write_json(self._file_path(session_key), ledger.to_dict())
        return ledger

    def start(
        self,
        session_key: str,
        objective: str,
        acceptance_criteria: list[str] | None = None,
    ) -> GoalLedger:
        objective = objective.strip()
        if not objective:
            raise ValueError("Goal objective cannot be empty.")
        criteria = [
            AcceptanceCriterion(description=item.strip())
            for item in (acceptance_criteria or [])
            if item and item.strip()
        ]
        return self.save(session_key, GoalLedger(
            session_key=session_key,
            objective=objective,
            acceptance_criteria=criteria,
        ))

    def update(
        self,
        session_key: str,
        status: str | None = None,
        note: str = "",
        *,
        plan: list[str] | None = None,
        current_step: str | None = None,
        acceptance_updates: list[dict] | None = None,
        no_verification_reason: str = "",
    ) -> GoalLedger:
        if status is not None and status not in VALID_GOAL_STATUSES:
            supported = ", ".join(sorted(VALID_GOAL_STATUSES))
            raise ValueError(f"Invalid goal status '{status}'. Expected one of: {supported}.")
        ledger = self.load(session_key)
        if ledger is None:
            raise ValueError("No goal is set for this session.")
        if plan is not None:
            ledger.plan = [
                PlanStep(description=item.strip())
                for item in plan
                if item and item.strip()
            ]
            if ledger.plan and ledger.current_step_id is None:
                ledger.current_step_id = ledger.plan[0].id
        if current_step is not None:
            ledger.current_step_id = self._resolve_current_step_id(ledger, current_step)
        if acceptance_updates:
            self._apply_acceptance_updates(ledger, acceptance_updates)
        if status == "complete":
            self._validate_completion(ledger, no_verification_reason=no_verification_reason)
        if status is not None:
            ledger.status = status  # type: ignore[assignment]
            ledger.stop_reason = status
            if status == "complete":
                ledger.loop_status = "complete"
                ledger.loop_finished_at = time.time()
            elif status == "blocked":
                ledger.loop_status = "blocked"
                ledger.loop_finished_at = time.time()
            elif status == "active" and ledger.loop_status in {"complete", "blocked"}:
                ledger.loop_status = "idle"
        if note.strip():
            ledger.note = note.strip()
        if note.strip():
            ledger.notes.append(LedgerNote(note.strip()))
        if status == "blocked" and note.strip():
            ledger.blockers.append(Blocker(note.strip()))
        if no_verification_reason.strip():
            ledger.verification.append(VerificationEvidence(
                command="",
                status="not_applicable",
                summary=no_verification_reason.strip(),
            ))
        return self.save(session_key, ledger)

    def clear(self, session_key: str) -> bool:
        path = self._file_path(session_key)
        if not os.path.exists(path):
            return False
        os.remove(path)
        return True

    def increment_turn_count(self, session_key: str) -> GoalLedger | None:
        ledger = self.load(session_key)
        if ledger is None or ledger.status != "active":
            return ledger
        ledger.turn_count += 1
        return self.save(session_key, ledger)

    def mark_loop_started(self, session_key: str, *, run_id: str | None = None) -> GoalLedger | None:
        ledger = self.load(session_key)
        if ledger is None or ledger.status != "active":
            return ledger
        ledger.run_id = run_id or ledger.run_id
        ledger.loop_status = "running"
        ledger.loop_started_at = time.time()
        ledger.loop_finished_at = None
        ledger.stop_reason = None
        return self.save(session_key, ledger)

    def mark_loop_finished(
        self,
        session_key: str,
        *,
        stop_reason: str,
        pending_approvals: int = 0,
    ) -> GoalLedger | None:
        ledger = self.load(session_key)
        if ledger is None:
            return None
        ledger.stop_reason = stop_reason
        ledger.loop_finished_at = time.time()
        ledger.pending_approvals = max(0, int(pending_approvals))
        if ledger.status == "complete":
            ledger.loop_status = "complete"
        elif ledger.status == "blocked":
            ledger.loop_status = "blocked"
        elif pending_approvals > 0:
            ledger.loop_status = "paused"
        elif stop_reason in {"max_iterations", "stop_requested", "error"}:
            ledger.loop_status = "paused"
        else:
            ledger.loop_status = "waiting"
        return self.save(session_key, ledger)

    def record_evidence(
        self,
        session_key: str,
        *,
        kind: EvidenceKind,
        summary: str,
        path: str | None = None,
        command: str | None = None,
        status: str | None = None,
        tool_call_id: str | None = None,
        trace_event_id: str | None = None,
        tool_trace_event_id: str | None = None,
    ) -> GoalLedger:
        return self.record_evidence_with_result(
            session_key,
            kind=kind,
            summary=summary,
            path=path,
            command=command,
            status=status,
            tool_call_id=tool_call_id,
            trace_event_id=trace_event_id,
            tool_trace_event_id=tool_trace_event_id,
        ).ledger

    def record_evidence_with_result(
        self,
        session_key: str,
        *,
        kind: EvidenceKind,
        summary: str,
        path: str | None = None,
        command: str | None = None,
        status: str | None = None,
        tool_call_id: str | None = None,
        trace_event_id: str | None = None,
        tool_trace_event_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> GoalLedgerEvidenceRecordResult:
        ledger = self.load(session_key)
        if ledger is None:
            raise ValueError("No goal is set for this session.")
        summary = summary.strip()
        if not summary:
            raise ValueError("Evidence summary cannot be empty.")
        evidence_id = ""
        evidence = EvidenceRef(
            kind=kind,
            path=path,
            tool_call_id=tool_call_id,
            trace_event_id=trace_event_id,
            summary=summary,
        )
        if kind in {"read", "search", "status", "diff"}:
            ledger.inspected_files.append(evidence)
            evidence_id = evidence.id
        elif kind in {"command", "test"}:
            item = CommandEvidence(
                command=command or "",
                status=status or "unknown",
                summary=summary,
                trace_event_id=trace_event_id,
                tool_call_id=tool_call_id,
                tool_trace_event_id=tool_trace_event_id,
            )
            ledger.commands.append(item)
            evidence_id = item.id
            if kind == "test":
                verification = VerificationEvidence(
                    command=command or "",
                    status=status or "unknown",
                    summary=summary,
                    trace_event_id=trace_event_id,
                    tool_call_id=tool_call_id,
                    tool_trace_event_id=tool_trace_event_id,
                )
                ledger.verification.append(verification)
                evidence_id = verification.id
        elif kind == "checkpoint":
            changed_file = ChangedFileRef(
                path=path or "",
                trace_event_id=trace_event_id,
                tool_call_id=tool_call_id,
                tool_trace_event_id=tool_trace_event_id,
                checkpoint_id=checkpoint_id,
                summary=summary,
            )
            ledger.changed_files.append(changed_file)
            evidence_id = changed_file.id
        else:
            raise ValueError(f"Unsupported evidence kind: {kind}")
        saved = self.save(session_key, ledger)
        return GoalLedgerEvidenceRecordResult(
            ledger=saved,
            evidence_id=evidence_id,
            ledger_path=self._file_path(session_key),
            related_trace_event_id=trace_event_id,
        )

    def _validate_completion(
        self,
        ledger: GoalLedger,
        *,
        no_verification_reason: str = "",
    ):
        if ledger.acceptance_criteria and any(
            item.status == "pending"
            for item in ledger.acceptance_criteria
        ):
            raise ValueError(
                "Cannot complete goal until every acceptance criterion is "
                "satisfied or marked not_applicable."
            )
        if ledger.changed_files and not ledger.verification and not no_verification_reason.strip():
            raise ValueError(
                "Cannot complete goal with changed files until verification evidence "
                "or a no_verification_reason is recorded."
            )

    def _resolve_current_step_id(self, ledger: GoalLedger, current_step: str) -> str | None:
        current_step = current_step.strip()
        if not current_step:
            return None
        for step in ledger.plan:
            if step.id == current_step:
                return step.id
        normalized = current_step.lower()
        for step in ledger.plan:
            if step.description.lower() == normalized:
                return step.id
        raise ValueError(f"Current step '{current_step}' does not match a plan step.")

    def _apply_acceptance_updates(
        self,
        ledger: GoalLedger,
        updates: list[dict],
    ):
        by_id = {item.id: item for item in ledger.acceptance_criteria}
        by_description = {
            item.description.lower(): item
            for item in ledger.acceptance_criteria
        }
        for update in updates:
            criterion = None
            criterion_id = str(update.get("id") or "").strip()
            description = str(update.get("description") or "").strip()
            if criterion_id:
                criterion = by_id.get(criterion_id)
            if criterion is None and description:
                criterion = by_description.get(description.lower())
            if criterion is None:
                raise ValueError("Acceptance update does not match an existing criterion.")
            status = update.get("status")
            if status is not None:
                if status not in {"pending", "satisfied", "not_applicable"}:
                    raise ValueError(f"Invalid acceptance criterion status '{status}'.")
                criterion.status = status
            evidence = update.get("evidence")
            if isinstance(evidence, str) and evidence.strip():
                criterion.evidence.append(evidence.strip())
            elif isinstance(evidence, list):
                criterion.evidence.extend(str(item).strip() for item in evidence if str(item).strip())
