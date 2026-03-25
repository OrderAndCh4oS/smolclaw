from typing import Any, Dict, List

from app.tools.base import Tool
from app.tools.middleware import MiddlewareChain, MiddlewareFn


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._middleware = MiddlewareChain()
        self._per_tool_middleware: Dict[str, MiddlewareChain] = {}

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
        return [tool.to_schema() for tool in self._tools.values()]

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
        # Inherit middleware from parent registry
        filtered._middleware = MiddlewareChain(list(self._middleware._middlewares))
        for tool_name, chain in self._per_tool_middleware.items():
            if tool_name in filtered._tools:
                filtered._per_tool_middleware[tool_name] = MiddlewareChain(
                    list(chain._middlewares),
                )
        return filtered
