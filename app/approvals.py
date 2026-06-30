"""Durable approval requests for policy ``ask`` decisions."""

from __future__ import annotations

import hashlib
import json
import os
import time
import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Mapping

from app import diagnostics
from app.storage_paths import atomic_write_json, contained_storage_path, load_json_with_backup
from app.execution_grants import ExecutionGrant


ApprovalStatus = Literal["pending", "approved", "denied", "used"]
ApprovalScope = Literal["once"]
ApprovalReply = Literal["once", "always", "reject"]
PermissionEventSink = Callable[[dict[str, Any]], Awaitable[None]]


class PermissionRejectedError(Exception):
    def __init__(self, request: "ApprovalRequest", message: str = ""):
        self.request = request
        self.message = message
        super().__init__(message or f"Permission request rejected: {request.id}")


class PermissionInteractionUnavailableError(Exception):
    def __init__(self, request: "ApprovalRequest"):
        self.request = request
        super().__init__(f"Permission request requires interaction: {request.id}")


def approval_arguments_hash(
    tool_name: str,
    arguments: Mapping[str, Any],
) -> str:
    payload = {
        "tool": tool_name,
        "arguments": _approval_fingerprint_arguments(tool_name, arguments),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _legacy_approval_arguments_hash(tool_name: str, arguments: Mapping[str, Any]) -> str:
    payload = {
        "tool": tool_name,
        "arguments": _json_safe(arguments),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _approval_argument_hashes(
    tool_name: str,
    arguments: Mapping[str, Any],
) -> tuple[str, ...]:
    primary = approval_arguments_hash(tool_name, arguments)
    legacy = _legacy_approval_arguments_hash(tool_name, arguments)
    if legacy == primary:
        return (primary,)
    return (primary, legacy)


def approval_request_id(session_key: str, tool_name: str, arguments_hash: str) -> str:
    raw = f"{session_key}\0{tool_name}\0{arguments_hash}"
    return "apr-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ApprovalRequest:
    id: str
    session_key: str
    tool_name: str
    arguments_hash: str
    arguments_preview: Any
    reason: str
    status: ApprovalStatus = "pending"
    scope: ApprovalScope = "once"
    requested_action: str = "ask"
    matched_subject: str | None = None
    matched_pattern: str | None = None
    granted_effects: tuple[str, ...] = ()
    expires_at: float | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    run_id: str | None = None
    origin_session_key: str | None = None
    origin_run_id: str | None = None
    rationale: str = ""
    expected_outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_key": self.session_key,
            "tool_name": self.tool_name,
            "arguments_hash": self.arguments_hash,
            "arguments_preview": self.arguments_preview,
            "reason": self.reason,
            "status": self.status,
            "scope": self.scope,
            "requested_action": self.requested_action,
            "matched_subject": self.matched_subject,
            "matched_pattern": self.matched_pattern,
            "granted_effects": list(self.granted_effects),
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_id": self.run_id,
            "origin_session_key": self.origin_session_key,
            "origin_run_id": self.origin_run_id,
            "rationale": self.rationale,
            "expected_outcome": self.expected_outcome,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ApprovalRequest":
        return cls(
            id=str(data["id"]),
            session_key=str(data["session_key"]),
            tool_name=str(data["tool_name"]),
            arguments_hash=str(data["arguments_hash"]),
            arguments_preview=data.get("arguments_preview"),
            reason=str(data.get("reason") or ""),
            status=str(data.get("status") or "pending"),  # type: ignore[arg-type]
            scope=str(data.get("scope") or "once"),  # type: ignore[arg-type]
            requested_action=str(data.get("requested_action") or "ask"),
            matched_subject=str(data["matched_subject"]) if data.get("matched_subject") else None,
            matched_pattern=str(data["matched_pattern"]) if data.get("matched_pattern") else None,
            granted_effects=tuple(str(effect) for effect in data.get("granted_effects") or ()),
            expires_at=float(data["expires_at"]) if data.get("expires_at") else None,
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            run_id=str(data["run_id"]) if data.get("run_id") else None,
            origin_session_key=(
                str(data["origin_session_key"])
                if data.get("origin_session_key")
                else str(data["session_key"]) if data.get("session_key") else None
            ),
            origin_run_id=(
                str(data["origin_run_id"])
                if data.get("origin_run_id")
                else str(data["run_id"]) if data.get("run_id") else None
            ),
            rationale=str(data.get("rationale") or ""),
            expected_outcome=str(data.get("expected_outcome") or ""),
        )


class ApprovalRequestStore:
    def __init__(self, approvals_dir: str):
        self.approvals_dir = approvals_dir

    def path_for(self, session_key: str) -> str:
        return contained_storage_path(self.approvals_dir, session_key, ".approvals.json")

    def list(self, session_key: str, *, status: ApprovalStatus | None = None) -> list[ApprovalRequest]:
        requests = self._load(session_key)
        if status is not None:
            return [request for request in requests if request.status == status]
        return requests

    def list_all(self, *, status: ApprovalStatus | None = None) -> list[ApprovalRequest]:
        requests: list[ApprovalRequest] = []
        try:
            filenames = sorted(os.listdir(self.approvals_dir))
        except FileNotFoundError:
            return []
        for filename in filenames:
            if not filename.endswith(".approvals.json"):
                continue
            path = os.path.join(self.approvals_dir, filename)
            requests.extend(self._load_path(path))
        if status is not None:
            return [request for request in requests if request.status == status]
        return requests

    def get(self, session_key: str, approval_id: str) -> ApprovalRequest | None:
        for request in self._load(session_key):
            if request.id == approval_id:
                return request
        return None

    def request(
        self,
        session_key: str,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        reason: str = "",
        run_id: str | None = None,
        scope: ApprovalScope = "once",
        requested_action: str = "ask",
        matched_subject: str | None = None,
        matched_pattern: str | None = None,
        granted_effects: tuple[str, ...] = (),
        expires_at: float | None = None,
        origin_session_key: str | None = None,
        origin_run_id: str | None = None,
        rationale: str = "",
        expected_outcome: str = "",
    ) -> ApprovalRequest:
        granted_effects = tuple(sorted(set(granted_effects)))
        arguments_hash = approval_arguments_hash(tool_name, arguments)
        approval_id = approval_request_id(session_key, tool_name, arguments_hash)
        candidate_hashes = set(_approval_argument_hashes(tool_name, arguments))
        candidate_ids = {
            approval_request_id(session_key, tool_name, candidate_hash)
            for candidate_hash in candidate_hashes
        }
        requests = self._load(session_key)
        now = time.time()
        for index, existing in enumerate(requests):
            if existing.id in candidate_ids or _request_matches_arguments(
                existing,
                tool_name,
                arguments,
                candidate_hashes,
            ):
                requested_effects = tuple(sorted(set(existing.granted_effects).union(granted_effects)))
                if existing.status in {"used", "approved"}:
                    existing.status = "pending"
                existing.reason = reason or existing.reason
                existing.rationale = rationale or existing.rationale
                existing.expected_outcome = expected_outcome or existing.expected_outcome
                existing.run_id = run_id or existing.run_id
                existing.origin_session_key = origin_session_key or existing.origin_session_key
                existing.origin_run_id = origin_run_id or run_id or existing.origin_run_id
                existing.scope = scope
                existing.requested_action = requested_action or existing.requested_action
                existing.matched_subject = matched_subject or existing.matched_subject
                existing.matched_pattern = matched_pattern or existing.matched_pattern
                existing.granted_effects = requested_effects
                existing.expires_at = expires_at if expires_at is not None else existing.expires_at
                existing.updated_at = now
                requests[index] = existing
                self._save(session_key, requests)
                return existing
        request = ApprovalRequest(
            id=approval_id,
            session_key=session_key,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            arguments_preview=_argument_preview(arguments),
            reason=reason,
            scope=scope,
            requested_action=requested_action,
            matched_subject=matched_subject,
            matched_pattern=matched_pattern,
            granted_effects=tuple(granted_effects),
            expires_at=expires_at,
            run_id=run_id,
            origin_session_key=origin_session_key or session_key,
            origin_run_id=origin_run_id or run_id,
            rationale=rationale,
            expected_outcome=expected_outcome,
        )
        requests.append(request)
        self._save(session_key, requests)
        return request

    def approve(self, session_key: str, approval_id: str) -> ApprovalRequest:
        return self._set_status(session_key, approval_id, "approved")

    def deny(self, session_key: str, approval_id: str) -> ApprovalRequest:
        return self._set_status(session_key, approval_id, "denied")

    def consume_approved(
        self,
        session_key: str,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        required_effects: tuple[str, ...] = (),
    ) -> ApprovalRequest | None:
        candidate_hashes = set(_approval_argument_hashes(tool_name, arguments))
        required_effect_set = set(required_effects)
        requests = self._load(session_key)
        for index, request in enumerate(requests):
            if (
                _request_matches_arguments(
                    request,
                    tool_name,
                    arguments,
                    candidate_hashes=candidate_hashes,
                )
                and request.status == "approved"
            ):
                if required_effect_set and not required_effect_set.issubset(set(request.granted_effects)):
                    request.status = "pending"
                    request.granted_effects = tuple(sorted(set(request.granted_effects).union(required_effect_set)))
                    request.updated_at = time.time()
                    requests[index] = request
                    self._save(session_key, requests)
                    return None
                if request.expires_at is not None and request.expires_at < time.time():
                    request.status = "denied"
                    request.updated_at = time.time()
                    requests[index] = request
                    self._save(session_key, requests)
                    return None
                request.updated_at = time.time()
                requests[index] = request
                self._save(session_key, requests)
                return request
        return None

    def mark_used(self, session_key: str, approval_id: str) -> ApprovalRequest:
        return self._set_status(session_key, approval_id, "used")

    def mark_pending(self, session_key: str, approval_id: str) -> ApprovalRequest:
        return self._set_status(session_key, approval_id, "pending")

    def _set_status(self, session_key: str, approval_id: str, status: ApprovalStatus) -> ApprovalRequest:
        requests = self._load(session_key)
        for index, request in enumerate(requests):
            if request.id == approval_id:
                request.status = status
                request.updated_at = time.time()
                requests[index] = request
                self._save(session_key, requests)
                return request
        raise KeyError(f"No approval request '{approval_id}' for session '{session_key}'.")

    def _load(self, session_key: str) -> list[ApprovalRequest]:
        return self._load_path(self.path_for(session_key))

    def _load_path(self, path: str) -> list[ApprovalRequest]:
        data = load_json_with_backup(path, default=[])
        if not isinstance(data, list):
            return []
        return [ApprovalRequest.from_dict(item) for item in data if isinstance(item, Mapping)]

    def _save(self, session_key: str, requests: list[ApprovalRequest]):
        atomic_write_json(self.path_for(session_key), [request.to_dict() for request in requests])


@dataclass
class _PendingPermission:
    request: ApprovalRequest
    future: asyncio.Future
    loop: asyncio.AbstractEventLoop
    event_sink: PermissionEventSink | None = None
    trace_recorder: Any = None


@dataclass(frozen=True)
class _AlwaysRule:
    tool_name: str
    arguments_hash: str
    effects: frozenset[str]
    approval_id: str
    run_id: str | None = None

    def matches(self, *, tool_name: str, arguments_hash: str, effects: frozenset[str]) -> bool:
        return (
            self.tool_name == tool_name
            and self.arguments_hash == arguments_hash
            and effects.issubset(self.effects)
        )


class PermissionController:
    """Live approval control plane.

    The store is a mirror for review/status only; pending futures are the
    authority that resumes suspended tool calls.
    """

    def __init__(self, approval_store: ApprovalRequestStore | None = None):
        self.approval_store = approval_store
        self._pending: dict[str, _PendingPermission] = {}
        self._always: list[_AlwaysRule] = []

    async def assert_allowed(
        self,
        *,
        session_key: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        reason: str = "",
        matched_subject: str | None = None,
        matched_pattern: str | None = None,
        effects: tuple[str, ...] = (),
        run_id: str | None = None,
        origin_session_key: str | None = None,
        origin_run_id: str | None = None,
        rationale: str = "",
        expected_outcome: str = "",
        event_sink: PermissionEventSink | None = None,
        trace_recorder: Any = None,
    ) -> ExecutionGrant:
        effects_set = frozenset(str(effect) for effect in effects)
        arguments_hash = approval_arguments_hash(tool_name, arguments)
        for rule in reversed(self._always):
            if rule.matches(tool_name=tool_name, arguments_hash=arguments_hash, effects=effects_set):
                return ExecutionGrant(
                    tool_name=tool_name,
                    arguments_hash=arguments_hash,
                    approval_id=rule.approval_id,
                    effects=effects_set,
                    run_id=rule.run_id,
                )

        request = self._request(
            session_key,
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
            run_id=run_id,
            matched_subject=matched_subject,
            matched_pattern=matched_pattern,
            granted_effects=tuple(sorted(effects_set)),
            origin_session_key=origin_session_key,
            origin_run_id=origin_run_id,
            rationale=rationale,
            expected_outcome=expected_outcome,
        )
        if event_sink is None:
            self._set_status(request, "denied")
            raise PermissionInteractionUnavailableError(request)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        pending = _PendingPermission(
            request=request,
            future=future,
            loop=loop,
            event_sink=event_sink,
            trace_recorder=trace_recorder,
        )
        self._pending[request.id] = pending
        self._trace(trace_recorder, "approval.requested", request, reply=None)
        await event_sink({
            "type": "permission",
            "phase": "requested",
            "approval_id": request.id,
            "request": request,
            "session_key": request.session_key,
            "origin_session_key": request.origin_session_key,
            "tool": request.tool_name,
            "reason": request.reason,
            "rationale": request.rationale,
            "expected_outcome": request.expected_outcome,
            "effects": list(request.granted_effects),
            "matched_subject": request.matched_subject,
            "matched_pattern": request.matched_pattern,
        })
        try:
            reply, message = await future
        finally:
            self._pending.pop(request.id, None)

        if reply == "reject":
            self._set_status(request, "denied")
            raise PermissionRejectedError(request, message)
        if reply == "always":
            self._always.append(_AlwaysRule(
                tool_name=request.tool_name,
                arguments_hash=request.arguments_hash,
                effects=frozenset(request.granted_effects),
                approval_id=request.id,
                run_id=request.run_id,
            ))
        self._set_status(request, "approved")
        return ExecutionGrant.from_approval(request, effects=request.granted_effects)

    def reply(self, approval_id: str, reply: ApprovalReply, message: str = "") -> ApprovalRequest:
        if reply not in {"once", "always", "reject"}:
            raise ValueError("approval reply must be one of: once, always, reject")
        pending = self._pending.get(approval_id)
        if pending is None:
            raise KeyError(f"No pending approval request '{approval_id}'.")
        self._pending.pop(approval_id, None)
        request = pending.request
        status: ApprovalStatus = "denied" if reply == "reject" else "approved"
        self._set_status(request, status)
        self._trace(pending.trace_recorder, "approval.resolved", request, reply=reply)

        def _resolve():
            if pending.future.done():
                return
            pending.future.set_result((reply, message))

        if pending.loop.is_running():
            pending.loop.call_soon_threadsafe(_resolve)
        else:
            _resolve()

        if reply == "always":
            self._resolve_matching_always(request)
        return request

    def approve(self, session_key: str, approval_id: str) -> ApprovalRequest:
        _ = session_key
        return self.reply(approval_id, "once")

    def deny(self, session_key: str, approval_id: str) -> ApprovalRequest:
        _ = session_key
        return self.reply(approval_id, "reject")

    def mark_used(self, request: ApprovalRequest) -> None:
        self._set_status(request, "used")

    def list_pending(self, session_key: str | None = None) -> list[ApprovalRequest]:
        requests = [pending.request for pending in self._pending.values()]
        if session_key:
            requests = [
                request for request in requests
                if request.session_key == session_key or request.origin_session_key == session_key
            ]
        return sorted(requests, key=lambda request: request.created_at)

    def get(self, session_key: str, approval_id: str) -> ApprovalRequest | None:
        pending = self._pending.get(approval_id)
        if pending and (not session_key or pending.request.session_key == session_key):
            return pending.request
        if self.approval_store is not None:
            return self.approval_store.get(session_key, approval_id)
        return None

    def cancel_session(self, session_key: str, *, message: str = "") -> None:
        for pending in list(self._pending.values()):
            if pending.request.session_key != session_key and pending.request.origin_session_key != session_key:
                continue
            self.reply(pending.request.id, "reject", message)

    def _request(self, session_key: str, **kwargs) -> ApprovalRequest:
        if self.approval_store is not None:
            return self.approval_store.request(session_key, **kwargs)
        arguments = kwargs["arguments"]
        tool_name = kwargs["tool_name"]
        request = ApprovalRequest(
            id=approval_request_id(session_key, tool_name, approval_arguments_hash(tool_name, arguments)),
            session_key=session_key,
            tool_name=tool_name,
            arguments_hash=approval_arguments_hash(tool_name, arguments),
            arguments_preview=_argument_preview(arguments),
            reason=kwargs.get("reason") or "",
            rationale=kwargs.get("rationale") or "",
            expected_outcome=kwargs.get("expected_outcome") or "",
            matched_subject=kwargs.get("matched_subject"),
            matched_pattern=kwargs.get("matched_pattern"),
            granted_effects=tuple(kwargs.get("granted_effects") or ()),
            run_id=kwargs.get("run_id"),
            origin_session_key=kwargs.get("origin_session_key") or session_key,
            origin_run_id=kwargs.get("origin_run_id") or kwargs.get("run_id"),
        )
        return request

    def _set_status(self, request: ApprovalRequest, status: ApprovalStatus) -> None:
        request.status = status
        request.updated_at = time.time()
        if self.approval_store is None:
            return
        try:
            self.approval_store._set_status(request.session_key, request.id, status)
        except KeyError:
            return

    def _resolve_matching_always(self, request: ApprovalRequest) -> None:
        for pending in list(self._pending.values()):
            item = pending.request
            if item.id == request.id:
                continue
            if item.session_key != request.session_key:
                continue
            if item.tool_name != request.tool_name:
                continue
            if item.arguments_hash != request.arguments_hash:
                continue
            if not set(item.granted_effects).issubset(set(request.granted_effects)):
                continue
            self.reply(item.id, "always")

    def _trace(self, trace_recorder, event: str, request: ApprovalRequest, *, reply: str | None) -> None:
        if trace_recorder is None:
            return
        data = {
            "approval_id": request.id,
            "tool": request.tool_name,
            "reason": request.reason,
            "rationale": request.rationale,
            "expected_outcome": request.expected_outcome,
            "scope": request.scope,
            "arguments_hash": request.arguments_hash,
            "matched_subject": request.matched_subject,
            "matched_pattern": request.matched_pattern,
            "granted_effects": list(request.granted_effects),
            "run_id": request.run_id,
            "origin_session_key": request.origin_session_key,
            "origin_run_id": request.origin_run_id,
        }
        if reply is not None:
            data["reply"] = reply
            data["status"] = "denied" if reply == "reject" else "approved"
        trace_recorder.append(event, data)


def _argument_preview(arguments: Mapping[str, Any]) -> Any:
    return _truncate(_json_safe(diagnostics.redact(dict(arguments))), max_chars=1200)


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except TypeError:
        return str(value)


def _approval_fingerprint_arguments(tool_name: str, arguments: Mapping[str, Any]) -> Any:
    safe_arguments = _json_safe(arguments)
    if tool_name != "run_command" or not isinstance(safe_arguments, Mapping):
        return safe_arguments
    fingerprint: dict[str, Any] = {}
    command = safe_arguments.get("command")
    if command is not None:
        fingerprint["command"] = command
    fingerprint["cwd"] = safe_arguments.get("cwd") or "."
    return fingerprint


def _request_matches_arguments(
    request: ApprovalRequest,
    tool_name: str,
    arguments: Mapping[str, Any],
    candidate_hashes: set[str],
) -> bool:
    if request.tool_name != tool_name:
        return False
    if request.arguments_hash in candidate_hashes:
        return True
    if not isinstance(request.arguments_preview, Mapping):
        return False
    if (
        _approval_fingerprint_arguments(tool_name, request.arguments_preview)
        == _approval_fingerprint_arguments(tool_name, arguments)
    ):
        return True
    return False


def _truncate(value: Any, *, max_chars: int) -> Any:
    text = json.dumps(value, sort_keys=True, default=str)
    if len(text) <= max_chars:
        return value
    return {
        "truncated": True,
        "preview": text[: max_chars - 3] + "...",
    }


def format_approval_status(store: ApprovalRequestStore, session_key: str) -> str:
    pending = store.list(session_key, status="pending")
    if not pending:
        return "No pending approval requests."
    lines = ["Pending approvals:"]
    for request in pending:
        reason = f" - {request.reason}" if request.reason else ""
        rule = _format_rule(request)
        rule_suffix = f" ({rule})" if rule else ""
        lines.append(f"- {request.id}: {request.tool_name}{rule_suffix}{reason}")
    lines.append(
        "Use /approval review, /approval detail <id>, /approval approve <id>, or /approval deny <id>."
    )
    return "\n".join(lines)


def format_approval_review(store: ApprovalRequestStore, session_key: str) -> str:
    pending = store.list(session_key, status="pending")
    if not pending:
        return "No pending approval requests."
    lines = [
        "Approval review:",
        "Select a request, inspect the exact arguments, then approve or deny it.",
    ]
    for index, request in enumerate(pending, start=1):
        lines.append(f"{index}. {format_approval_review_option(request)}")
    lines.append("Actions: approve, deny, detail, skip, quit.")
    return "\n".join(lines)


def format_approval_review_option(request: ApprovalRequest) -> str:
    rule = _format_rule(request)
    rule_suffix = f" ({rule})" if rule else ""
    reason = f" - {request.reason}" if request.reason else ""
    run = f" run:{request.run_id}" if request.run_id else ""
    origin = (
        f" origin:{request.origin_session_key}"
        if request.origin_session_key and request.origin_session_key != request.session_key
        else ""
    )
    effects = f" effects:{','.join(sorted(request.granted_effects))}" if request.granted_effects else ""
    preview = _format_arguments_preview(request.arguments_preview)
    preview_suffix = f" args:{preview}" if preview else ""
    return f"{request.id}: {request.tool_name}{rule_suffix}{run}{origin}{effects}{reason}{preview_suffix}"


def format_approval_summary_lines(request: ApprovalRequest, *, max_argument_lines: int = 4) -> list[str]:
    lines = [
        f"Tool: {request.tool_name}",
    ]
    if request.rationale:
        lines.append(f"Rationale: {_truncate_text(request.rationale, 220)}")
    elif request.reason:
        lines.append(f"Reason: {_truncate_text(request.reason, 220)}")
    if request.expected_outcome:
        lines.append(f"Expected outcome: {_truncate_text(request.expected_outcome, 220)}")
    operation = _format_operation_summary(request)
    if operation:
        lines.append(f"Operation: {operation}")
    for line in _format_argument_summary_lines(request.arguments_preview)[:max_argument_lines]:
        lines.append(line)
    if request.granted_effects:
        lines.append(f"Effects: {', '.join(sorted(request.granted_effects))}")
    return lines


def format_approval_detail(store: ApprovalRequestStore, session_key: str, approval_id: str) -> str:
    request = store.get(session_key, approval_id)
    if request is None:
        return f"Error: No approval request '{approval_id}' for session '{session_key}'."
    lines = [
        f"Approval: {request.id}",
        f"Status: {request.status}",
        f"Tool: {request.tool_name}",
        f"Scope: {request.scope}",
        f"Requested action: {request.requested_action}",
        f"Arguments hash: {request.arguments_hash}",
    ]
    if request.reason:
        lines.append(f"Reason: {request.reason}")
    if request.rationale:
        lines.append(f"Rationale: {request.rationale}")
    if request.expected_outcome:
        lines.append(f"Expected outcome: {request.expected_outcome}")
    rule = _format_rule(request)
    if rule:
        lines.append(f"Matched rule: {rule}")
    if request.run_id:
        lines.append(f"Run: {request.run_id}")
    if request.origin_session_key and request.origin_session_key != request.session_key:
        lines.append(f"Origin session: {request.origin_session_key}")
    if request.origin_run_id and request.origin_run_id != request.run_id:
        lines.append(f"Origin run: {request.origin_run_id}")
    if request.granted_effects:
        lines.append(f"Granted effects: {', '.join(sorted(request.granted_effects))}")
    lines.append(f"Expiry: {_format_expiry(request.expires_at)}")
    lines.append(f"Arguments: {json.dumps(request.arguments_preview, sort_keys=True, default=str)}")
    if request.status == "pending":
        lines.append("Use /approval approve <id> to allow this exact call once, or /approval deny <id> to reject it.")
    return "\n".join(lines)


def _format_rule(request: ApprovalRequest) -> str:
    if request.matched_subject and request.matched_pattern:
        return f"{request.matched_subject}:{request.matched_pattern}"
    if request.matched_subject:
        return request.matched_subject
    if request.matched_pattern:
        return request.matched_pattern
    return ""


def _format_arguments_preview(arguments_preview: Any) -> str:
    if isinstance(arguments_preview, Mapping):
        command = arguments_preview.get("command")
        if isinstance(command, str) and command:
            return _truncate_text(command, 80)
        path = arguments_preview.get("path")
        if isinstance(path, str) and path:
            return _truncate_text(path, 80)
        if arguments_preview.get("truncated") is True:
            preview = arguments_preview.get("preview")
            if isinstance(preview, str):
                return _truncate_text(preview, 80)
    if isinstance(arguments_preview, str):
        return _truncate_text(arguments_preview, 80)
    return ""


def _format_operation_summary(request: ApprovalRequest) -> str:
    arguments = request.arguments_preview
    if not isinstance(arguments, Mapping):
        return ""
    if request.tool_name == "run_command":
        command = arguments.get("command")
        cwd = arguments.get("cwd") or "."
        if isinstance(command, str) and command:
            return f"run `{_truncate_text(command, 120)}` in {cwd}"
    if request.tool_name.startswith("work_loop_"):
        return request.tool_name.removeprefix("work_loop_").replace("_", " ")
    path = arguments.get("path")
    if isinstance(path, str) and path:
        return f"use path {path}"
    title = arguments.get("title")
    if isinstance(title, str) and title:
        return _truncate_text(title, 120)
    return ""


def _format_argument_summary_lines(arguments_preview: Any) -> list[str]:
    if not isinstance(arguments_preview, Mapping):
        return []
    if arguments_preview.get("truncated") is True:
        preview = arguments_preview.get("preview")
        return [f"Arguments: {_truncate_text(str(preview), 180)}"] if preview else []
    lines: list[str] = []
    for key, value in arguments_preview.items():
        if key in {"approval_rationale", "approval_expected_outcome"}:
            continue
        if value in (None, "", [], {}):
            continue
        label = str(key).replace("_", " ").title()
        rendered = _truncate_text(_format_argument_value(value), 160)
        lines.append(f"{label}: {rendered}")
    return lines


def _format_argument_value(value: Any) -> str:
    if isinstance(value, str):
        return value.replace("\n", "\\n")
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _truncate_text(value: str, max_chars: int) -> str:
    value = value.replace("\n", " ")
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _format_expiry(expires_at: float | None) -> str:
    if expires_at is None:
        return "none"
    if expires_at < time.time():
        return f"expired at {expires_at:.0f}"
    return f"{expires_at:.0f}"
