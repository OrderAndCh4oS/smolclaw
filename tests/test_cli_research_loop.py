import os
from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from app.hooks import ON_SESSION_END, HookRunner
from app.workspace import WorkspaceContext


def _fake_runtime(workspace_root: str, smol_rag, session_manager):
    runtime = MagicMock()
    runtime.workspace = WorkspaceContext.from_root(workspace_root).ensure_dirs()
    runtime.smol_rag = smol_rag
    runtime.session_manager = session_manager
    return runtime


class FakeConsoleStream:
    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(text)

    def flush(self):
        return None


class FakeConsole:
    def __init__(self):
        self.lines = []
        self.file = FakeConsoleStream()

    def status(self, *args, **kwargs):
        return nullcontext()

    def print(self, *args, **kwargs):
        self.lines.append(" ".join(str(arg) for arg in args))


class FakeStopController:
    def __init__(self, *, wait_results=None, reason="Stopped: Escape pressed."):
        self._wait_results = list(wait_results or [])
        self._reason = reason
        self._stop_requested = False

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @property
    def reason(self) -> str:
        return self._reason

    def request_stop(self, reason: str):
        self._stop_requested = True
        self._reason = reason

    async def wait(self, timeout=None) -> bool:
        _ = timeout
        if self._wait_results:
            should_stop = self._wait_results.pop(0)
            if should_stop:
                self._stop_requested = True
            return should_stop
        return self._stop_requested


class FakeEscWatcher:
    def __init__(self, active=False):
        self.active = active
        self.close = MagicMock()


def _make_agent(process_side_effect, smol_rag):
    agent = MagicMock()
    agent.llm = MagicMock()
    agent.hook_runner = HookRunner()
    agent.close = AsyncMock()
    agent.process = AsyncMock(side_effect=process_side_effect)
    agent.request_stop = MagicMock()
    agent.session = MagicMock()
    agent.session.key = "research-loop"
    agent.session_usage = None
    agent.smol_rag = smol_rag
    return agent


def test_research_loop_help_renders():
    from cli.main import app

    result = CliRunner().invoke(app, ["research-loop", "--help"])

    assert result.exit_code == 0
    assert "Run recurring automated research until stopped." in result.stdout
    assert "--interval" in result.stdout
    assert "--max-runs" in result.stdout


def test_build_research_loop_prompt_emphasizes_delta_after_first_run():
    from cli.main import _build_research_loop_prompt

    first_prompt = _build_research_loop_prompt("Track UK AI regulation updates.", 0)
    followup_prompt = _build_research_loop_prompt("Track UK AI regulation updates.", 1)

    assert "Run number: 1" in first_prompt
    assert "Search memory first" in first_prompt
    assert "Run number: 2" in followup_prompt
    assert "Review prior session context and memory first." in followup_prompt
    assert "important delta" in followup_prompt


@pytest.mark.asyncio
async def test_research_loop_runs_until_max_runs(temp_dir):
    from cli.main import _research_loop

    workspace_root = os.path.join(temp_dir, "workspace")
    fake_console = FakeConsole()
    stop_controller = FakeStopController(wait_results=[False])
    esc_watcher = FakeEscWatcher(active=False)
    prompts = []
    smol_rag = MagicMock()
    smol_rag.close = AsyncMock()
    smol_rag.contradiction_detector = None
    session_manager = MagicMock()

    async def fake_process(prompt, on_output=None, on_event=None):
        prompts.append(prompt)
        if on_output:
            await on_output(f"cycle {len(prompts)}")
        return f"cycle {len(prompts)}"

    fake_agent = _make_agent(fake_process, smol_rag)

    with patch("cli.main._build_cli_runtime", return_value=_fake_runtime(workspace_root, smol_rag, session_manager)), \
        patch("cli.main._build_multiagent", return_value=fake_agent), \
        patch("cli.main._create_research_loop_stop_controller", return_value=(stop_controller, esc_watcher)), \
        patch("cli.main.console", fake_console):
        await _research_loop(
            goal="Track UK AI regulation updates.",
            workspace=workspace_root,
            agent_name="researcher",
            session_key="research-loop",
            interval=0.01,
            max_runs=2,
            auto_export=True,
            show_actions=False,
        )

    assert len(prompts) == 2
    assert "Run number: 1" in prompts[0]
    assert "Run number: 2" in prompts[1]
    assert ON_SESSION_END in fake_agent.hook_runner.events
    assert len(fake_agent.hook_runner._hooks[ON_SESSION_END]) == 2
    assert "Completed requested run limit after 2 cycle(s)." in "\n".join(fake_console.lines)
    fake_agent.close.assert_awaited_once()
    smol_rag.close.assert_awaited_once()
    esc_watcher.close.assert_called_once()


@pytest.mark.asyncio
async def test_research_loop_stops_cleanly_between_cycles(temp_dir):
    from cli.main import _research_loop

    workspace_root = os.path.join(temp_dir, "workspace")
    fake_console = FakeConsole()
    stop_controller = FakeStopController(wait_results=[True], reason="Stopped: Escape pressed.")
    esc_watcher = FakeEscWatcher(active=True)
    smol_rag = MagicMock()
    smol_rag.close = AsyncMock()
    smol_rag.contradiction_detector = None
    session_manager = MagicMock()

    async def fake_process(prompt, on_output=None, on_event=None):
        _ = prompt, on_output, on_event
        return "cycle 1"

    fake_agent = _make_agent(fake_process, smol_rag)

    with patch("cli.main._build_cli_runtime", return_value=_fake_runtime(workspace_root, smol_rag, session_manager)), \
        patch("cli.main._build_multiagent", return_value=fake_agent), \
        patch("cli.main._create_research_loop_stop_controller", return_value=(stop_controller, esc_watcher)), \
        patch("cli.main.console", fake_console):
        await _research_loop(
            goal="Track UK AI regulation updates.",
            workspace=workspace_root,
            agent_name="researcher",
            session_key="research-loop",
            interval=0.01,
            max_runs=None,
            auto_export=False,
            show_actions=False,
        )

    fake_agent.process.assert_awaited_once()
    fake_agent.request_stop.assert_not_called()
    assert "Stopped: Escape pressed. Completed 1 cycle(s)." in "\n".join(fake_console.lines)


@pytest.mark.asyncio
async def test_research_loop_requests_agent_stop_when_signaled_mid_cycle(temp_dir):
    from cli.main import _research_loop

    workspace_root = os.path.join(temp_dir, "workspace")
    fake_console = FakeConsole()
    stop_controller = FakeStopController()
    esc_watcher = FakeEscWatcher(active=False)
    smol_rag = MagicMock()
    smol_rag.close = AsyncMock()
    smol_rag.contradiction_detector = None
    session_manager = MagicMock()

    async def fake_process(prompt, on_output=None, on_event=None):
        _ = prompt, on_output
        stop_controller.request_stop("Stopped: Escape pressed.")
        if on_event:
            await on_event({"type": "llm", "phase": "start", "iteration": 0})
        return "cycle 1"

    fake_agent = _make_agent(fake_process, smol_rag)

    with patch("cli.main._build_cli_runtime", return_value=_fake_runtime(workspace_root, smol_rag, session_manager)), \
        patch("cli.main._build_multiagent", return_value=fake_agent), \
        patch("cli.main._create_research_loop_stop_controller", return_value=(stop_controller, esc_watcher)), \
        patch("cli.main.console", fake_console):
        await _research_loop(
            goal="Track UK AI regulation updates.",
            workspace=workspace_root,
            agent_name="researcher",
            session_key="research-loop",
            interval=0.01,
            max_runs=None,
            auto_export=False,
            show_actions=False,
        )

    fake_agent.process.assert_awaited_once()
    fake_agent.request_stop.assert_called_once()
    assert "Stopped: Escape pressed. Completed 1 cycle(s)." in "\n".join(fake_console.lines)
