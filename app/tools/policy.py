"""Policy-shaped permission middleware layered over existing mode protections."""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

import yaml

from app.execution_grants import ExecutionGrant, IMAGE_MANAGEMENT_EFFECT, NETWORK_EFFECT, SHELL_SESSION_EFFECT
from app.runtime_state import RuntimeSharedState
from app.workspace import WorkspaceContext
from app.approvals import PermissionInteractionUnavailableError, PermissionRejectedError
from app.tools.base import Tool, ToolResult, normalize_tool_result, tool_policy_effects
from app.tools.middleware import NextFn
from app.tools.permissions import (
    PERMISSION_MODES,
    VALID_PERMISSION_MODES,
    PermissionMiddleware,
    _policy_capabilities,
)


PermissionAction = Literal["allow", "ask", "deny"]
VALID_POLICY_SUBJECTS = frozenset({"tool", "capability", "path", "command"})
_ACTION_RANK = {"allow": 0, "ask": 1, "deny": 2}


@dataclass(frozen=True)
class PermissionRule:
    subject: str
    pattern: str
    action: PermissionAction
    reason: str = ""


@dataclass(frozen=True)
class PermissionPolicy:
    default_action: PermissionAction = "allow"
    rules: tuple[PermissionRule, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PermissionPolicy":
        rules = []
        for item in data.get("rules") or []:
            rules.append(PermissionRule(
                subject=str(item.get("subject") or ""),
                pattern=str(item.get("pattern") or "*"),
                action=str(item.get("action") or "deny"),  # type: ignore[arg-type]
                reason=str(item.get("reason") or ""),
            ))
        return cls(
            default_action=str(data.get("default_action") or "allow"),  # type: ignore[arg-type]
            rules=tuple(rules),
        )

    def merge(self, other: "PermissionPolicy") -> "PermissionPolicy":
        default_action = (
            self.default_action
            if _ACTION_RANK[self.default_action] >= _ACTION_RANK[other.default_action]
            else other.default_action
        )
        return PermissionPolicy(
            default_action=default_action,
            rules=(*self.rules, *other.rules),
        )


@dataclass(frozen=True)
class PolicyDecision:
    action: PermissionAction
    reason: str
    source: str
    matched_subject: str | None = None
    matched_pattern: str | None = None


class PolicyPermissionMiddleware(PermissionMiddleware):
    """Permission middleware that preserves hard denies and adds policy rules."""

    def __init__(
        self,
        mode: str,
        *,
        workspace=None,
        policy: PermissionPolicy | None = None,
        shared_state: dict[str, Any] | None = None,
    ):
        super().__init__(mode, workspace=workspace)
        self.policy = (policy or PermissionPolicy()).merge(baseline_policy_for_mode(mode))
        self.shared_state = shared_state if shared_state is not None else {}
        self.runtime_state = RuntimeSharedState(self.shared_state)
        validate_permission_policy(self.policy)

    async def __call__(self, tool: Tool, kwargs: dict[str, Any], next_fn: NextFn):
        hard_deny = self._path_policy_error(tool.name, kwargs)
        if hard_deny:
            self._emit_decision(tool, "deny", "hard_deny", hard_deny)
            return hard_deny
        mode_deny = self._mode_denial(tool, kwargs)
        if mode_deny:
            self._emit_decision(tool, "deny", "mode", mode_deny)
            return mode_deny
        decision = self.resolve(tool, kwargs)
        self._emit_decision(
            tool,
            decision.action,
            decision.source,
            decision.reason,
            matched_subject=decision.matched_subject,
            matched_pattern=decision.matched_pattern,
        )
        if decision.action == "deny":
            reason = f": {decision.reason}" if decision.reason else ""
            return f"Error: tool '{tool.name}' denied by permission policy{reason}"
        if decision.action == "ask":
            required_effects = tuple(sorted(tool_policy_effects(tool.get_call_policy(dict(kwargs)))))
            try:
                grant = await self._approval_grant(
                    tool,
                    kwargs,
                    decision,
                    required_effects=required_effects,
                )
            except PermissionRejectedError as exc:
                reason = f": {exc.message}" if exc.message else ""
                return ToolResult(
                    status="denied",
                    content=f"Denied: approval rejected for tool '{tool.name}'{reason}",
                    metadata={"approval_id": exc.request.id},
                )
            except PermissionInteractionUnavailableError as exc:
                return ToolResult(
                    status="denied",
                    content=(
                        f"Denied: approval required for tool '{tool.name}', "
                        "but no approval UI is available."
                    ),
                    metadata={"approval_id": exc.request.id, "approval_required": True},
                )
            return await self._run_with_approval_grant(tool, kwargs, next_fn, grant)
        return await next_fn(tool, kwargs)

    async def _run_with_approval_grant(self, tool: Tool, kwargs: dict[str, Any], next_fn: NextFn, grant):
        with self.runtime_state.scoped_execution_grant(grant):
            if tool.name == "run_command":
                with self.runtime_state.approved_command_bypass():
                    result = await next_fn(tool, kwargs)
            else:
                result = await next_fn(tool, kwargs)

        normalized = normalize_tool_result(result)
        if normalized.status == "ok":
            self._mark_approval_request_used(grant)
            self._emit_approval_resolved(tool, "approved", grant)
        elif normalized.status == "denied" and self._is_environment_approval_denied(normalized.content):
            self._mark_approval_request_pending(grant)
        return result

    def _is_environment_approval_denied(self, content: str) -> bool:
        message = (content or "").lower()
        return "approval required" in message or "environment approval gate" in message

    def _mark_approval_request_pending(self, grant):
        # A lower environment gate rejected an approved call. The new control
        # plane does not retry via persisted approvals; leave the typed denied
        # result visible to the caller.
        _ = grant

    def _mark_approval_request_used(self, grant):
        controller = self.runtime_state.invocation_context.permission_controller
        if controller is None:
            return
        request = getattr(controller, "get", lambda *_: None)(
            self.runtime_state.invocation_context.approval_context_key or "",
            grant.approval_id,
        )
        if request is None:
            return
        mark_used = getattr(controller, "mark_used", None)
        if callable(mark_used):
            mark_used(request)

    def resolve(self, tool: Tool, kwargs: Mapping[str, Any]) -> PolicyDecision:
        subjects = self._subjects(tool, kwargs)
        for rule in self.policy.rules:
            values = subjects.get(rule.subject, [])
            if any(fnmatch.fnmatchcase(value, rule.pattern) for value in values):
                return PolicyDecision(
                    action=rule.action,
                    reason=rule.reason,
                    source="rule",
                    matched_subject=rule.subject,
                    matched_pattern=rule.pattern,
                )
        return PolicyDecision(
            action=self.policy.default_action,
            reason="default policy",
            source="default",
        )

    def _mode_denial(self, tool: Tool, kwargs: Mapping[str, Any]) -> str | None:
        if tool.name in self.blocked_tools:
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode."
        capabilities = _policy_capabilities(tool, kwargs)
        if tool.name in self.config.capability_exempt_tools:
            capabilities -= self.decision.blocked_capabilities
        blocked = sorted(cap for cap in capabilities if self.decision.denies(cap))
        if blocked:
            caps = ", ".join(blocked)
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode ({caps})."
        return None

    def _subjects(self, tool: Tool, kwargs: Mapping[str, Any]) -> dict[str, list[str]]:
        subjects = {
            "tool": [tool.name],
            "capability": sorted(_policy_capabilities(tool, kwargs)),
        }
        paths = [path for _, path in self._path_arguments(tool.name, kwargs) if path]
        if paths:
            subjects["path"] = paths
        if tool.name == "run_command" and kwargs.get("command"):
            subjects["command"] = [str(kwargs["command"])]
        return subjects

    def _emit_decision(
        self,
        tool: Tool,
        action: str,
        source: str,
        reason: str,
        *,
        matched_subject: str | None = None,
        matched_pattern: str | None = None,
    ):
        trace_recorder = self.runtime_state.invocation_context.trace_recorder
        if trace_recorder is None:
            return
        trace_recorder.append("permission.decided", {
            "tool": tool.name,
            "action": action,
            "source": source,
            "reason": reason,
            "matched_subject": matched_subject,
            "matched_pattern": matched_pattern,
        })

    async def _approval_grant(
        self,
        tool: Tool,
        kwargs: Mapping[str, Any],
        decision: PolicyDecision,
        *,
        required_effects: tuple[str, ...],
    ) -> ExecutionGrant:
        context = self.runtime_state.invocation_context
        controller = context.permission_controller
        session_key = context.approval_context_key
        if controller is None or not session_key:
            raise PermissionInteractionUnavailableError(self._synthetic_request(tool, kwargs, decision))
        trace_recorder = context.trace_recorder
        run_id = getattr(trace_recorder, "run_id", None)
        return await controller.assert_allowed(
            session_key=str(session_key),
            tool_name=tool.name,
            arguments=kwargs,
            reason=decision.reason,
            run_id=run_id,
            matched_subject=decision.matched_subject,
            matched_pattern=decision.matched_pattern,
            effects=required_effects,
            origin_session_key=context.session_key,
            origin_run_id=run_id,
            event_sink=context.event_sink,
            trace_recorder=trace_recorder,
        )

    def _synthetic_request(self, tool: Tool, kwargs: Mapping[str, Any], decision: PolicyDecision):
        from app.approvals import ApprovalRequest, approval_arguments_hash, approval_request_id
        session_key = self.runtime_state.invocation_context.approval_context_key or ""
        arguments_hash = approval_arguments_hash(tool.name, kwargs)
        return ApprovalRequest(
            id=approval_request_id(session_key, tool.name, arguments_hash),
            session_key=session_key,
            tool_name=tool.name,
            arguments_hash=arguments_hash,
            arguments_preview=dict(kwargs),
            reason=decision.reason,
            matched_subject=decision.matched_subject,
            matched_pattern=decision.matched_pattern,
        )

    def _emit_approval_resolved(self, tool: Tool, status: str, request=None):
        trace_recorder = self.runtime_state.invocation_context.trace_recorder
        if trace_recorder is None:
            return
        trace_recorder.append("approval.resolved", {
            "tool": tool.name,
            "status": status,
            "approval_id": getattr(request, "approval_id", None) or getattr(request, "id", None),
            "scope": getattr(request, "scope", None),
            "arguments_hash": getattr(request, "arguments_hash", None),
            "granted_effects": list(getattr(request, "effects", ()) or getattr(request, "granted_effects", ()) or ()),
            "run_id": getattr(request, "run_id", None),
        })


def baseline_policy_for_mode(mode: str) -> PermissionPolicy:
    if mode not in VALID_PERMISSION_MODES:
        supported = ", ".join(sorted(VALID_PERMISSION_MODES))
        raise ValueError(f"Unknown permission mode '{mode}'. Expected one of: {supported}.")
    config = PERMISSION_MODES[mode]
    rules = [
        PermissionRule(subject="tool", pattern=tool_name, action="deny", reason=f"{mode} blocks tool")
        for tool_name in sorted(config.blocked_tools)
    ]
    rules.extend(
        PermissionRule(subject="capability", pattern=capability, action="deny", reason=f"{mode} blocks capability")
        for capability in sorted(config.blocked_capabilities)
    )
    if mode in {"execute", "full"}:
        rules.extend([
            PermissionRule(
                subject="capability",
                pattern=NETWORK_EFFECT,
                action="ask",
                reason="network access requires approval",
            ),
            PermissionRule(
                subject="capability",
                pattern=IMAGE_MANAGEMENT_EFFECT,
                action="ask",
                reason="Docker image build/pull requires approval",
            ),
            PermissionRule(
                subject="capability",
                pattern=SHELL_SESSION_EFFECT,
                action="ask",
                reason="shell session execution requires approval",
            ),
        ])
        rules.extend(_approval_command_rules())
    return PermissionPolicy(default_action="allow", rules=tuple(rules))


def _approval_command_rules() -> list[PermissionRule]:
    reason = "command requires approval"
    return [
        PermissionRule(subject="command", pattern=pattern, action="ask", reason=reason)
        for pattern in (
            "npm install*",
            "npm i*",
            "npm add*",
            "npm view*",
            "pnpm install*",
            "pnpm add*",
            "pnpm view*",
            "yarn install*",
            "yarn add*",
            "yarn view*",
            "bun install*",
            "bun add*",
            "bun view*",
            "node -e*",
        )
    ]


def validate_permission_policy(policy: PermissionPolicy):
    if policy.default_action not in {"allow", "ask", "deny"}:
        raise ValueError(f"Invalid default policy action: {policy.default_action}")
    for rule in policy.rules:
        if rule.subject not in VALID_POLICY_SUBJECTS:
            supported = ", ".join(sorted(VALID_POLICY_SUBJECTS))
            raise ValueError(f"Invalid policy subject '{rule.subject}'. Expected one of: {supported}.")
        if rule.action not in {"allow", "ask", "deny"}:
            raise ValueError(f"Invalid policy action: {rule.action}")


def load_permission_policy(
    workspace: WorkspaceContext | None = None,
    *,
    explicit_paths: tuple[str, ...] = (),
    include_user: bool = True,
) -> PermissionPolicy:
    """Load user and workspace permission policy files.

    Files use the same shape accepted by ``PermissionPolicy.from_dict``. Rule
    order is user/explicit first, then workspace, so trusted user rules can
    override project rules. Default actions are merged conservatively.
    """
    policy = PermissionPolicy()
    for path in _permission_policy_paths(
        workspace,
        explicit_paths=explicit_paths,
        include_user=include_user,
    ):
        if not os.path.exists(path):
            continue
        loaded = _load_permission_policy_file(path)
        validate_permission_policy(loaded)
        policy = policy.merge(loaded)
    return policy


def _permission_policy_paths(
    workspace: WorkspaceContext | None,
    *,
    explicit_paths: tuple[str, ...] = (),
    include_user: bool = True,
) -> list[str]:
    paths: list[str] = []
    for path in explicit_paths:
        if path:
            paths.append(_normalize_policy_path(path))

    env_path = os.getenv("SMOLCLAW_PERMISSION_POLICY")
    if env_path:
        paths.append(_normalize_policy_path(env_path))

    if include_user:
        paths.extend([
            _normalize_policy_path("~/.config/smolclaw/permissions.yaml"),
            _normalize_policy_path("~/.smolclaw/permissions.yaml"),
        ])

    if workspace is not None:
        roots = [workspace.state_root_dir]
        if workspace.root_dir != workspace.state_root_dir:
            roots.append(workspace.root_dir)
        for root in roots:
            paths.extend([
                os.path.join(root, ".smolclaw", "permissions.yaml"),
                os.path.join(root, ".smolclaw", "permissions.yml"),
                os.path.join(root, ".smolclaw", "permissions.json"),
            ])

    deduped = []
    seen = set()
    for path in paths:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        deduped.append(real)
    return deduped


def _normalize_policy_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _load_permission_policy_file(path: str) -> PermissionPolicy:
    with open(path, encoding="utf-8") as handle:
        if path.endswith(".json"):
            data = json.load(handle) or {}
        else:
            data = yaml.safe_load(handle) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"Permission policy file must contain a mapping: {path}")
    return PermissionPolicy.from_dict(data)
