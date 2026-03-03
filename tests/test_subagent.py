from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_config import AgentConfig
from app.subagent import SubagentManager
from app.tools.registry import ToolRegistry


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
    async def test_spawn_registers_session_end_hook(self, subagent_config):
        session_manager = MagicMock()
        registrar = MagicMock()
        loop = MagicMock()
        loop.process = AsyncMock(return_value="done")
        loop.close = AsyncMock()

        manager = SubagentManager(
            configs=subagent_config,
            master_registry=ToolRegistry(),
            smol_rag=MagicMock(),
            session_manager=session_manager,
            session_end_hook_registrar=registrar,
        )

        with patch("app.subagent.build_agent_loop", return_value=loop):
            task_id = await manager.spawn("worker", "finish task")

        await manager._tasks[task_id]

        assert task_id == "sub-1"
        registrar.assert_called_once_with(loop)
        assert manager._results[task_id] == "done"
        loop.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_calls_close_on_success(self, subagent_config):
        manager = SubagentManager(
            configs=subagent_config,
            master_registry=ToolRegistry(),
            smol_rag=MagicMock(),
            session_manager=MagicMock(),
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
            master_registry=ToolRegistry(),
            smol_rag=MagicMock(),
            session_manager=MagicMock(),
        )
        loop = MagicMock()
        loop.process = AsyncMock(side_effect=RuntimeError("boom"))
        loop.close = AsyncMock()

        await manager._run("sub-1", loop, "finish task")

        assert "Error: agent failed" in manager._results["sub-1"]
        loop.close.assert_awaited_once()
