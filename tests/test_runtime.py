from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_config import AgentConfig
from app.context_assembly import ContextAssembler
from app.context_builder import ContextBuilder
from app.hooks import ON_AFTER_TOOL
from app.runtime import RuntimeEnvironment, build_configured_agent
from app.session import SessionManager
from app.workspace import WorkspaceContext


def _make_loop_llm():
    llm = MagicMock()
    llm.completion_model = "gpt-test"
    llm.get_tool_completion = AsyncMock(return_value={
        "content": "ok",
        "tool_calls": None,
        "has_tool_calls": False,
    })
    llm.get_completion = AsyncMock(return_value="summary")
    return llm


class TestRuntimeMemoryCapabilities:
    @pytest.mark.asyncio
    async def test_build_configured_agent_without_memory_capability_disables_memory(
        self, mock_smol_rag, sessions_dir, temp_dir
    ):
        llm = _make_loop_llm()
        env = RuntimeEnvironment(
            smol_rag=mock_smol_rag,
            session_manager=SessionManager(sessions_dir),
            workspace=WorkspaceContext.from_root(temp_dir),
        )
        config = AgentConfig(
            name="reader",
            model="gpt-test",
            persona="You are Reader.",
            tools=["read_file"],
            capabilities=["filesystem"],
            memory_window=20,
        )

        with patch("app.agent_factory.create_llm", return_value=llm):
            loop = build_configured_agent(config, env)

        assert loop.smol_rag is None
        assert isinstance(loop.context_builder, ContextBuilder)
        assert ON_AFTER_TOOL not in loop.hook_runner.events

        for i in range(25):
            loop.session.add_message({"role": "user", "content": f"msg {i}"})
            loop.session.add_message({"role": "assistant", "content": f"reply {i}"})

        await loop.process("new input")

        mock_smol_rag.ingest_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_build_configured_agent_with_memory_capability_enables_memory(
        self, mock_smol_rag, sessions_dir, temp_dir
    ):
        llm = _make_loop_llm()
        env = RuntimeEnvironment(
            smol_rag=mock_smol_rag,
            session_manager=SessionManager(sessions_dir),
            workspace=WorkspaceContext.from_root(temp_dir),
        )
        config = AgentConfig(
            name="researcher",
            model="gpt-test",
            persona="You are Researcher.",
            tools=["memory_search"],
            capabilities=["filesystem", "memory"],
            memory_window=20,
        )

        with patch("app.agent_factory.create_llm", return_value=llm):
            loop = build_configured_agent(config, env)

        assert loop.smol_rag is mock_smol_rag
        assert isinstance(loop.context_builder, ContextAssembler)
        assert ON_AFTER_TOOL in loop.hook_runner.events

        defs = [schema["function"]["name"] for schema in loop.tool_registry.get_definitions()]
        assert "tool_search" in defs

        for i in range(25):
            loop.session.add_message({"role": "user", "content": f"msg {i}"})
            loop.session.add_message({"role": "assistant", "content": f"reply {i}"})

        await loop.process("new input")

        mock_smol_rag.ingest_text.assert_called_once()


class TestRuntimeProviders:
    @pytest.mark.asyncio
    async def test_build_configured_agent_uses_mcp_wrappers_for_gateway_transport(
        self, mock_smol_rag, sessions_dir, temp_dir
    ):
        llm = _make_loop_llm()
        env = RuntimeEnvironment(
            smol_rag=mock_smol_rag,
            session_manager=SessionManager(sessions_dir),
            workspace=WorkspaceContext.from_root(temp_dir),
            transport="mcp",
            token_issuer_url="http://issuer",
            gateway_url="http://gateway",
        )
        config = AgentConfig(
            name="reader",
            model="gpt-test",
            persona="You are Reader.",
            tools=["read_file", "web_fetch"],
            capabilities=["filesystem", "web"],
        )

        with patch("app.agent_factory.create_llm", return_value=llm):
            loop = build_configured_agent(config, env)

        assert loop.tool_registry._tools["read_file"].__class__.__name__ == "McpFileReadTool"
        assert loop.tool_registry._tools["web_fetch"].__class__.__name__ == "McpHttpFetchTool"

    def test_build_configured_agent_rejects_unsatisfied_tools_for_transport(
        self, mock_smol_rag, sessions_dir, temp_dir
    ):
        env = RuntimeEnvironment(
            smol_rag=mock_smol_rag,
            session_manager=SessionManager(sessions_dir),
            workspace=WorkspaceContext.from_root(temp_dir),
            transport="mcp",
            token_issuer_url="http://issuer",
            gateway_url="http://gateway",
        )
        config = AgentConfig(
            name="reader",
            model="gpt-test",
            persona="You are Reader.",
            tools=["list_dir"],
            capabilities=["filesystem"],
        )

        with patch("app.agent_factory.create_llm", return_value=_make_loop_llm()):
            with pytest.raises(ValueError) as exc_info:
                build_configured_agent(config, env)

        assert "unavailable for transport 'mcp'" in str(exc_info.value)
