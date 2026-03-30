from typing import Any, Dict, List, Set

from app.tools.base import (
    Tool,
    ToolOutcome,
    ToolResult,
    ToolRuntimeContext,
    normalize_tool_result,
    render_tool_result,
)
from app.tools.middleware import MiddlewareChain, MiddlewareFn


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._middleware = MiddlewareChain()
        self._per_tool_middleware: Dict[str, MiddlewareChain] = {}
        self._exposed: Set[str] = set()

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def values(self) -> List[Tool]:
        return list(self._tools.values())

    def has_deferred_tools(self) -> bool:
        return any(tool.deferred for tool in self._tools.values())

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

    def has_hidden_deferred_tools(self) -> bool:
        return any(
            tool.deferred and name not in self._exposed
            for name, tool in self._tools.items()
        )

    async def invoke(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        if name not in self._tools:
            return ToolResult(status="error", content=f"Error: unknown tool '{name}'")
        tool = self._tools[name]
        if tool.deferred and name not in self._exposed:
            return ToolResult(
                status="error",
                content=(
                    f"Error: tool '{name}' is not currently exposed. "
                    "Use 'tool_search' to discover and expose it first."
                ),
            )
        try:
            # Per-tool middleware runs inside global middleware
            per_tool = self._per_tool_middleware.get(name)
            if per_tool and per_tool._middlewares:
                chain = MiddlewareChain(
                    self._middleware._middlewares + per_tool._middlewares,
                )
            else:
                chain = self._middleware
            result: ToolOutcome = await chain.run(tool, arguments)
            return normalize_tool_result(result)
        except Exception as e:
            return ToolResult(status="error", content=f"Error: {e}")

    async def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        return render_tool_result(await self.invoke(name, arguments))

    def filter_by_names(
        self,
        names: List[str],
        runtime_ctx: ToolRuntimeContext | None = None,
    ) -> "ToolRegistry":
        filtered = ToolRegistry()
        if runtime_ctx is not None:
            runtime_ctx.registry = filtered
        for name in names:
            if name in self._tools:
                tool = self._tools[name]
                filtered._tools[name] = tool.bind(runtime_ctx) if runtime_ctx else tool
        # Inherit middleware and exposed set from parent registry
        filtered._middleware = MiddlewareChain(list(self._middleware._middlewares))
        filtered._exposed = set(self._exposed)
        for tool_name, chain in self._per_tool_middleware.items():
            if tool_name in filtered._tools:
                filtered._per_tool_middleware[tool_name] = MiddlewareChain(
                    list(chain._middlewares),
                )
        return filtered

    def project_for_agent(
        self,
        enabled_names: List[str],
        runtime_ctx: ToolRuntimeContext | None = None,
    ) -> "ToolRegistry":
        projected = ToolRegistry()
        if runtime_ctx is not None:
            runtime_ctx.registry = projected

        enabled = set(enabled_names)

        for name, tool in self._tools.items():
            if name == "tool_search":
                continue
            if tool.deferred or name in enabled:
                projected._tools[name] = tool.bind(runtime_ctx) if runtime_ctx else tool

        projected._exposed = {
            name for name in self._exposed if name in projected._tools
        }
        projected._exposed.update(
            name
            for name in enabled
            if name in projected._tools and projected._tools[name].deferred
        )

        if projected.has_hidden_deferred_tools() and "tool_search" in self._tools:
            tool_search = self._tools["tool_search"]
            projected._tools["tool_search"] = (
                tool_search.bind(runtime_ctx) if runtime_ctx else tool_search
            )

        projected._middleware = MiddlewareChain(list(self._middleware._middlewares))
        for tool_name, chain in self._per_tool_middleware.items():
            if tool_name in projected._tools:
                projected._per_tool_middleware[tool_name] = MiddlewareChain(
                    list(chain._middlewares),
                )

        return projected
