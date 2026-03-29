import os
from contextlib import nullcontext

import pytest
import typer
from typer.testing import CliRunner

from app.agent_config import AgentConfigLoader
from app.agent_loop import AgentLoop
from app.tools.registry import ToolRegistry
from cli.main import _build_cli_tool_registry, _build_default_chat_agent, _build_multiagent
from app.hooks import ON_SESSION_END, HookRunner
from app.session import SessionManager
from unittest.mock import ANY, AsyncMock, MagicMock, patch


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
    def test_empty_cli_invocation_shows_help(self):
        from cli.main import app

        result = CliRunner().invoke(app, [])

        assert result.exit_code == 0
        assert "Usage" in result.stdout
        assert "chat" in result.stdout

    def test_subcommand_help_renders(self):
        from cli.main import app

        result = CliRunner().invoke(app, ["chat", "--help"])

        assert result.exit_code == 0
        assert "Start an interactive chat session." in result.stdout
        assert "--session" in result.stdout

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
        with patch("cli.main._build_cli_tool_registry", return_value=registry):

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
        with patch("cli.main._build_cli_tool_registry", return_value=registry):

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
        configs = AgentConfigLoader.load(agents_yaml)
        registry = _build_cli_tool_registry(
            mock_smol_rag,
            "/tmp",
            agent_configs=configs,
            session_manager=sm,
            enable_subagents=True,
        )

        tool_names = [d["function"]["name"] for d in registry.get_definitions()]
        assert "spawn_agent" in tool_names
        assert "get_result" in tool_names

    def test_build_multiagent_passes_child_loop_registrar_when_provided(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        fake_agent = MagicMock()
        registrar = MagicMock()

        with patch("cli.main.build_configured_agent", return_value=fake_agent) as mock_build_configured_agent:
            agent = _build_multiagent(
                agent_name="researcher",
                agents_config_path=agents_yaml,
                session_key="default",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
                auto_export=True,
                child_loop_registrar=registrar,
            )

        assert agent is fake_agent
        assert mock_build_configured_agent.call_args.kwargs["child_loop_registrar"] is registrar
        assert mock_build_configured_agent.call_args.kwargs["env"].enable_subagents is True

    def test_build_multiagent_defaults_child_loop_registrar_to_none(self, agents_yaml, mock_smol_rag, sessions_dir):
        sm = SessionManager(sessions_dir)
        fake_agent = MagicMock()

        with patch("cli.main.build_configured_agent", return_value=fake_agent) as mock_build_configured_agent:
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
        assert mock_build_configured_agent.call_args.kwargs["child_loop_registrar"] is None

    @pytest.mark.asyncio
    async def test_chat_loop_registers_export_hook_for_multiagent(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                pass

            async def prompt_async(self, _prompt):
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

        with patch("cli.main.create_smol_rag", return_value=smol_rag), \
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
            child_loop_registrar=ANY,
        )
        assert ON_SESSION_END in fake_agent.hook_runner.events
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_skips_export_hook_when_disabled(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                pass

            async def prompt_async(self, _prompt):
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

        with patch("cli.main.create_smol_rag", return_value=smol_rag), \
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
            child_loop_registrar=ANY,
        )
        # Usage persist hook is always registered; export hooks only when auto_export=True
        assert ON_SESSION_END in fake_agent.hook_runner.events
        # Only 1 hook (UsagePersistHook), not the export/decay/contradiction hooks
        assert len(fake_agent.hook_runner._hooks[ON_SESSION_END]) == 1
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_without_agent_uses_default_chat_builder(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                pass

            async def prompt_async(self, _prompt):
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

        with patch("cli.main.create_smol_rag", return_value=smol_rag), \
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
            child_loop_registrar=ANY,
        )
        assert ON_SESSION_END in fake_agent.hook_runner.events
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_remember_command_stores_memory_without_agent_turn(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/remember save this detail"])

            async def prompt_async(self, _prompt):
                try:
                    return next(self._inputs)
                except StopIteration:
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
        fake_agent.process = AsyncMock()
        fake_agent.session = MagicMock()

        memory_tool = MagicMock()
        memory_tool.execute = AsyncMock(return_value="Stored memory: mem-1")
        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main.create_smol_rag", return_value=smol_rag), \
            patch("cli.main.SessionManager", return_value=session_manager), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main.MemoryStoreTool", return_value=memory_tool), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent) as mock_build_default_chat_agent, \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        mock_build_default_chat_agent.assert_called_once()
        memory_tool.execute.assert_awaited_once_with(content="save this detail")
        fake_agent.process.assert_not_called()
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_remember_thread_exports_current_session(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/remember-thread"])

            async def prompt_async(self, _prompt):
                try:
                    return next(self._inputs)
                except StopIteration:
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
        fake_agent.process = AsyncMock()
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main.create_smol_rag", return_value=smol_rag), \
            patch("cli.main.SessionManager", return_value=session_manager), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main.SessionExportHook") as mock_export_hook_cls, \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", FakeConsole()):
            hook_instance = AsyncMock()
            mock_export_hook_cls.return_value = hook_instance
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        hook_instance.assert_awaited_once_with({
            "session_key": "default",
            "session": fake_agent.session,
        })
        fake_agent.process.assert_not_called()
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_help_command_shows_slash_command_list(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/help"])

            async def prompt_async(self, _prompt):
                try:
                    return next(self._inputs)
                except StopIteration:
                    raise EOFError

        class FakeConsole:
            def __init__(self):
                self.lines = []

            def status(self, *args, **kwargs):
                return nullcontext()

            def print(self, *args, **kwargs):
                self.lines.append(" ".join(str(arg) for arg in args))

        fake_console = FakeConsole()
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.process = AsyncMock()
        fake_agent.session = MagicMock()

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main.create_smol_rag", return_value=smol_rag), \
            patch("cli.main.SessionManager", return_value=session_manager), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        help_output = "\n".join(fake_console.lines)
        assert "Slash commands:" in help_output
        assert "/remember <text>" in help_output
        assert "/remember-thread" in help_output
        assert "/quit or /exit" in help_output
        fake_agent.process.assert_not_called()
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_close_releases_agent_llm(self, temp_dir):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                pass

            async def prompt_async(self, _prompt):
                raise EOFError

        class FakeConsole:
            def status(self, *args, **kwargs):
                return nullcontext()

            def print(self, *args, **kwargs):
                return None

        llm = MagicMock()
        llm.close = AsyncMock()
        session_manager = SessionManager(temp_dir)
        session = session_manager.get_or_create("close-test")
        agent = AgentLoop(
            llm=llm,
            tool_registry=ToolRegistry(),
            context_builder=MagicMock(),
            session=session,
            session_manager=session_manager,
            hook_runner=HookRunner(),
        )
        smol_rag = MagicMock()
        smol_rag.close = AsyncMock()

        with patch("cli.main.create_smol_rag", return_value=smol_rag), \
            patch("cli.main.SessionManager", return_value=session_manager), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=agent), \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("close-test", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        llm.close.assert_awaited_once()
        smol_rag.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_shows_live_tool_actions(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["check the docs"])

            async def prompt_async(self, _prompt):
                try:
                    return next(self._inputs)
                except StopIteration:
                    raise EOFError

        class FakeConsole:
            def __init__(self):
                self.lines = []

            def status(self, *args, **kwargs):
                return nullcontext()

            def print(self, *args, **kwargs):
                self.lines.append(" ".join(str(arg) for arg in args))

        async def fake_process(_message, on_output=None, on_event=None):
            if on_event:
                await on_event({
                    "type": "tool",
                    "phase": "start",
                    "name": "web_fetch",
                    "summary": "web_fetch url=https://example.com/docs",
                })
                await on_event({
                    "type": "tool",
                    "phase": "end",
                    "name": "web_fetch",
                    "ok": True,
                    "duration_ms": 412,
                })
            return "done"

        fake_console = FakeConsole()
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.process = AsyncMock(side_effect=fake_process)
        fake_agent.session = MagicMock()

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main.create_smol_rag", return_value=smol_rag), \
            patch("cli.main.SessionManager", return_value=session_manager), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True, show_actions=True)

        output = "\n".join(fake_console.lines)
        assert "action: web_fetch url=https://example.com/docs" in output
        assert "done: web_fetch (0.4s)" in output
        fake_agent.close.assert_awaited_once()
