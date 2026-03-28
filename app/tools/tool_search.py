"""Meta-tool for discovering deferred tools at runtime."""

import json

from app.tools.base import Tool, ToolRuntimeContext


class ToolSearchTool(Tool):
    """Searches deferred tools by keyword, exposes matches so the LLM can use them."""

    def __init__(self, registry):
        self._registry = registry

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        if runtime_ctx.registry is None:
            return self
        return ToolSearchTool(runtime_ctx.registry)

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def description(self) -> str:
        return (
            "Search for additional tools by keyword. "
            "Returns matching tool schemas that you can then use in subsequent calls."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search tool names and descriptions",
                },
            },
            "required": ["query"],
        }

    @property
    def examples(self) -> list[dict]:
        return [
            {"description": "Find memory-related tools", "arguments": {"query": "memory"}},
            {"description": "Search for file tools", "arguments": {"query": "file"}},
        ]

    async def execute(self, **kwargs) -> str:
        query = kwargs["query"]
        matches = self._registry.search_tools(query)
        if not matches:
            return f"No additional tools found matching '{query}'."

        # Expose matched tools so they appear in future get_definitions() calls
        for schema in matches:
            tool_name = schema["function"]["name"]
            self._registry.expose_tool(tool_name)

        lines = [f"Found {len(matches)} tool(s) matching '{query}':\n"]
        for schema in matches:
            func = schema["function"]
            lines.append(f"**{func['name']}**: {func['description']}")
            props = func.get("parameters", {}).get("properties", {})
            if props:
                param_strs = []
                for pname, pdef in props.items():
                    param_strs.append(f"  - {pname}: {pdef.get('description', pdef.get('type', ''))}")
                lines.append("  Parameters:")
                lines.extend(param_strs)
            lines.append("")

        return "\n".join(lines)
