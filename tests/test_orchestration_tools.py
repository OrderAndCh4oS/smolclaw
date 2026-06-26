"""Tests for orchestration tool wrappers."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent_config import AgentConfig
from app.tools.orchestration_tools import (
    FanoutPipelineTool,
    RouteTool,
    SequentialPipelineTool,
)


def _make_config(name: str = "test") -> AgentConfig:
    return AgentConfig(
        name=name, model="gpt-test", persona="Test", tools=["memory_search"],
    )


class TestSequentialPipelineTool:
    def test_schema(self):
        tool = SequentialPipelineTool({}, MagicMock(), None, MagicMock())
        schema = tool.to_schema()
        assert schema["function"]["name"] == "sequential_pipeline"
        assert "agent_names" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_execute(self):
        mock_seq = AsyncMock()
        mock_seq.return_value = "final result"
        configs = {"a": _make_config("a")}
        tool = SequentialPipelineTool(configs, MagicMock(), None, MagicMock(), runner=mock_seq)
        result = await tool.execute(agent_names=["a"], input="go")
        assert result == "final result"
        mock_seq.assert_called_once()


class TestFanoutPipelineTool:
    def test_schema(self):
        tool = FanoutPipelineTool({}, MagicMock(), None, MagicMock())
        schema = tool.to_schema()
        assert schema["function"]["name"] == "fanout_pipeline"

    @pytest.mark.asyncio
    async def test_execute_returns_json(self):
        mock_fan = AsyncMock()
        mock_fan.return_value = ["result_a", "result_b"]
        tool = FanoutPipelineTool({}, MagicMock(), None, MagicMock(), runner=mock_fan)
        result = await tool.execute(agent_names=["a", "b"], input="test")
        parsed = json.loads(result)
        assert parsed == ["result_a", "result_b"]


class TestRouteTool:
    def test_schema(self):
        tool = RouteTool({}, MagicMock(), None, MagicMock())
        schema = tool.to_schema()
        assert schema["function"]["name"] == "route"

    @pytest.mark.asyncio
    async def test_execute(self):
        mock_route = AsyncMock()
        mock_route.return_value = "routed result"
        llm = MagicMock()
        tool = RouteTool({}, MagicMock(), None, MagicMock(), llm=llm, runner=mock_route)
        result = await tool.execute(
            input="test query",
            routes={"pattern": "agent_name"},
        )
        assert result == "routed result"
        assert mock_route.call_args.kwargs["llm"] is llm

    @pytest.mark.asyncio
    async def test_bind_uses_runtime_llm(self):
        mock_route = AsyncMock(return_value="ok")
        runtime_llm = MagicMock()
        runtime_ctx = MagicMock()
        runtime_ctx.llm = runtime_llm
        runtime_ctx.child_agent_factory = None
        tool = RouteTool({}, MagicMock(), None, MagicMock(), runner=mock_route).bind(runtime_ctx)

        await tool.execute(input="test query", routes={"pattern": "agent_name"})

        assert mock_route.call_args.kwargs["llm"] is runtime_llm
