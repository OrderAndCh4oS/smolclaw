import os
from contextlib import nullcontext

import pytest
import typer

from app.agent_config import AgentConfigLoader
from app.agent_loop import AgentLoop
from cli.main import _build_default_chat_agent, _build_multiagent
from app.hooks import ON_SESSION_END, HookRunner
from app.session import SessionManager
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def agents_yaml(temp_dir):
    path = os.path.join(temp_dir, "agents.yaml")
    with open(path, "w") as f:
        f.write(
            "agents:\n"
            "  - name: default\n"
            "    model: gpt-5.2-mini\n"
            "    persona: You are Default.\n"
            "    tools:\n"
            "      - memory_search\n"
            "      - memory_recall\n"
            "      - read_file\n"
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
    def test_runtime_default_agent_includes_memory_recall(self):
        configs = AgentConfigLoader.load(os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.yaml"))
        assert "memory_recall" in configs["default"].tools

    def test_chat_without_agent_flag_backwards_compat(self, mock_smol_rag, sessions_dir, temp_dir):
        """When no --agent flag, standard single-agent behavior still works."""
        from cli.main import _chat_loop
        import inspect
        sig = inspect.signature(_chat_loop)
        assert "agent_name" in sig.parameters
        assert sig.parameters["agent_name"].default is None

    def test_chat_with_agent_flag_loads_config(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        from app.tools.registry import ToolRegistry
        registry = ToolRegistry()
        with patch("cli.main._build_tool_registry", return_value=registry):

            agent = _build_multiagent(
                agent_name="researcher",
                agents_config_path=agents_yaml,
                session_key="default",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
                auto_export=True,
            )
            assert isinstance(agent, AgentLoop)
            assert agent.llm.completion_model == "gpt-5.2-instant"
            assert "researcher" in agent.session.key

    def test_build_default_chat_agent_uses_exact_session_key_and_model_override(
        self, agents_yaml, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        from app.tools.registry import ToolRegistry
        registry = ToolRegistry()
        with patch("cli.main._build_tool_registry", return_value=registry):

            agent = _build_default_chat_agent(
                agents_config_path=agents_yaml,
                session_key="plain-session",
                model="gpt-5.2-pro",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
            )

        assert isinstance(agent, AgentLoop)
        assert agent.llm.completion_model == "gpt-5.2-pro"
        assert agent.session.key == "plain-session"

    def test_build_default_chat_agent_requires_default_entry(self, temp_dir, mock_smol_rag, sessions_dir):
        path = os.path.join(temp_dir, "agents.yaml")
        with open(path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: researcher\n"
                "    model: gpt-5.2-instant\n"
                "    persona: You are Researcher.\n"
            )
        sm = SessionManager(sessions_dir)

        with pytest.raises(typer.BadParameter) as exc_info:
            _build_default_chat_agent(
                agents_config_path=path,
                session_key="plain-session",
                model="gpt-5.2-pro",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
            )

        assert "default" in str(exc_info.value)

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
                auto_export=True,
            )
        assert "nonexistent" in str(exc_info.value)
        assert "researcher" in str(exc_info.value)

    def test_multiagent_registers_spawn_tools(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        from app.tools.registry import ToolRegistry
        registry = ToolRegistry()
        with patch("cli.main._build_tool_registry", return_value=registry):

            agent = _build_multiagent(
                agent_name="researcher",
                agents_config_path=agents_yaml,
                session_key="default",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
                auto_export=True,
            )
            # The master registry should have spawn_agent and get_result
            tool_names = [d["function"]["name"] for d in registry.get_definitions()]
            assert "spawn_agent" in tool_names
            assert "get_result" in tool_names

    def test_build_multiagent_passes_registrar_to_subagent_manager_when_enabled(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        from app.tools.registry import ToolRegistry
        registry = ToolRegistry()

        with patch("cli.main._build_tool_registry", return_value=registry), \
            patch("app.subagent.SubagentManager") as mock_subagent_manager, \
            patch("app.agent_factory.build_agent_loop", return_value=fake_agent):
            agent = _build_multiagent(
                agent_name="researcher",
                agents_config_path=agents_yaml,
                session_key="default",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
                auto_export=True,
            )

        assert agent is fake_agent
        registrar = mock_subagent_manager.call_args.kwargs["session_end_hook_registrar"]
        assert callable(registrar)

        subagent_loop = MagicMock()
        subagent_loop.llm = MagicMock()
        subagent_loop.hook_runner = HookRunner()
        registrar(subagent_loop)
        assert ON_SESSION_END in subagent_loop.hook_runner.events

    def test_build_multiagent_skips_registrar_when_disabled(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        fake_agent = MagicMock()
        from app.tools.registry import ToolRegistry
        registry = ToolRegistry()

        with patch("cli.main._build_tool_registry", return_value=registry), \
            patch("app.subagent.SubagentManager") as mock_subagent_manager, \
            patch("app.agent_factory.build_agent_loop", return_value=fake_agent):
            agent = _build_multiagent(
                agent_name="researcher",
                agents_config_path=agents_yaml,
                session_key="default",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
                auto_export=False,
            )

        assert agent is fake_agent
        assert mock_subagent_manager.call_args.kwargs["session_end_hook_registrar"] is None

    @pytest.mark.asyncio
    async def test_chat_loop_registers_export_hook_for_multiagent(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                pass

            def prompt(self, _prompt):
                raise EOFError

        class FakeConsole:
            def status(self, *args, **kwargs):
                return nullcontext()

            def print(self, *args, **kwargs):
                return None

        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.session = MagicMock()

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main.SmolRag", return_value=smol_rag), \
            patch("cli.main.SessionManager", return_value=session_manager), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_multiagent", return_value=fake_agent) as mock_build_multiagent, \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("default", "/tmp", "model", agent_name="researcher", auto_export=True)

        mock_build_multiagent.assert_called_once_with(
            "researcher",
            DEFAULT_AGENTS_CONFIG,
            "default",
            smol_rag,
            "/tmp",
            session_manager,
            True,
        )
        assert ON_SESSION_END in fake_agent.hook_runner.events
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_skips_export_hook_when_disabled(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                pass

            def prompt(self, _prompt):
                raise EOFError

        class FakeConsole:
            def status(self, *args, **kwargs):
                return nullcontext()

            def print(self, *args, **kwargs):
                return None

        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.session = MagicMock()

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main.SmolRag", return_value=smol_rag), \
            patch("cli.main.SessionManager", return_value=session_manager), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_multiagent", return_value=fake_agent) as mock_build_multiagent, \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("default", "/tmp", "model", agent_name="researcher", auto_export=False)

        mock_build_multiagent.assert_called_once_with(
            "researcher",
            DEFAULT_AGENTS_CONFIG,
            "default",
            smol_rag,
            "/tmp",
            session_manager,
            False,
        )
        assert ON_SESSION_END not in fake_agent.hook_runner.events
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_without_agent_uses_default_chat_builder(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                pass

            def prompt(self, _prompt):
                raise EOFError

        class FakeConsole:
            def status(self, *args, **kwargs):
                return nullcontext()

            def print(self, *args, **kwargs):
                return None

        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.session = MagicMock()

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main.SmolRag", return_value=smol_rag), \
            patch("cli.main.SessionManager", return_value=session_manager), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent) as mock_default_builder, \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("plain-session", "/tmp", "gpt-5.2-pro", agent_name=None, auto_export=True)

        mock_default_builder.assert_called_once_with(
            agents_config_path=DEFAULT_AGENTS_CONFIG,
            session_key="plain-session",
            model="gpt-5.2-pro",
            smol_rag=smol_rag,
            workspace="/tmp",
            session_manager=session_manager,
        )
        assert ON_SESSION_END in fake_agent.hook_runner.events
        fake_agent.close.assert_awaited_once()
