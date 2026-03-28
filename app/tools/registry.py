from typing import Any, Dict, List, Set

from app.tools.base import Tool
from app.tools.middleware import MiddlewareChain, MiddlewareFn


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._middleware = MiddlewareChain()
        self._per_tool_middleware: Dict[str, MiddlewareChain] = {}
        self._exposed: Set[str] = set()

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def use(self, mw: MiddlewareFn):
        """Register global middleware applied to all tool executions."""
        self._middleware.use(mw)

    def use_for(self, tool_name: str, mw: MiddlewareFn):
        """Register middleware applied only to a specific tool."""
        if tool_name not in self._per_tool_middleware:
            self._per_tool_middleware[tool_name] = MiddlewareChain()
        self._per_tool_middleware[tool_name].use(mw)

    def get_definitions(self) -> List[dict]:
        """Return schemas for non-deferred tools (plus any dynamically exposed ones)."""
        return [
            tool.to_schema()
            for tool in self._tools.values()
            if not tool.deferred or tool.name in self._exposed
        ]

    def search_tools(self, query: str) -> List[dict]:
        """Search deferred tools by case-insensitive substring match on name and description."""
        query_lower = query.lower()
        matches = []
        for tool in self._tools.values():
            if not tool.deferred or tool.name in self._exposed:
                continue
            if query_lower in tool.name.lower() or query_lower in tool.description.lower():
                matches.append(tool.to_schema())
        return matches

    def expose_tool(self, name: str):
        """Mark a deferred tool as visible in get_definitions()."""
        if name in self._tools:
            self._exposed.add(name)

    async def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        tool = self._tools[name]
        try:
            # Per-tool middleware runs inside global middleware
            per_tool = self._per_tool_middleware.get(name)
            if per_tool and per_tool._middlewares:
                chain = MiddlewareChain(
                    self._middleware._middlewares + per_tool._middlewares,
                )
            else:
                chain = self._middleware
            return await chain.run(tool, arguments)
        except Exception as e:
            return f"Error: {e}"

    def filter_by_names(self, names: List[str]) -> "ToolRegistry":
        filtered = ToolRegistry()
        for name in names:
            if name in self._tools:
                filtered._tools[name] = self._tools[name]
        # Inherit middleware and exposed set from parent registry
        filtered._middleware = MiddlewareChain(list(self._middleware._middlewares))
        filtered._exposed = set(self._exposed)
        for tool_name, chain in self._per_tool_middleware.items():
            if tool_name in filtered._tools:
                filtered._per_tool_middleware[tool_name] = MiddlewareChain(
                    list(chain._middlewares),
                )
        return filtered
