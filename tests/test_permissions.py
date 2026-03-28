"""Tests for permission modes and PermissionMiddleware."""

import pytest

from app.tools.base import Tool
from app.tools.middleware import MiddlewareChain
from app.tools.permissions import PERMISSION_BLOCKED, PermissionMiddleware


class FakeTool(Tool):
    def __init__(self, tool_name="fake"):
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Fake {self._name}"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return f"{self._name} executed"


class TestFullMode:
    @pytest.mark.asyncio
    async def test_allows_write_file(self):
        mw = PermissionMiddleware("full")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("write_file"), {})
        assert result == "write_file executed"

    @pytest.mark.asyncio
    async def test_allows_exec(self):
        mw = PermissionMiddleware("full")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("exec"), {})
        assert result == "exec executed"

    @pytest.mark.asyncio
    async def test_allows_sequential_pipeline(self):
        mw = PermissionMiddleware("full")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("sequential_pipeline"), {})
        assert result == "sequential_pipeline executed"


class TestPlanMode:
    @pytest.mark.asyncio
    async def test_blocks_write_file(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("write_file"), {})
        assert result.startswith("Error:")
        assert "not permitted" in result
        assert "'plan'" in result

    @pytest.mark.asyncio
    async def test_blocks_edit_file(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("edit_file"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_exec(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("exec"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_memory_store(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("memory_store"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_memory_relate(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("memory_relate"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_allows_read_file(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("read_file"), {})
        assert result == "read_file executed"

    @pytest.mark.asyncio
    async def test_allows_memory_search(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("memory_search"), {})
        assert result == "memory_search executed"

    @pytest.mark.asyncio
    async def test_allows_web_search(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("web_search"), {})
        assert result == "web_search executed"

    @pytest.mark.asyncio
    async def test_blocks_spawn_agent(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("spawn_agent"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_sequential_pipeline(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("sequential_pipeline"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_fanout_pipeline(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("fanout_pipeline"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_route(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("route"), {})
        assert result.startswith("Error:")


class TestExecuteMode:
    @pytest.mark.asyncio
    async def test_blocks_sequential_pipeline(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("sequential_pipeline"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_fanout_pipeline(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("fanout_pipeline"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_route(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("route"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_allows_exec(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("exec"), {})
        assert result == "exec executed"

    @pytest.mark.asyncio
    async def test_allows_write_file(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("write_file"), {})
        assert result == "write_file executed"


class TestUnknownMode:
    @pytest.mark.asyncio
    async def test_unknown_mode_allows_all(self):
        mw = PermissionMiddleware("unknown_mode")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("exec"), {})
        assert result == "exec executed"


class TestPermissionBlockedMapping:
    def test_full_blocks_nothing(self):
        assert PERMISSION_BLOCKED["full"] == set()

    def test_plan_blocks_expected_tools(self):
        expected = {
            "write_file",
            "edit_file",
            "exec",
            "memory_store",
            "memory_relate",
            "sequential_pipeline",
            "fanout_pipeline",
            "route",
            "spawn_agent",
        }
        assert PERMISSION_BLOCKED["plan"] == expected

    def test_execute_blocks_expected_tools(self):
        expected = {"sequential_pipeline", "fanout_pipeline", "route", "spawn_agent"}
        assert PERMISSION_BLOCKED["execute"] == expected
