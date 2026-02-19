import os

import pytest
import typer

from app.agent_config import AgentConfigLoader
from app.agent_loop import AgentLoop
from cli.main import _build_multiagent, _build_tool_registry
from app.session import SessionManager
from app.smol_rag import SmolRag
from unittest.mock import MagicMock, patch


@pytest.fixture
def agents_yaml(temp_dir):
    path = os.path.join(temp_dir, "agents.yaml")
    with open(path, "w") as f:
        f.write(
            "agents:\n"
            "  - name: researcher\n"
            "    model: gpt-5.2-instant\n"
            "    persona: You are Researcher.\n"
            "    tools:\n"
            "      - memory_search\n"
            "      - web_search\n"
            "  - name: writer\n"
            "    model: gpt-5.2-pro\n"
            "    persona: You are Writer.\n"
            "    tools:\n"
            "      - memory_search\n"
            "      - read_file\n"
        )
    return path


class TestCliMultiagent:
    def test_chat_without_agent_flag_backwards_compat(self, mock_smol_rag, sessions_dir, temp_dir):
        """When no --agent flag, standard single-agent behavior still works."""
        from cli.main import _chat_loop
        import inspect
        sig = inspect.signature(_chat_loop)
        assert "agent_name" in sig.parameters
        assert sig.parameters["agent_name"].default is None

    def test_chat_with_agent_flag_loads_config(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        with patch("cli.main._build_tool_registry") as mock_registry:
            from app.tools.registry import ToolRegistry
            registry = ToolRegistry()
            mock_registry.return_value = registry

            agent = _build_multiagent(
                agent_name="researcher",
                agents_config_path=agents_yaml,
                session_key="default",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
            )
            assert isinstance(agent, AgentLoop)
            assert agent.llm.completion_model == "gpt-5.2-instant"
            assert "researcher" in agent.session.key

    def test_chat_unknown_agent_raises(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        with pytest.raises(typer.BadParameter) as exc_info:
            _build_multiagent(
                agent_name="nonexistent",
                agents_config_path=agents_yaml,
                session_key="default",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
            )
        assert "nonexistent" in str(exc_info.value)
        assert "researcher" in str(exc_info.value)

    def test_multiagent_registers_spawn_tools(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        with patch("cli.main._build_tool_registry") as mock_registry:
            from app.tools.registry import ToolRegistry
            registry = ToolRegistry()
            mock_registry.return_value = registry

            agent = _build_multiagent(
                agent_name="researcher",
                agents_config_path=agents_yaml,
                session_key="default",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
            )
            # The master registry should have spawn_agent and get_result
            tool_names = [d["function"]["name"] for d in registry.get_definitions()]
            assert "spawn_agent" in tool_names
            assert "get_result" in tool_names
