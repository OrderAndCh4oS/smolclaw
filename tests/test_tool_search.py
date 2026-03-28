"""Tests for ToolSearchTool and deferred tool discovery."""

import pytest

from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from app.tools.tool_search import ToolSearchTool


class DeferredTool(Tool):
    def __init__(self, tool_name="deferred_tool", desc="A deferred tool"):
        self._name = tool_name
        self._desc = desc

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._desc

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}

    @property
    def deferred(self) -> bool:
        return True

    async def execute(self, **kwargs) -> str:
        return f"deferred result: {kwargs.get('x', '')}"


class NormalTool(Tool):
    @property
    def name(self) -> str:
        return "normal_tool"

    @property
    def description(self) -> str:
        return "A normal tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "normal"


class TestToolSearchReturnsMatches:
    @pytest.mark.asyncio
    async def test_search_finds_by_name(self):
        registry = ToolRegistry()
        registry.register(DeferredTool(tool_name="special_memory", desc="memory operations"))
        registry.register(NormalTool())
        search = ToolSearchTool(registry)

        result = await search.execute(query="special")
        assert "special_memory" in result
        assert "Found 1 tool" in result

    @pytest.mark.asyncio
    async def test_search_finds_by_description(self):
        registry = ToolRegistry()
        registry.register(DeferredTool(tool_name="hidden", desc="advanced graph operations"))
        search = ToolSearchTool(registry)

        result = await search.execute(query="graph")
        assert "hidden" in result

    @pytest.mark.asyncio
    async def test_search_no_match(self):
        registry = ToolRegistry()
        registry.register(DeferredTool())
        search = ToolSearchTool(registry)

        result = await search.execute(query="nonexistent_xyz")
        assert "No additional tools found" in result

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self):
        registry = ToolRegistry()
        registry.register(DeferredTool(tool_name="MyTool", desc="Something"))
        search = ToolSearchTool(registry)

        result = await search.execute(query="mytool")
        assert "MyTool" in result


class TestToolSearchExposesTools:
    @pytest.mark.asyncio
    async def test_found_tool_gets_exposed(self):
        registry = ToolRegistry()
        registry.register(DeferredTool(tool_name="hidden_tool", desc="hidden"))
        registry.register(NormalTool())
        search = ToolSearchTool(registry)

        # Before search: deferred tool excluded
        defs = registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "hidden_tool" not in names

        # Search and expose
        await search.execute(query="hidden")

        # After search: deferred tool now visible
        defs = registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "hidden_tool" in names

    @pytest.mark.asyncio
    async def test_search_does_not_expose_non_deferred(self):
        registry = ToolRegistry()
        registry.register(NormalTool())
        search = ToolSearchTool(registry)

        # Normal tools are not returned by search_tools
        result = await search.execute(query="normal")
        assert "No additional tools found" in result


class TestToolSearchSchema:
    def test_tool_search_is_not_deferred(self):
        registry = ToolRegistry()
        search = ToolSearchTool(registry)
        assert not search.deferred

    def test_tool_search_has_examples(self):
        registry = ToolRegistry()
        search = ToolSearchTool(registry)
        assert len(search.examples) >= 1
