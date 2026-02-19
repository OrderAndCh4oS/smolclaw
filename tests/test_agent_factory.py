import os
from unittest.mock import MagicMock, patch

import pytest

from app.agent_config import AgentConfig
from app.agent_factory import build_agent_loop
from app.agent_loop import AgentLoop
from app.session import SessionManager
from app.tools.base import Tool
from app.tools.registry import ToolRegistry


class StubToolA(Tool):
    @property
    def name(self) -> str:
        return "tool_a"

    @property
    def description(self) -> str:
        return "Tool A"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "a"


class StubToolB(Tool):
    @property
    def name(self) -> str:
        return "tool_b"

    @property
    def description(self) -> str:
        return "Tool B"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "b"


class StubToolC(Tool):
    @property
    def name(self) -> str:
        return "tool_c"

    @property
    def description(self) -> str:
        return "Tool C"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "c"


@pytest.fixture
def master_registry():
    registry = ToolRegistry()
    registry.register(StubToolA())
    registry.register(StubToolB())
    registry.register(StubToolC())
    return registry


@pytest.fixture
def researcher_config():
    return AgentConfig(
        name="researcher",
        model="gpt-5.2-instant",
        persona="You are Researcher.",
        tools=["tool_a", "tool_b"],
        max_iterations=20,
        memory_window=30,
    )


@pytest.fixture
def writer_config():
    return AgentConfig(
        name="writer",
        model="gpt-5.2-pro",
        persona="You are Writer.",
        tools=["tool_b", "tool_c"],
    )


def _mock_create_llm(completion_model=None, **kwargs):
    mock = MagicMock()
    mock.completion_model = completion_model
    return mock


class TestAgentFactory:
    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_returns_agent_loop(
        self, mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert isinstance(loop, AgentLoop)

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_uses_config_model(
        self, mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert loop.llm.completion_model == "gpt-5.2-instant"

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_filters_tools(
        self, mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        defs = loop.tool_registry.get_definitions()
        names = sorted([d["function"]["name"] for d in defs])
        assert names == ["tool_a", "tool_b"]

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_uses_persona(
        self, mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert loop.context_builder.persona == "You are Researcher."

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_session_key_isolation(
        self, mock_create, researcher_config, writer_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop_r = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        loop_w = build_agent_loop(writer_config, master_registry, mock_smol_rag, sm)
        assert loop_r.session.key != loop_w.session.key
        assert "researcher" in loop_r.session.key
        assert "writer" in loop_w.session.key

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_shared_smol_rag(
        self, mock_create, researcher_config, writer_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop_r = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        loop_w = build_agent_loop(writer_config, master_registry, mock_smol_rag, sm)
        assert loop_r.smol_rag is loop_w.smol_rag
