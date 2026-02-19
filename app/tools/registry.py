from typing import Any, Dict, List

from app.tools.base import Tool


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get_definitions(self) -> List[dict]:
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        try:
            return await self._tools[name].execute(**arguments)
        except Exception as e:
            return f"Error: {e}"

    def filter_by_names(self, names: List[str]) -> "ToolRegistry":
        filtered = ToolRegistry()
        for name in names:
            if name in self._tools:
                filtered._tools[name] = self._tools[name]
        return filtered
