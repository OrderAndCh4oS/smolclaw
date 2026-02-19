import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_config import AgentConfig
from app.session import SessionManager
from app.subagent import SubagentManager
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from app.tools.spawn import SpawnTool, GetResultTool


class StubTool(Tool):
    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Stub"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "stub"


@pytest.fixture
def agent_configs():
    return {
        "researcher": AgentConfig(
            name="researcher",
            model="gpt-5.2-instant",
            persona="You are Researcher.",
            tools=["memory_search"],
        ),
        "writer": AgentConfig(
            name="writer",
            model="gpt-5.2-pro",
            persona="You are Writer.",
            tools=["memory_search"],
        ),
    }


@pytest.fixture
def master_registry():
    registry = ToolRegistry()
    registry.register(StubTool())
    return registry


@pytest.fixture
def subagent_manager(agent_configs, master_registry, mock_smol_rag, sessions_dir):
    sm = SessionManager(sessions_dir)
    return SubagentManager(agent_configs, master_registry, mock_smol_rag, sm)


class TestSubagentManager:
    @pytest.mark.asyncio
    async def test_spawn_creates_task(self, subagent_manager):
        with patch("app.subagent.build_agent_loop") as mock_build:
            mock_loop = MagicMock()
            mock_loop.process = AsyncMock(return_value="done")
            mock_build.return_value = mock_loop
            task_id = await subagent_manager.spawn("researcher", "find info")
        assert task_id == "sub-1"
        assert "sub-1" in subagent_manager._tasks

    @pytest.mark.asyncio
    async def test_spawn_runs_agent_loop(self, subagent_manager):
        with patch("app.subagent.build_agent_loop") as mock_build:
            mock_loop = MagicMock()
            mock_loop.process = AsyncMock(return_value="research result")
            mock_build.return_value = mock_loop
            task_id = await subagent_manager.spawn("researcher", "find info")
            await asyncio.sleep(0.05)  # let the task complete
        result = subagent_manager.get_result(task_id)
        assert result == "research result"

    @pytest.mark.asyncio
    async def test_spawn_max_concurrent(self, agent_configs, master_registry, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        manager = SubagentManager(agent_configs, master_registry, mock_smol_rag, sm, max_concurrent=1)

        with patch("app.subagent.build_agent_loop") as mock_build:
            # Create a long-running task
            never_done = asyncio.Future()
            mock_loop = MagicMock()
            mock_loop.process = AsyncMock(return_value=never_done)
            # Make process await the future
            async def slow_process(goal):
                await never_done
                return "done"
            mock_loop.process = slow_process
            mock_build.return_value = mock_loop

            task_id1 = await manager.spawn("researcher", "task 1")
            assert task_id1 == "sub-1"

            result = await manager.spawn("researcher", "task 2")
            assert "Error" in result
            assert "max concurrent" in result

            # Cleanup: cancel the pending task
            manager._tasks[task_id1].cancel()
            try:
                await manager._tasks[task_id1]
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_get_result_pending(self, subagent_manager):
        with patch("app.subagent.build_agent_loop") as mock_build:
            never_done = asyncio.Future()
            mock_loop = MagicMock()
            async def slow_process(goal):
                await never_done
                return "done"
            mock_loop.process = slow_process
            mock_build.return_value = mock_loop

            task_id = await subagent_manager.spawn("researcher", "find info")
            result = subagent_manager.get_result(task_id)
            assert result == "pending"

            # Cleanup
            subagent_manager._tasks[task_id].cancel()
            try:
                await subagent_manager._tasks[task_id]
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_get_result_completed(self, subagent_manager):
        with patch("app.subagent.build_agent_loop") as mock_build:
            mock_loop = MagicMock()
            mock_loop.process = AsyncMock(return_value="the answer")
            mock_build.return_value = mock_loop

            task_id = await subagent_manager.spawn("researcher", "find info")
            await asyncio.sleep(0.05)

        result = subagent_manager.get_result(task_id)
        assert result == "the answer"

    @pytest.mark.asyncio
    async def test_spawn_unknown_agent(self, subagent_manager):
        result = await subagent_manager.spawn("nonexistent", "do something")
        assert "Error" in result
        assert "unknown agent" in result

    @pytest.mark.asyncio
    async def test_get_result_unknown_task(self, subagent_manager):
        result = subagent_manager.get_result("sub-999")
        assert "Error" in result
        assert "unknown task" in result

    @pytest.mark.asyncio
    async def test_spawn_uses_agent_config(self, subagent_manager):
        with patch("app.subagent.build_agent_loop") as mock_build:
            mock_loop = MagicMock()
            mock_loop.process = AsyncMock(return_value="done")
            mock_build.return_value = mock_loop

            await subagent_manager.spawn("researcher", "find info")

            call_args = mock_build.call_args
            config = call_args[0][0]
            assert config.name == "researcher"
            assert config.model == "gpt-5.2-instant"


class TestSpawnTool:
    def test_spawn_tool_schema(self):
        manager = MagicMock()
        tool = SpawnTool(manager)
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "spawn_agent"
        props = schema["function"]["parameters"]["properties"]
        assert "agent_name" in props
        assert "goal" in props

    @pytest.mark.asyncio
    async def test_spawn_tool_execute(self):
        manager = MagicMock()
        manager.spawn = AsyncMock(return_value="sub-1")
        tool = SpawnTool(manager)
        result = await tool.execute(agent_name="researcher", goal="research SaaS")
        manager.spawn.assert_called_once_with("researcher", "research SaaS")
        assert result == "sub-1"


class TestGetResultTool:
    def test_get_result_tool_schema(self):
        manager = MagicMock()
        tool = GetResultTool(manager)
        schema = tool.to_schema()
        assert schema["function"]["name"] == "get_result"
        props = schema["function"]["parameters"]["properties"]
        assert "task_id" in props

    @pytest.mark.asyncio
    async def test_get_result_tool_execute(self):
        manager = MagicMock()
        manager.get_result.return_value = "the answer"
        tool = GetResultTool(manager)
        result = await tool.execute(task_id="sub-1")
        manager.get_result.assert_called_once_with("sub-1")
        assert result == "the answer"
