"""Permission modes for restricting tool access per agent."""

from dataclasses import dataclass
from typing import Any, Dict, Final, Mapping, Set

from app.tools.base import Tool
from app.tools.middleware import NextFn

MUTATES_STATE: Final[str] = "mutates_state"
DELEGATES: Final[str] = "delegates"

DIRECT_MUTATION_TOOLS: Final[Set[str]] = {
    "write_file",
    "edit_file",
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

PERMISSION_BLOCKED: Dict[str, Set[str]] = {
    "full": set(),
    "plan": DIRECT_MUTATION_TOOLS | DELEGATION_TOOLS,
    "execute": set(DELEGATION_TOOLS),
}

PERMISSION_BLOCKED_CAPABILITIES: Dict[str, Set[str]] = {
    "full": set(),
    "plan": {MUTATES_STATE, DELEGATES},
    "execute": {DELEGATES},
}


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
        self.mode = mode
        self.decision = PermissionDecision(
            blocked_capabilities=frozenset(PERMISSION_BLOCKED_CAPABILITIES.get(mode, set())),
        )
        self.blocked_tools = PERMISSION_BLOCKED.get(mode, set())

    async def __call__(self, tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn):
        if tool.name in self.blocked_tools:
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode."
        capabilities = _policy_capabilities(tool, kwargs)
        blocked = sorted(cap for cap in capabilities if self.decision.denies(cap))
        if blocked:
            caps = ", ".join(blocked)
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode ({caps})."
        return await next_fn(tool, kwargs)
