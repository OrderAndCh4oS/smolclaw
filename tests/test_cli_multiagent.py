import os
from contextlib import nullcontext

import pytest
import typer
from typer.testing import CliRunner

from app.agent_config import AgentConfigLoader
from app.definitions import build_workspace_paths
from app.agent_loop import AgentLoop
from app.approvals import ApprovalRequestStore
from app.model_settings import RuntimeModelSettings
from app.run_trace import RunTraceStore
from app.tools.registry import ToolRegistry
from cli.main import _build_cli_tool_registry, _build_default_chat_agent, _build_multiagent
from app.hooks import ON_SESSION_END, HookRunner
from app.session import SessionManager
from app.workspace import WorkspaceContext
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


def _fake_runtime(workspace_root: str | WorkspaceContext, smol_rag, session_manager):
    runtime = MagicMock()
    if isinstance(workspace_root, WorkspaceContext):
        runtime.workspace = workspace_root.ensure_dirs()
    else:
        runtime.workspace = WorkspaceContext.from_root(workspace_root).ensure_dirs()
    runtime.smol_rag = smol_rag
    runtime.session_manager = session_manager
    return runtime


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

    @pytest.mark.asyncio
    async def test_run_once_returns_json_ready_payload(self, temp_dir):
        from cli.main import DEFAULT_AGENTS_CONFIG, _run_once

        async def fake_process(message, on_output=None, on_event=None):
            trace_store = RunTraceStore(build_workspace_paths(temp_dir).traces_dir)
            recorder = trace_store.start_run("default")
            recorder.finish("complete", stop_reason="assistant_final")
            return f"response to {message}"

        fake_agent = MagicMock()
        fake_agent.process = AsyncMock(side_effect=fake_process)
        fake_agent.close = AsyncMock()
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"
        smol_rag = MagicMock()
        smol_rag.close = AsyncMock()
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime(temp_dir, smol_rag, session_manager)), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent):
            payload = await _run_once(
                prompt="hello",
                session_key="default",
                workspace=temp_dir,
                model="model",
                agents_config=DEFAULT_AGENTS_CONFIG,
            )

        assert payload["status"] == "complete"
        assert payload["response"] == "response to hello"
        assert payload["turns"] == 1
        assert payload["trace_path"].endswith(".jsonl")
        fake_agent.close.assert_awaited_once()
        smol_rag.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_once_worktree_uses_isolated_workspace_and_cleans_up(self, temp_dir):
        from cli.main import DEFAULT_AGENTS_CONFIG, _run_once

        worktree_path = os.path.join(temp_dir, "isolated")
        os.makedirs(worktree_path, exist_ok=True)
        fake_ctx = MagicMock()
        fake_ctx.path = worktree_path
        fake_ctx.diff.return_value = "diff --git a/app.py b/app.py"
        fake_agent = MagicMock()

        async def fake_process(_message):
            trace_store = RunTraceStore(build_workspace_paths(temp_dir).traces_dir)
            recorder = trace_store.start_run("default")
            recorder.finish("complete", stop_reason="assistant_final")
            return "done"

        fake_agent.process = AsyncMock(side_effect=fake_process)
        fake_agent.close = AsyncMock()
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"
        smol_rag = MagicMock()
        smol_rag.close = AsyncMock()
        session_manager = MagicMock()

        def fake_runtime(workspace_root, *_args, **_kwargs):
            assert isinstance(workspace_root, WorkspaceContext)
            assert workspace_root.root_dir == os.path.realpath(worktree_path)
            assert workspace_root.state_root_dir == os.path.realpath(build_workspace_paths(temp_dir).state_root_dir)
            return _fake_runtime(workspace_root, smol_rag, session_manager)

        with patch("cli.main.WorktreeRunner") as mock_runner_cls, \
            patch("cli.main._build_cli_runtime", side_effect=fake_runtime), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent) as mock_build:
            mock_runner_cls.return_value.create.return_value = fake_ctx
            payload = await _run_once(
                prompt="hello",
                session_key="default",
                workspace=temp_dir,
                model="model",
                agents_config=DEFAULT_AGENTS_CONFIG,
                worktree=True,
            )

        mock_runner_cls.return_value.create.assert_called_once()
        built_workspace = mock_build.call_args.kwargs["workspace"]
        assert isinstance(built_workspace, WorkspaceContext)
        assert built_workspace.root_dir == os.path.realpath(worktree_path)
        assert built_workspace.state_root_dir == os.path.realpath(build_workspace_paths(temp_dir).state_root_dir)
        assert payload["worktree_path"] == worktree_path
        assert payload["worktree_diff"] == "diff --git a/app.py b/app.py"
        assert os.path.realpath(payload["trace_path"]).startswith(
            os.path.realpath(build_workspace_paths(temp_dir).traces_dir)
        )
        assert not os.path.exists(os.path.join(worktree_path, ".smolclaw"))
        fake_ctx.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_tui_chat_loop_worktree_uses_isolated_workspace_and_cleans_up(self, temp_dir):
        from cli.main import DEFAULT_AGENTS_CONFIG, _tui_chat_loop

        worktree_path = os.path.join(temp_dir, "isolated")
        os.makedirs(worktree_path, exist_ok=True)
        fake_ctx = MagicMock()
        fake_ctx.path = worktree_path
        fake_ctx.run_id = "run-1"
        fake_ctx.base_repo = temp_dir
        fake_ctx.created_by_git_worktree = True
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"
        smol_rag = MagicMock()
        session_manager = MagicMock()
        fake_tui = MagicMock()
        fake_tui.run = AsyncMock()

        def fake_runtime(workspace_root, *_args, **_kwargs):
            assert isinstance(workspace_root, WorkspaceContext)
            assert workspace_root.root_dir == os.path.realpath(worktree_path)
            assert workspace_root.state_root_dir == os.path.realpath(build_workspace_paths(temp_dir).state_root_dir)
            return _fake_runtime(workspace_root, smol_rag, session_manager)

        with patch("cli.main.WorktreeRunner") as mock_runner_cls, \
            patch("cli.main._build_cli_runtime", side_effect=fake_runtime), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent) as mock_build, \
            patch("cli.tui.CoderTui", return_value=fake_tui) as mock_tui_cls:
            mock_runner_cls.return_value.create.return_value = fake_ctx
            await _tui_chat_loop(
                "default",
                temp_dir,
                "model",
                agents_config=DEFAULT_AGENTS_CONFIG,
                worktree=True,
            )

        built_workspace = mock_build.call_args.kwargs["workspace"]
        assert isinstance(built_workspace, WorkspaceContext)
        assert built_workspace.root_dir == os.path.realpath(worktree_path)
        assert built_workspace.state_root_dir == os.path.realpath(build_workspace_paths(temp_dir).state_root_dir)
        assert mock_tui_cls.call_args.kwargs["workspace_root"] == os.path.realpath(worktree_path)
        assert mock_tui_cls.call_args.kwargs["resolve_worktree_command"]("status").startswith("Worktree: active")
        fake_tui.run.assert_awaited_once()
        fake_ctx.cleanup.assert_called_once()

    def test_format_trace_status_shows_latest_summary(self, temp_dir):
        from cli.commands import _format_trace_status

        traces_dir = build_workspace_paths(temp_dir).traces_dir
        trace_store = RunTraceStore(traces_dir)
        recorder = trace_store.start_run("default")
        recorder.append("tool.started", {"name": "run_command", "command": "pytest"})
        recorder.append("verification.recorded", {
            "command": "pytest",
            "status": "passed",
            "summary": "tests passed",
        })
        recorder.finish("complete", stop_reason="assistant_final")

        output = _format_trace_status(traces_dir, "default")

        assert f"Trace: {recorder.run_id}" in output
        assert "Status: complete" in output
        assert "Commands: pytest" in output
        assert "Verification records: 1" in output
        assert ".summary.json" in output

    def test_resolve_trace_command_lists_run_summaries(self, temp_dir):
        from cli.main import _resolve_trace_command

        traces_dir = build_workspace_paths(temp_dir).traces_dir
        trace_store = RunTraceStore(traces_dir)
        first = trace_store.start_run("default")
        first.finish("blocked", stop_reason="needs_approval")
        second = trace_store.start_run("default")
        second.append("tool.denied", {"name": "run_command", "reason": "policy"})
        second.finish("complete", stop_reason="assistant_final")

        output = _resolve_trace_command(
            traces_dir,
            "default",
            "list",
        )

        assert "Run traces (2/2):" in output
        assert f"- {second.run_id}: complete" in output
        assert "denied=1" in output
        assert f"- {first.run_id}: blocked" in output

    def test_resolve_trace_command_shows_recent_events(self, temp_dir):
        from cli.main import _resolve_trace_command

        traces_dir = build_workspace_paths(temp_dir).traces_dir
        trace_store = RunTraceStore(traces_dir)
        recorder = trace_store.start_run("default")
        recorder.append("llm.started", {"model": "gpt-test"}, turn_index=1)
        recorder.append("tool.started", {"name": "run_command", "command": "pytest"}, iteration=2)
        recorder.append("verification.recorded", {"status": "passed", "summary": "tests passed"})
        recorder.finish("complete", stop_reason="assistant_final")

        output = _resolve_trace_command(
            traces_dir,
            "default",
            "events 3",
        )

        assert f"Trace events: {recorder.run_id}" in output
        assert "Showing 3/5 event(s)" in output
        assert "tool.started iter=2 name=run_command command=pytest" in output
        assert "verification.recorded status=passed summary=tests passed" in output
        assert "run.ended status=complete stop_reason=assistant_final" in output

    def test_resolve_trace_command_replays_compact_trajectory(self, temp_dir):
        from cli.main import _resolve_trace_command

        traces_dir = build_workspace_paths(temp_dir).traces_dir
        trace_store = RunTraceStore(traces_dir)
        recorder = trace_store.start_run("default")
        recorder.append("turn.started", {"message_length": 12}, turn_index=0)
        recorder.append("llm.started", {"model": "gpt-test"}, turn_index=0, iteration=0)
        recorder.append("tool.started", {"name": "run_command", "command": "pytest"}, iteration=0)
        recorder.append("checkpoint.created", {
            "checkpoint_id": "chk-1",
            "changed_paths": ["app.py"],
            "reason": "fix parser",
        })
        recorder.finish("complete", stop_reason="assistant_final")

        output = _resolve_trace_command(
            traces_dir,
            "default",
            f"replay {recorder.run_id}",
        )

        assert f"Trace replay: {recorder.run_id}" in output
        assert "Status: complete" in output
        assert "turn.started turn=0" in output
        assert "llm.started turn=0 iter=0 model=gpt-test" in output
        assert "tool.started iter=0 name=run_command command=pytest" in output
        assert "checkpoint.created" in output
        assert "checkpoint_id=chk-1" in output
        assert "reason=fix parser" in output
        assert "run.ended status=complete stop_reason=assistant_final" in output

    def test_resolve_approval_command_shows_and_resolves_pending_request(self, temp_dir):
        from cli.main import _resolve_approval_command

        approval_store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
        request = approval_store.request(
            "default",
            tool_name="run_command",
            arguments={"command": "npm install left-pad"},
            reason="dependency changes need approval",
            run_id="run-123",
            matched_subject="command",
            matched_pattern="npm install*",
        )

        status = _resolve_approval_command(approval_store, "default", "status")
        detail = _resolve_approval_command(approval_store, "default", f"detail {request.id}")
        approved = _resolve_approval_command(approval_store, "default", f"approve {request.id}")
        denied = _resolve_approval_command(approval_store, "default", f"deny {request.id}")

        assert request.id in status
        assert "run_command" in status
        assert "command:npm install*" in status
        assert f"Approval: {request.id}" in detail
        assert "Scope: once" in detail
        assert "Run: run-123" in detail
        assert "\"command\": \"npm install left-pad\"" in detail
        assert approved == f"Approved {request.id}. Retry the same tool call to continue."
        assert denied == f"Denied {request.id}."

    @pytest.mark.asyncio
    async def test_resolve_memory_command_reviews_and_resolves_contradictions(self):
        from cli.main import _resolve_memory_command

        detector = MagicMock()
        detector.get_pending = AsyncMock(return_value=[{
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "SmolClaw",
            "existing_value": "uses old memory defaults",
            "new_value": "uses updated memory defaults",
            "verdict": "contradict",
            "confidence": 0.91,
        }])
        detector.resolve = AsyncMock(return_value={"status": "resolved_merged"})
        detector.store.get_by_key = AsyncMock(return_value={
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "SmolClaw",
            "existing_value": "uses old memory defaults",
            "new_value": "uses updated memory defaults",
            "status": "pending",
        })
        smol_rag = MagicMock()
        smol_rag.contradiction_detector = detector

        review = await _resolve_memory_command(smol_rag, "list")
        detail = await _resolve_memory_command(smol_rag, "detail ctr-1")
        resolved = await _resolve_memory_command(smol_rag, "resolve ctr-1 merge reconcile both notes")

        assert "ctr-1" in review
        assert "SmolClaw" in review
        assert "**Contradiction: ctr-1**" in detail
        assert resolved == "Resolved ctr-1 as **resolved_merged**."
        detector.resolve.assert_awaited_once_with("ctr-1", "merge", note="reconcile both notes")

    @pytest.mark.asyncio
    async def test_resolve_memory_command_without_detector_reports_unavailable(self):
        from cli.main import _resolve_memory_command

        smol_rag = MagicMock()
        smol_rag.contradiction_detector = None

        result = await _resolve_memory_command(smol_rag, "review")

        assert "unavailable" in result

    def test_run_command_outputs_json(self, temp_dir):
        from cli.main import app

        async def fake_run_once(**kwargs):
            return {
                "session_key": kwargs["session_key"],
                "status": "complete",
                "response": "done",
                "responses": ["done"],
                "turns": 1,
                "trace_path": None,
                "trace_summary_path": None,
                "ledger_path": None,
                "stop_reason": "assistant_final",
            }

        with patch("cli.main._run_once", side_effect=fake_run_once):
            result = CliRunner().invoke(app, ["run", "hello", "--workspace", temp_dir])

        assert result.exit_code == 0
        assert '"status": "complete"' in result.stdout
        assert '"response": "done"' in result.stdout

    def test_run_command_passes_worktree_options(self, temp_dir):
        from cli.main import app

        async def fake_run_once(**kwargs):
            assert kwargs["worktree"] is True
            assert kwargs["copy_dirty_worktree"] is True
            assert kwargs["keep_worktree"] is True
            return {
                "session_key": kwargs["session_key"],
                "status": "complete",
                "response": "done",
                "responses": ["done"],
                "turns": 1,
                "trace_path": None,
                "trace_summary_path": None,
                "ledger_path": None,
                "stop_reason": "assistant_final",
                "worktree_path": "/tmp/worktree",
                "worktree_diff": "",
            }

        with patch("cli.main._run_once", side_effect=fake_run_once):
            result = CliRunner().invoke(
                app,
                [
                    "run",
                    "hello",
                    "--workspace",
                    temp_dir,
                    "--worktree",
                    "--copy-dirty-worktree",
                    "--keep-worktree",
                ],
            )

        assert result.exit_code == 0
        assert '"worktree_path": "/tmp/worktree"' in result.stdout

    def test_chat_command_passes_worktree_options(self, temp_dir):
        from cli.main import app

        async def fake_tui_chat_loop(*args, **kwargs):
            assert kwargs["worktree"] is True
            assert kwargs["copy_dirty_worktree"] is True
            assert kwargs["keep_worktree"] is True

        with patch("cli.main._tui_chat_loop", side_effect=fake_tui_chat_loop):
            result = CliRunner().invoke(
                app,
                [
                    "chat",
                    "--workspace",
                    temp_dir,
                    "--worktree",
                    "--copy-dirty-worktree",
                    "--keep-worktree",
                ],
            )

        assert result.exit_code == 0

    def test_resolve_worktree_command_status_diff_apply_and_discard(self):
        from cli.main import _InteractiveWorktreeState, _resolve_worktree_command

        ctx = MagicMock()
        ctx.created_by_git_worktree = True
        ctx.run_id = "run-1"
        ctx.path = "/tmp/isolated"
        ctx.base_repo = "/repo/base"
        ctx.diff.return_value = "diff --git a/app.py b/app.py"
        ctx.apply_back.return_value = "Applied isolated diff to base repository."
        state = _InteractiveWorktreeState(
            context=ctx,
            state_root="/repo/base",
            keep_on_exit=True,
        )

        status = _resolve_worktree_command(state, "status")
        diff = _resolve_worktree_command(state, "diff")
        applied = _resolve_worktree_command(state, "apply")
        discarded = _resolve_worktree_command(state, "discard")

        assert "Worktree: active" in status
        assert "Mode: git-worktree" in status
        assert "Source root: /tmp/isolated" in status
        assert "State root: /repo/base" in status
        assert diff == "diff --git a/app.py b/app.py"
        assert applied == "Applied isolated diff to base repository."
        assert state.applied_count == 1
        assert "Discard scheduled" in discarded
        assert state.discard_on_exit is True

    def test_resolve_worktree_command_without_active_worktree(self):
        from cli.main import _resolve_worktree_command

        assert _resolve_worktree_command(None, "status") == "No active isolated worktree."
        assert _resolve_worktree_command(None, "diff") == "No active isolated worktree."

    def test_smolclaw_main_uses_tui_coder_harness(self):
        from cli.main import _smolclaw_main

        async def fake_coro():
            return None

        coro = fake_coro()
        mock_tui = MagicMock(return_value=coro)
        with patch("cli.main._tui_chat_loop", new=mock_tui), \
            patch("cli.main.asyncio.run") as mock_run:
            _smolclaw_main(
                session_key="default",
                workspace=".",
                model="model",
                agents_config="agents.yaml",
                auto_export=True,
                show_actions=True,
            )

        mock_tui.assert_called_once_with(
            session_key="default",
            workspace=".",
            model="model",
            agent_name="coder",
            agents_config="agents.yaml",
            auto_export=True,
            show_actions=True,
            display_label="SmolClaw",
        )
        mock_run.assert_called_once_with(coro)
        coro.close()

    def test_chat_command_uses_tui_loop(self):
        from cli.main import app

        async def fake_coro():
            return None

        coro = fake_coro()
        mock_tui = MagicMock(return_value=coro)
        with patch("cli.main._tui_chat_loop", new=mock_tui), \
            patch("cli.main.asyncio.run") as mock_run:
            result = CliRunner().invoke(app, ["chat", "--session", "s", "--workspace", ".", "--model", "m"])

        assert result.exit_code == 0
        mock_tui.assert_called_once()
        assert mock_tui.call_args.kwargs == {
            "worktree": False,
            "copy_dirty_worktree": False,
            "keep_worktree": False,
        }
        assert mock_tui.call_args.args[:4] == ("s", ".", "m", None)
        assert mock_tui.call_args.args[5] is False
        mock_run.assert_called_once_with(coro)
        coro.close()

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

    def test_build_default_chat_agent_passes_agent_configs_and_subagent_support(
        self, agents_yaml, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        fake_agent = MagicMock()

        with patch("cli.main.build_configured_agent", return_value=fake_agent) as mock_build_configured_agent:
            agent = _build_default_chat_agent(
                agents_config_path=agents_yaml,
                session_key="plain-session",
                model="gpt-5.2-pro",
                smol_rag=mock_smol_rag,
                workspace="/tmp",
                session_manager=sm,
            )

        assert agent is fake_agent
        env = mock_build_configured_agent.call_args.kwargs["env"]
        assert set(env.agent_configs) == {"default", "researcher", "writer"}
        assert env.enable_subagents is True
        assert env.memory_docs_dir == build_workspace_paths("/tmp").memory_docs_dir
        assert env.workspace.root_dir == os.path.realpath(build_workspace_paths("/tmp").root_dir)
        assert env.llm_db_path == build_workspace_paths("/tmp").sqlite_db_path

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
        fake_agent.smol_rag = smol_rag = MagicMock()
        smol_rag.contradiction_detector = None

        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
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
        assert len(fake_agent.hook_runner._hooks[ON_SESSION_END]) == 2
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_skips_export_hook_for_memoryless_multiagent(self):
        from cli.main import _chat_loop

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
        fake_agent.smol_rag = None

        smol_rag = MagicMock()
        smol_rag.contradiction_detector = None
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_multiagent", return_value=fake_agent), \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("default", "/tmp", "model", agent_name="researcher", auto_export=True)

        assert ON_SESSION_END in fake_agent.hook_runner.events
        assert len(fake_agent.hook_runner._hooks[ON_SESSION_END]) == 1
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
        fake_agent.smol_rag = smol_rag = MagicMock()
        smol_rag.contradiction_detector = None
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
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
        fake_agent.smol_rag = smol_rag = MagicMock()
        smol_rag.contradiction_detector = None
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
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
        assert len(fake_agent.hook_runner._hooks[ON_SESSION_END]) == 2
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_uses_workspace_scoped_paths(self, temp_dir):
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

        workspace_root = os.path.join(temp_dir, "topic-a")
        expected = build_workspace_paths(workspace_root)
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.session = MagicMock()
        fake_agent.smol_rag = smol_rag = MagicMock()
        smol_rag.contradiction_detector = None
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime(workspace_root, smol_rag, session_manager)) as mock_build_runtime, \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("default", workspace_root, "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        mock_build_runtime.assert_called_once()
        runtime = mock_build_runtime.return_value
        assert runtime.workspace.paths.sqlite_db_path == expected.sqlite_db_path
        assert runtime.workspace.paths.kg_db_path == expected.kg_db_path
        assert runtime.workspace.paths.research_dir == expected.research_dir
        assert runtime.workspace.paths.log_dir == expected.log_dir
        assert runtime.session_manager is session_manager

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

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
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
    async def test_chat_loop_memory_list_lists_contradictions_without_agent_turn(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/memory list"])

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
        fake_agent.session.key = "default"

        detector = MagicMock()
        detector.get_pending = AsyncMock(return_value=[{
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "SmolClaw",
            "existing_value": "old",
            "new_value": "new",
            "verdict": "contradict",
            "confidence": 0.8,
        }])
        smol_rag = MagicMock()
        smol_rag.contradiction_detector = detector
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        output = "\n".join(fake_console.lines)
        assert "ctr-1" in output
        assert "SmolClaw" in output
        fake_agent.process.assert_not_called()
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_memory_review_runs_agent_conversation_turn(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/memory review SmolClaw defaults"])

            async def prompt_async(self, _prompt):
                try:
                    return next(self._inputs)
                except StopIteration:
                    raise EOFError

        class FakeConsole:
            file = MagicMock()

            def status(self, *args, **kwargs):
                return nullcontext()

            def print(self, *args, **kwargs):
                return None

        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.process = AsyncMock(return_value="reconciled")
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"

        smol_rag = MagicMock()
        smol_rag.contradiction_detector = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        prompt = fake_agent.process.await_args.args[0]
        assert "Review pending memory contradictions conversationally" in prompt
        assert "contradiction_review" in prompt
        assert "Do not call contradiction_review with action=resolve" in prompt
        assert "SmolClaw defaults" in prompt
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_memory_reconcile_alias_runs_agent_conversation_turn(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/memory reconcile SmolClaw defaults"])

            async def prompt_async(self, _prompt):
                try:
                    return next(self._inputs)
                except StopIteration:
                    raise EOFError

        class FakeConsole:
            file = MagicMock()

            def status(self, *args, **kwargs):
                return nullcontext()

            def print(self, *args, **kwargs):
                return None

        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.process = AsyncMock(return_value="reconciled")
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"

        smol_rag = MagicMock()
        smol_rag.contradiction_detector = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", FakeConsole()):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        prompt = fake_agent.process.await_args.args[0]
        assert "Review pending memory contradictions conversationally" in prompt
        assert "SmolClaw defaults" in prompt
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

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
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

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        help_output = "\n".join(fake_console.lines)
        assert "Slash commands:" in help_output
        assert "/remember <text>" in help_output
        assert "/remember-thread" in help_output
        assert "/memory list" in help_output
        assert "/memory review" in help_output
        assert "/init" in help_output
        assert "/trace replay" in help_output
        assert "/quit or /exit" in help_output
        fake_agent.process.assert_not_called()
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_init_command_creates_project_guidance(self, temp_dir):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/init", "/quit"])

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
        fake_agent.session.key = "default"

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime(temp_dir, smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", temp_dir, "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        output = "\n".join(fake_console.lines)
        assert "Created" in output
        assert os.path.exists(os.path.join(temp_dir, "AGENTS.md"))
        fake_agent.process.assert_not_called()
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_trace_command_shows_latest_trace(self, temp_dir):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/trace", "/quit"])

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

        trace_store = RunTraceStore(build_workspace_paths(temp_dir).traces_dir)
        recorder = trace_store.start_run("default")
        recorder.finish("complete", stop_reason="assistant_final")
        fake_console = FakeConsole()
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.process = AsyncMock()
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime(temp_dir, smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", temp_dir, "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        output = "\n".join(fake_console.lines)
        assert f"Trace: {recorder.run_id}" in output
        assert "Status: complete" in output
        fake_agent.process.assert_not_called()
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_undo_command_uses_checkpoint_store(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/undo", "/quit"])

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
        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.message = "Undid checkpoint chk-1; restored 1 path."
        fake_result.restored_paths = ["/tmp/file.txt"]
        fake_result.conflicts = []
        checkpoint_store = MagicMock()
        checkpoint_store.undo_last.return_value = fake_result
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.process = AsyncMock()
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"
        fake_agent.session_usage = None

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.CheckpointStore", return_value=checkpoint_store), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        checkpoint_store.undo_last.assert_called_once_with(session_key="default")
        output = "\n".join(fake_console.lines)
        assert "Undid checkpoint chk-1; restored 1 path." in output
        assert "/tmp/file.txt" in output
        fake_agent.process.assert_not_called()
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_model_subagents_command_updates_subagent_default(self):
        from cli.main import DEFAULT_AGENTS_CONFIG, _chat_loop

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/model subagents gpt-5.4-pro high", "/quit"])

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
        fake_agent.llm.completion_model = "gpt-test"
        fake_agent.llm.reasoning_effort = None
        fake_agent.model_settings = RuntimeModelSettings()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.process = AsyncMock()
        fake_agent.session = MagicMock()
        fake_agent.session_usage = None

        smol_rag = MagicMock()
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True)

        selection = fake_agent.model_settings.resolve("fallback", subagent=True)
        assert selection.model == "gpt-5.4-pro"
        assert selection.reasoning_effort == "high"
        assert fake_agent.llm.completion_model == "gpt-test"
        assert "Switched subagents model:gpt-5.4-pro effort:high" in "\n".join(fake_console.lines)
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

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
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

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True, show_actions=True)

        output = "\n".join(fake_console.lines)
        assert "action: web_fetch url=https://example.com/docs" in output
        assert "done: web_fetch (0.4s)" in output
        fake_agent.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_loop_goal_run_continues_until_goal_completes(self, temp_dir):
        from cli.main import DEFAULT_AGENTS_CONFIG, _build_goal_loop_prompt, _chat_loop
        from app.goal_ledger import GoalLedgerStore

        class FakePromptSession:
            def __init__(self, **kwargs):
                self._inputs = iter(["/goal start Finish the goal loop", "/goal run 3", "/quit"])

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

        prompt_outputs = []
        goal_store = GoalLedgerStore(os.path.join(temp_dir, "ledgers"))

        async def fake_process(message, on_output=None, on_event=None):
            prompt_outputs.append(message)
            if len(prompt_outputs) == 2:
                goal_store.update("default", status="complete", note="done")
            return f"response {len(prompt_outputs)}"

        fake_console = FakeConsole()
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.close = AsyncMock()
        fake_agent.process = AsyncMock(side_effect=fake_process)
        fake_agent.session = MagicMock()
        fake_agent.session.key = "default"
        fake_agent.session.clear = MagicMock()
        fake_agent.session_usage = None

        smol_rag = MagicMock()
        smol_rag.contradiction_detector = None
        session_manager = MagicMock()

        with patch("cli.main._build_cli_runtime", return_value=_fake_runtime("/tmp", smol_rag, session_manager)), \
            patch("cli.main.PromptSession", FakePromptSession), \
            patch("cli.main._build_default_chat_agent", return_value=fake_agent), \
            patch("cli.main.GoalLedgerStore", return_value=goal_store), \
            patch("cli.main.console", fake_console):
            await _chat_loop("default", "/tmp", "model", agents_config=DEFAULT_AGENTS_CONFIG, auto_export=True, show_actions=True)

        assert len(prompt_outputs) == 2
        assert prompt_outputs[0] == _build_goal_loop_prompt()
        assert prompt_outputs[1] == prompt_outputs[0]
        assert goal_store.load("default").status == "complete"
        output = "\n".join(fake_console.lines)
        assert "Goal turn 1/3" in output
        assert "Goal turn 2/3" in output
        assert "Status: complete" in output
        fake_agent.close.assert_awaited_once()
