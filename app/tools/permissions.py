"""Permission modes for restricting tool access per agent."""

from typing import Any, Dict, Set

from app.tools.base import Tool
from app.tools.middleware import NextFn

PERMISSION_BLOCKED: Dict[str, Set[str]] = {
    "full": set(),
    "plan": {"write_file", "edit_file", "exec", "memory_store", "memory_relate"},
    "execute": {"sequential_pipeline", "fanout_pipeline", "route", "spawn_agent"},
}


class PermissionMiddleware:
    """Middleware that blocks tool calls not permitted by the agent's permission mode."""

    def __init__(self, mode: str):
        self.mode = mode
        self.blocked = PERMISSION_BLOCKED.get(mode, set())

    async def __call__(self, tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn) -> str:
        if tool.name in self.blocked:
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode."
        return await next_fn(tool, kwargs)
