"""Tests for permission modes and PermissionMiddleware."""

import pytest

from app.tools.base import Tool, ToolCallPolicy
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


class PolicyTool(FakeTool):
    def __init__(self, tool_name="fake", policy=None, policy_fn=None):
        super().__init__(tool_name=tool_name)
        self._policy = policy
        self._policy_fn = policy_fn

    def get_call_policy(self, arguments=None) -> ToolCallPolicy:
        if self._policy_fn is not None:
            return self._policy_fn(arguments or {})
        return self._policy or ToolCallPolicy()


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


class TestResearchMode:
    @pytest.mark.asyncio
    async def test_allows_memory_store(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("memory_store", policy=ToolCallPolicy(mutates_state=True, tags=frozenset({"memory"}))),
            {},
        )
        assert result == "memory_store executed"

    @pytest.mark.asyncio
    async def test_blocks_write_file(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("write_file", policy=ToolCallPolicy(mutates_state=True, tags=frozenset({"filesystem", "write"}))),
            {},
        )
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_exec(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("exec", policy=ToolCallPolicy(mutates_state=True, tags=frozenset({"shell"}))),
            {},
        )
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_delegation(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("route", policy=ToolCallPolicy(delegates=True, tags=frozenset({"orchestration"}))),
            {},
        )
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_contradiction_resolution(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool(
                "contradiction_review",
                policy_fn=lambda arguments: ToolCallPolicy(
                    mutates_state=arguments.get("action") == "resolve",
                    tags=frozenset({"memory", "contradiction"}),
                ),
            ),
            {"action": "resolve"},
        )
        assert result.startswith("Error:")
        assert "mutates_state" in result

    @pytest.mark.asyncio
    async def test_allows_non_mutating_contradiction_review(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool(
                "contradiction_review",
                policy_fn=lambda arguments: ToolCallPolicy(
                    mutates_state=arguments.get("action") == "resolve",
                    tags=frozenset({"memory", "contradiction"}),
                ),
            ),
            {"action": "list"},
        )
        assert result == "contradiction_review executed"


class TestDelegateOnlyMode:
    @pytest.mark.asyncio
    async def test_allows_route(self):
        mw = PermissionMiddleware("delegate_only")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("route", policy=ToolCallPolicy(delegates=True, tags=frozenset({"orchestration"}))),
            {},
        )
        assert result == "route executed"

    @pytest.mark.asyncio
    async def test_allows_spawn_agent(self):
        mw = PermissionMiddleware("delegate_only")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("spawn_agent", policy=ToolCallPolicy(delegates=True, tags=frozenset({"subagent"}))),
            {},
        )
        assert result == "spawn_agent executed"

    @pytest.mark.asyncio
    async def test_blocks_memory_store(self):
        mw = PermissionMiddleware("delegate_only")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("memory_store", policy=ToolCallPolicy(mutates_state=True, tags=frozenset({"memory"}))),
            {},
        )
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_contradiction_resolution(self):
        mw = PermissionMiddleware("delegate_only")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool(
                "contradiction_review",
                policy_fn=lambda arguments: ToolCallPolicy(
                    mutates_state=arguments.get("action") == "resolve",
                    tags=frozenset({"memory", "contradiction"}),
                ),
            ),
            {"action": "resolve"},
        )
        assert result.startswith("Error:")
        assert "mutates_state" in result


class TestUnknownMode:
    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown permission mode"):
            PermissionMiddleware("unknown_mode")


class TestPermissionBlockedMapping:
    def test_full_blocks_nothing(self):
        assert PERMISSION_BLOCKED["full"] == set()

    def test_plan_blocks_expected_tools(self):
        expected = {
            "apply_patch",
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

    def test_research_blocks_expected_tools(self):
        expected = {
            "apply_patch",
            "write_file",
            "edit_file",
            "exec",
            "memory_relate",
            "sequential_pipeline",
            "fanout_pipeline",
            "route",
            "spawn_agent",
        }
        assert PERMISSION_BLOCKED["research"] == expected

    def test_delegate_only_blocks_expected_tools(self):
        expected = {
            "apply_patch",
            "write_file",
            "edit_file",
            "exec",
            "memory_store",
            "memory_relate",
        }
        assert PERMISSION_BLOCKED["delegate_only"] == expected
