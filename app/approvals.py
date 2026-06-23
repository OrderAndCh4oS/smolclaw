"""Durable approval requests for policy ``ask`` decisions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from app import diagnostics
from app.storage_paths import atomic_write_json, contained_storage_path, load_json_with_backup


ApprovalStatus = Literal["pending", "approved", "denied", "used"]
ApprovalScope = Literal["once"]


def approval_arguments_hash(tool_name: str, arguments: Mapping[str, Any]) -> str:
    payload = {
        "tool": tool_name,
        "arguments": _json_safe(arguments),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    expires_at: float | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    run_id: str | None = None

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
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_id": self.run_id,
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
            expires_at=float(data["expires_at"]) if data.get("expires_at") else None,
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            run_id=str(data["run_id"]) if data.get("run_id") else None,
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
        expires_at: float | None = None,
    ) -> ApprovalRequest:
        arguments_hash = approval_arguments_hash(tool_name, arguments)
        approval_id = approval_request_id(session_key, tool_name, arguments_hash)
        requests = self._load(session_key)
        now = time.time()
        for index, existing in enumerate(requests):
            if existing.id == approval_id:
                if existing.status == "used":
                    existing.status = "pending"
                existing.reason = reason or existing.reason
                existing.run_id = run_id or existing.run_id
                existing.scope = scope
                existing.requested_action = requested_action or existing.requested_action
                existing.matched_subject = matched_subject or existing.matched_subject
                existing.matched_pattern = matched_pattern or existing.matched_pattern
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
            expires_at=expires_at,
            run_id=run_id,
        )
        requests.append(request)
        self._save(session_key, requests)
        return request

    def approve(self, session_key: str, approval_id: str) -> ApprovalRequest:
        return self._set_status(session_key, approval_id, "approved")

    def deny(self, session_key: str, approval_id: str) -> ApprovalRequest:
        return self._set_status(session_key, approval_id, "denied")

    def consume_approved(self, session_key: str, *, tool_name: str, arguments: Mapping[str, Any]) -> ApprovalRequest | None:
        arguments_hash = approval_arguments_hash(tool_name, arguments)
        requests = self._load(session_key)
        for index, request in enumerate(requests):
            if (
                request.tool_name == tool_name
                and request.arguments_hash == arguments_hash
                and request.status == "approved"
            ):
                if request.expires_at is not None and request.expires_at < time.time():
                    request.status = "denied"
                    request.updated_at = time.time()
                    requests[index] = request
                    self._save(session_key, requests)
                    return None
                request.status = "used"
                request.updated_at = time.time()
                requests[index] = request
                self._save(session_key, requests)
                return request
        return None

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
        data = load_json_with_backup(self.path_for(session_key), default=[])
        if not isinstance(data, list):
            return []
        return [ApprovalRequest.from_dict(item) for item in data if isinstance(item, Mapping)]

    def _save(self, session_key: str, requests: list[ApprovalRequest]):
        atomic_write_json(self.path_for(session_key), [request.to_dict() for request in requests])


def _argument_preview(arguments: Mapping[str, Any]) -> Any:
    return _truncate(_json_safe(diagnostics.redact(dict(arguments))), max_chars=1200)


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except TypeError:
        return str(value)


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
    lines.append("Use /approval detail <id>, /approval approve <id>, or /approval deny <id>.")
    return "\n".join(lines)


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
    rule = _format_rule(request)
    if rule:
        lines.append(f"Matched rule: {rule}")
    if request.run_id:
        lines.append(f"Run: {request.run_id}")
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


def _format_expiry(expires_at: float | None) -> str:
    if expires_at is None:
        return "none"
    if expires_at < time.time():
        return f"expired at {expires_at:.0f}"
    return f"{expires_at:.0f}"
