import pytest

from app.tools.base import Tool
from app.tools.registry import ToolRegistry


class DummyTool(Tool):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy tool for testing"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Input text"},
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs) -> str:
        return f"echo: {kwargs['text']}"


class ErrorTool(Tool):
    @property
    def name(self) -> str:
        return "error_tool"

    @property
    def description(self) -> str:
        return "A tool that raises"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        raise RuntimeError("boom")


class TestToolRegistry:
    def test_register_and_get_definitions(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        defs = registry.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "dummy"

    @pytest.mark.asyncio
    async def test_execute_returns_result(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        result = await registry.execute("dummy", {"text": "hello"})
        assert result == "echo: hello"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self):
        registry = ToolRegistry()
        result = await registry.execute("nonexistent", {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_execute_bad_params_returns_error(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        result = await registry.execute("dummy", {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_execute_tool_exception_returns_error(self):
        registry = ToolRegistry()
        registry.register(ErrorTool())
        result = await registry.execute("error_tool", {})
        assert result.startswith("Error:")
        assert "boom" in result

    def test_to_schema_format(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        defs = registry.get_definitions()
        schema = defs[0]
        assert schema["type"] == "function"
        assert "function" in schema
        assert schema["function"]["name"] == "dummy"
        assert schema["function"]["description"] == "A dummy tool for testing"
        assert "parameters" in schema["function"]


class AnotherTool(Tool):
    @property
    def name(self) -> str:
        return "another"

    @property
    def description(self) -> str:
        return "Another tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "another result"


class ThirdTool(Tool):
    @property
    def name(self) -> str:
        return "third"

    @property
    def description(self) -> str:
        return "Third tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "third result"


class ToolWithExamples(Tool):
    @property
    def name(self) -> str:
        return "example_tool"

    @property
    def description(self) -> str:
        return "A tool with examples"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    @property
    def examples(self) -> list[dict]:
        return [{"description": "Echo hello", "arguments": {"text": "hello"}}]

    async def execute(self, **kwargs) -> str:
        return f"echo: {kwargs['text']}"


class TestToSchemaExamples:
    def test_to_schema_includes_examples(self):
        tool = ToolWithExamples()
        schema = tool.to_schema()
        assert "examples" in schema["function"]
        assert len(schema["function"]["examples"]) == 1
        assert schema["function"]["examples"][0]["arguments"]["text"] == "hello"

    def test_to_schema_omits_examples_when_empty(self):
        tool = DummyTool()
        schema = tool.to_schema()
        assert "examples" not in schema["function"]


class DeferredDummyTool(Tool):
    @property
    def name(self) -> str:
        return "deferred_dummy"

    @property
    def description(self) -> str:
        return "A deferred tool for testing"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    @property
    def deferred(self) -> bool:
        return True

    async def execute(self, **kwargs) -> str:
        return "deferred result"


class SearchTool(Tool):
    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def description(self) -> str:
        return "Search for additional tools"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> str:
        return "search"


class TestDeferredTools:
    def test_get_definitions_excludes_deferred(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(DeferredDummyTool())
        defs = registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "dummy" in names
        assert "deferred_dummy" not in names

    def test_search_tools_finds_by_name(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        matches = registry.search_tools("deferred")
        assert len(matches) == 1
        assert matches[0]["function"]["name"] == "deferred_dummy"

    def test_search_tools_finds_by_description(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        matches = registry.search_tools("testing")
        assert len(matches) == 1

    def test_search_tools_no_match(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        matches = registry.search_tools("nonexistent")
        assert len(matches) == 0

    def test_search_tools_ignores_already_exposed(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        registry.expose_tool("deferred_dummy")
        matches = registry.search_tools("deferred")
        assert len(matches) == 0

    def test_expose_tool_makes_deferred_visible(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        assert len(registry.get_definitions()) == 0
        registry.expose_tool("deferred_dummy")
        defs = registry.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "deferred_dummy"

    def test_filter_by_names_carries_exposed(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(DeferredDummyTool())
        registry.expose_tool("deferred_dummy")
        filtered = registry.filter_by_names(["dummy", "deferred_dummy"])
        defs = filtered.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "deferred_dummy" in names

    @pytest.mark.asyncio
    async def test_deferred_tool_requires_exposure_to_execute(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        result = await registry.execute("deferred_dummy", {})
        assert result.startswith("Error:")
        assert "tool_search" in result

    @pytest.mark.asyncio
    async def test_exposed_deferred_tool_executes(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        registry.expose_tool("deferred_dummy")
        result = await registry.execute("deferred_dummy", {})
        assert result == "deferred result"


class TestProjectForAgent:
    def test_preserves_hidden_deferred_tools_for_runtime_discovery(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(DeferredDummyTool())
        registry.register(SearchTool())

        projected = registry.project_for_agent(["tool_search"])

        defs = projected.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert names == ["tool_search"]
        matches = projected.search_tools("deferred")
        assert len(matches) == 1
        assert matches[0]["function"]["name"] == "deferred_dummy"

    def test_exposes_listed_deferred_tools_immediately(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        registry.register(SearchTool())

        projected = registry.project_for_agent(["deferred_dummy"])

        defs = projected.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert names == ["deferred_dummy"]

    @pytest.mark.asyncio
    async def test_hidden_deferred_tools_are_not_invocable_until_exposed(self):
        registry = ToolRegistry()
        registry.register(DeferredDummyTool())
        registry.register(SearchTool())

        projected = registry.project_for_agent(["tool_search"])

        result = await projected.execute("deferred_dummy", {})
        assert result.startswith("Error:")
        assert "tool_search" in result

    @pytest.mark.asyncio
    async def test_excludes_unlisted_immediate_tools(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(DeferredDummyTool())
        registry.register(SearchTool())

        projected = registry.project_for_agent(["tool_search"])

        defs = projected.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "dummy" not in names
        result = await projected.execute("dummy", {"text": "hello"})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_excludes_tools_from_disabled_modules(self):
        registry = ToolRegistry()
        registry.register(DummyTool(), module_name="transport.direct")
        registry.register(DeferredDummyTool(), module_name="memory")
        registry.register(SearchTool(), module_name="tool_discovery")

        projected = registry.project_for_agent(
            ["dummy", "tool_search"],
            allowed_modules=["transport.direct"],
        )

        defs = projected.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert names == ["dummy"]
        assert projected.search_tools("deferred") == []

        result = await projected.execute("deferred_dummy", {})
        assert result.startswith("Error:")
        assert "unknown tool" in result


class TestFilterByNames:
    def test_filter_by_names_returns_subset(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())
        registry.register(ThirdTool())
        filtered = registry.filter_by_names(["dummy", "third"])
        defs = filtered.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert sorted(names) == ["dummy", "third"]

    def test_filter_by_names_unknown_name_ignored(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        filtered = registry.filter_by_names(["dummy", "nonexistent"])
        defs = filtered.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "dummy"

    def test_filter_by_names_empty_list(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        filtered = registry.filter_by_names([])
        assert filtered.get_definitions() == []

    def test_filter_by_names_does_not_mutate_original(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())
        registry.filter_by_names(["dummy"])
        assert len(registry.get_definitions()) == 2
