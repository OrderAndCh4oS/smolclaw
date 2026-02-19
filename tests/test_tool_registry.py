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
