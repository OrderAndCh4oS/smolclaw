import re
from typing import Any, Dict, List, Optional, Set

from app import diagnostics
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
        self._tool_capabilities: Dict[str, Optional[str]] = {}
        self._middleware = MiddlewareChain()
        self._per_tool_middleware: Dict[str, MiddlewareChain] = {}
        self._exposed: Set[str] = set()

    def register(self, tool: Tool, capability_name: str | None = None):
        self._tools[tool.name] = tool
        self._tool_capabilities[tool.name] = capability_name

    def values(self) -> List[Tool]:
        return list(self._tools.values())

    def tool_names(self) -> Set[str]:
        return set(self._tools)

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
        """Search deferred tools with deterministic lexical ranking."""
        query_lower = query.lower().strip()
        terms = _search_terms(query_lower)
        if not terms:
            return []
        matches = []
        for tool in self._tools.values():
            if not tool.deferred or tool.name in self._exposed:
                continue
            score = _tool_search_score(tool, query_lower, terms)
            if score > 0:
                matches.append((score, tool.name, tool.to_schema()))
        return [schema for _score, _name, schema in sorted(matches, key=lambda item: (-item[0], item[1]))]

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
            incident_id = diagnostics.record_exception(
                e,
                boundary="tool_registry",
                tool=name,
                arguments=arguments,
            )
            return ToolResult(
                status="error",
                content=diagnostics.user_error_message(incident_id, str(e)),
            )

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
                filtered._tool_capabilities[name] = self._tool_capabilities.get(name)
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
        allowed_capabilities: List[str] | None = None,
    ) -> "ToolRegistry":
        projected = ToolRegistry()
        if runtime_ctx is not None:
            runtime_ctx.registry = projected

        enabled = set(enabled_names)
        allowed = set(allowed_capabilities) if allowed_capabilities is not None else None

        for name, tool in self._tools.items():
            if name == "tool_search":
                continue
            tool_capability = self._tool_capabilities.get(name)
            if allowed is not None and tool_capability is not None and tool_capability not in allowed:
                continue
            if tool.deferred or name in enabled:
                projected._tools[name] = tool.bind(runtime_ctx) if runtime_ctx else tool
                projected._tool_capabilities[name] = tool_capability

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
            projected._tool_capabilities["tool_search"] = self._tool_capabilities.get("tool_search")

        projected._middleware = MiddlewareChain(list(self._middleware._middlewares))
        for tool_name, chain in self._per_tool_middleware.items():
            if tool_name in projected._tools:
                projected._per_tool_middleware[tool_name] = MiddlewareChain(
                    list(chain._middlewares),
                )

        return projected


def _search_terms(query: str) -> list[str]:
    return [term for term in re.split(r"[^a-z0-9_]+", query.lower()) if term]


def _tool_tokens(value: str) -> set[str]:
    return set(_search_terms(value.replace("_", " ")))


def _tool_search_score(tool: Tool, query: str, terms: list[str]) -> int:
    name = tool.name.lower()
    description = tool.description.lower()
    name_tokens = _tool_tokens(name)
    description_tokens = _tool_tokens(description)
    score = 0
    if query == name:
        score += 200
    if name.startswith(query):
        score += 100
    if query in name:
        score += 60
    if query in description:
        score += 15
    for term in terms:
        if term in name_tokens:
            score += 35
        elif term in name:
            score += 20
        if term in description_tokens:
            score += 10
        elif term in description:
            score += 4
    return score
