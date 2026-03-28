import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent_config import AgentConfig
from app.subagent import SubagentManager


@pytest.fixture
def subagent_config():
    return {
        "worker": AgentConfig(
            name="worker",
            model="gpt-5.2-instant",
            persona="You are Worker.",
            tools=[],
        )
    }


class TestSubagentManager:
    @pytest.mark.asyncio
    async def test_spawn_uses_child_agent_factory(self, subagent_config):
        child_factory = MagicMock()
        loop = MagicMock()
        loop.process = AsyncMock(return_value="done")
        loop.close = AsyncMock()
        child_factory.build.return_value = loop

        manager = SubagentManager(
            configs=subagent_config,
            child_agent_factory=child_factory,
        )

        task_id = await manager.spawn("worker", "finish task")
        await manager._tasks[task_id]

        assert task_id == "sub-1"
        child_factory.build.assert_called_once_with(
            subagent_config["worker"],
            purpose="spawn-sub-1",
        )
        assert manager._results[task_id] == "done"
        loop.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_calls_close_on_success(self, subagent_config):
        manager = SubagentManager(
            configs=subagent_config,
            child_agent_factory=MagicMock(),
        )
        loop = MagicMock()
        loop.process = AsyncMock(return_value="done")
        loop.close = AsyncMock()

        await manager._run("sub-1", loop, "finish task")

        assert manager._results["sub-1"] == "done"
        loop.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_calls_close_on_failure(self, subagent_config):
        manager = SubagentManager(
            configs=subagent_config,
            child_agent_factory=MagicMock(),
        )
        loop = MagicMock()
        loop.process = AsyncMock(side_effect=RuntimeError("boom"))
        loop.close = AsyncMock()

        await manager._run("sub-1", loop, "finish task")

        assert "Error: agent failed" in manager._results["sub-1"]
        loop.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_cancels_pending_tasks(self, subagent_config):
        manager = SubagentManager(
            configs=subagent_config,
            child_agent_factory=MagicMock(),
        )
        loop = MagicMock()

        started = asyncio.Event()

        async def long_running(_goal):
            started.set()
            await asyncio.Future()

        loop.process = AsyncMock(side_effect=long_running)
        loop.close = AsyncMock()

        task = asyncio.create_task(manager._run("sub-1", loop, "finish task"))
        manager._tasks["sub-1"] = task
        await started.wait()

        await manager.close()

        assert manager._results["sub-1"] == "Error: agent cancelled during shutdown"
        loop.close.assert_awaited_once()
        assert task.cancelled()
