"""Permission modes for restricting tool access per agent."""

from dataclasses import dataclass
from typing import Any, Dict, Final, Mapping, Set

from app.tools.base import Tool
from app.tools.middleware import NextFn

MUTATES_STATE: Final[str] = "mutates_state"
DELEGATES: Final[str] = "delegates"
COMMAND_EXECUTION: Final[str] = "command_execution"

DIRECT_MUTATION_TOOLS: Final[Set[str]] = {
    "write_file",
    "edit_file",
    "apply_patch",
    "exec",
    "memory_store",
    "memory_relate",
}

DELEGATION_TOOLS: Final[Set[str]] = {
    "sequential_pipeline",
    "fanout_pipeline",
    "route",
    "spawn_agent",
}

@dataclass(frozen=True)
class PermissionModeConfig:
    blocked_tools: frozenset[str]
    blocked_capabilities: frozenset[str]
    capability_exempt_tools: frozenset[str] = frozenset()


PERMISSION_MODES: Final[Dict[str, PermissionModeConfig]] = {
    "full": PermissionModeConfig(
        blocked_tools=frozenset(),
        blocked_capabilities=frozenset(),
    ),
    "plan": PermissionModeConfig(
        blocked_tools=frozenset(DIRECT_MUTATION_TOOLS | DELEGATION_TOOLS),
        blocked_capabilities=frozenset({MUTATES_STATE, DELEGATES, COMMAND_EXECUTION}),
    ),
    "execute": PermissionModeConfig(
        blocked_tools=frozenset(DELEGATION_TOOLS),
        blocked_capabilities=frozenset({DELEGATES}),
    ),
    "research": PermissionModeConfig(
        blocked_tools=frozenset({
            "apply_patch",
            "write_file",
            "edit_file",
            "exec",
            "memory_relate",
            "sequential_pipeline",
            "fanout_pipeline",
            "route",
            "spawn_agent",
        }),
        blocked_capabilities=frozenset({MUTATES_STATE, DELEGATES, COMMAND_EXECUTION}),
        capability_exempt_tools=frozenset({"memory_store"}),
    ),
    "delegate_only": PermissionModeConfig(
        blocked_tools=frozenset(DIRECT_MUTATION_TOOLS),
        blocked_capabilities=frozenset({MUTATES_STATE}),
    ),
}

PERMISSION_BLOCKED: Dict[str, Set[str]] = {
    name: set(config.blocked_tools) for name, config in PERMISSION_MODES.items()
}

PERMISSION_BLOCKED_CAPABILITIES: Dict[str, Set[str]] = {
    name: set(config.blocked_capabilities) for name, config in PERMISSION_MODES.items()
}
VALID_PERMISSION_MODES: Final[frozenset[str]] = frozenset(PERMISSION_MODES)


@dataclass(frozen=True)
class PermissionDecision:
    blocked_capabilities: frozenset[str]

    def denies(self, capability: str) -> bool:
        return capability in self.blocked_capabilities


def _policy_capabilities(tool: Tool, kwargs: Mapping[str, Any]) -> set[str]:
    policy = tool.get_call_policy(dict(kwargs))
    capabilities = set(policy.tags)
    if policy.mutates_state:
        capabilities.add(MUTATES_STATE)
    if policy.delegates:
        capabilities.add(DELEGATES)
    return capabilities


class PermissionMiddleware:
    """Middleware that blocks tool calls not permitted by the agent's permission mode."""

    def __init__(self, mode: str):
        if mode not in VALID_PERMISSION_MODES:
            supported = ", ".join(sorted(VALID_PERMISSION_MODES))
            raise ValueError(
                f"Unknown permission mode '{mode}'. Expected one of: {supported}."
            )
        self.mode = mode
        self.config = PERMISSION_MODES[mode]
        self.decision = PermissionDecision(
            blocked_capabilities=self.config.blocked_capabilities,
        )
        self.blocked_tools = set(self.config.blocked_tools)

    async def __call__(self, tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn):
        if tool.name in self.blocked_tools:
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode."
        capabilities = _policy_capabilities(tool, kwargs)
        if tool.name in self.config.capability_exempt_tools:
            capabilities -= self.decision.blocked_capabilities
        blocked = sorted(cap for cap in capabilities if self.decision.denies(cap))
        if blocked:
            caps = ", ".join(blocked)
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode ({caps})."
        return await next_fn(tool, kwargs)
