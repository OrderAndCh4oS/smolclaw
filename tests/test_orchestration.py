"""Tests for orchestration patterns."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_config import AgentConfig
from app.orchestration import fanout_pipeline, route, sequential_pipeline


def _make_config(name: str = "test") -> AgentConfig:
    return AgentConfig(
        name=name,
        model="gpt-test",
        persona="Test agent",
        tools=["memory_search"],
    )


def _mock_build_agent_loop(return_value: str = "result"):
    """Create a mock that returns a mock AgentLoop with a mock process()."""
    mock_loop = MagicMock()
    mock_loop.process = AsyncMock(return_value=return_value)
    mock_loop.close = AsyncMock()
    mock_loop._closed = False
    return mock_loop


class TestSequentialPipeline:
    @pytest.mark.asyncio
    @patch("app.orchestration.build_agent_loop")
    async def test_chains_output_to_input(self, mock_build):
        loops = [
            _mock_build_agent_loop("step1_output"),
            _mock_build_agent_loop("step2_output"),
        ]
        mock_build.side_effect = loops

        configs = {"a": _make_config("a"), "b": _make_config("b")}
        result = await sequential_pipeline(
            ["a", "b"], "initial", configs,
            MagicMock(), None, MagicMock(),
        )

        assert result == "step2_output"
        # First agent gets initial input
        loops[0].process.assert_called_once_with("initial")
        # Second agent gets first agent's output
        loops[1].process.assert_called_once_with("step1_output")
        # Both loops closed
        loops[0].close.assert_called_once()
        loops[1].close.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.orchestration.build_agent_loop")
    async def test_single_agent(self, mock_build):
        loop = _mock_build_agent_loop("only_output")
        mock_build.return_value = loop

        configs = {"a": _make_config("a")}
        result = await sequential_pipeline(
            ["a"], "input", configs, MagicMock(), None, MagicMock(),
        )
        assert result == "only_output"

    @pytest.mark.asyncio
    async def test_unknown_agent_returns_error(self):
        result = await sequential_pipeline(
            ["nonexistent"], "input", {}, MagicMock(), None, MagicMock(),
        )
        assert "Error" in result
        assert "nonexistent" in result


class TestFanoutPipeline:
    @pytest.mark.asyncio
    @patch("app.orchestration.build_agent_loop")
    async def test_parallel_execution(self, mock_build):
        loops = [
            _mock_build_agent_loop("result_a"),
            _mock_build_agent_loop("result_b"),
        ]
        mock_build.side_effect = loops

        configs = {"a": _make_config("a"), "b": _make_config("b")}
        results = await fanout_pipeline(
            ["a", "b"], "same input", configs,
            MagicMock(), None, MagicMock(),
        )

        assert results == ["result_a", "result_b"]
        loops[0].process.assert_called_once_with("same input")
        loops[1].process.assert_called_once_with("same input")

    @pytest.mark.asyncio
    async def test_unknown_agent_in_fanout(self):
        configs = {"a": _make_config("a")}
        with patch("app.orchestration.build_agent_loop") as mock_build:
            mock_build.return_value = _mock_build_agent_loop("ok")
            results = await fanout_pipeline(
                ["a", "unknown"], "input", configs,
                MagicMock(), None, MagicMock(),
            )
        assert results[0] == "ok"
        assert "Error" in results[1]

    @pytest.mark.asyncio
    @patch("app.orchestration.build_agent_loop")
    async def test_agent_exception(self, mock_build):
        loop = MagicMock()
        loop.process = AsyncMock(side_effect=RuntimeError("boom"))
        loop.close = AsyncMock()
        loop._closed = False
        mock_build.return_value = loop

        configs = {"a": _make_config("a")}
        results = await fanout_pipeline(
            ["a"], "input", configs, MagicMock(), None, MagicMock(),
        )
        assert "Error" in results[0]
        assert "boom" in results[0]


class TestRoute:
    @pytest.mark.asyncio
    @patch("app.orchestration.build_agent_loop")
    async def test_pattern_match(self, mock_build):
        loop = _mock_build_agent_loop("code answer")
        mock_build.return_value = loop

        configs = {"researcher": _make_config("researcher"), "coder": _make_config("coder")}
        result = await route(
            "Write a function to sort numbers",
            {"research|analyze": "researcher", "write|code|function": "coder"},
            configs, MagicMock(), None, MagicMock(),
        )
        assert result == "code answer"

    @pytest.mark.asyncio
    @patch("app.orchestration.build_agent_loop")
    async def test_default_to_first_route(self, mock_build):
        loop = _mock_build_agent_loop("default answer")
        mock_build.return_value = loop

        configs = {"default": _make_config("default")}
        result = await route(
            "something unmatched",
            {"very_specific_pattern": "default"},
            configs, MagicMock(), None, MagicMock(),
        )
        # Falls through patterns, defaults to first route
        assert result == "default answer"

    @pytest.mark.asyncio
    async def test_no_routes_returns_error(self):
        result = await route(
            "input", {}, {}, MagicMock(), None, MagicMock(),
        )
        assert "Error" in result

    @pytest.mark.asyncio
    @patch("app.orchestration.build_agent_loop")
    async def test_llm_routing(self, mock_build):
        loop = _mock_build_agent_loop("researched answer")
        mock_build.return_value = loop

        from app.schemas import RouteDecision
        mock_llm = MagicMock()
        mock_llm.get_structured_completion = AsyncMock(
            return_value=RouteDecision(
                selected_route="research",
                confidence=0.9,
                reasoning="This is a research question",
            )
        )

        configs = {"researcher": _make_config("researcher"), "coder": _make_config("coder")}
        result = await route(
            "What are the economic impacts of tariffs?",
            {"research": "researcher", "code": "coder"},
            configs, MagicMock(), None, MagicMock(),
            llm=mock_llm,
        )
        assert result == "researched answer"

    @pytest.mark.asyncio
    @patch("app.orchestration.build_agent_loop")
    async def test_llm_routing_fallback_to_pattern(self, mock_build):
        loop = _mock_build_agent_loop("pattern answer")
        mock_build.return_value = loop

        mock_llm = MagicMock()
        mock_llm.get_structured_completion = AsyncMock(side_effect=Exception("LLM failed"))

        configs = {"coder": _make_config("coder")}
        result = await route(
            "Write some code",
            {"code|write": "coder"},
            configs, MagicMock(), None, MagicMock(),
            llm=mock_llm,
        )
        assert result == "pattern answer"
