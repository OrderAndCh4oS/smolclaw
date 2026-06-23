from unittest.mock import AsyncMock, MagicMock

import asyncio
import logging
import os
import sys
import pytest

from cli.tui import ActivityEntry, CoderTui, DETAILS_HEIGHT, TranscriptEntry, UiState, _fit_line
from app.model_settings import RuntimeModelSettings


def _fake_tui(show_actions=False):
    agent = MagicMock()
    agent.llm.completion_model = "gpt-test"
    agent.llm.reasoning_effort = None
    agent.model_settings = RuntimeModelSettings()
    agent.session.key = "session"
    agent.safety_state = object()
    goal_store = MagicMock()
    goal_store.load.return_value = None
    checkpoint_store = MagicMock()
    checkpoint_store.undo_last.return_value.ok = True
    checkpoint_store.undo_last.return_value.message = "Undid checkpoint chk-1; restored 1 path."
    checkpoint_store.undo_last.return_value.restored_paths = ["/tmp/file.txt"]
    checkpoint_store.undo_last.return_value.conflicts = []
    return CoderTui(
        agent=agent,
        goal_store=goal_store,
        session_manager=MagicMock(),
        memory_store_tool=MagicMock(),
        session_export_hook=MagicMock(),
        smol_rag=MagicMock(),
        checkpoint_store=checkpoint_store,
        approval_store=MagicMock(),
        workspace_root=".",
        log_dir="./.smolclaw/stores/logs",
        model="fallback-model",
        auto_export=True,
        show_actions=show_actions,
        slash_commands_help="help",
        format_goal_status=lambda goal: "No goal" if goal is None else goal.status,
        parse_goal_run_count=lambda value: int(value or "3"),
        build_goal_loop_prompt=lambda: "continue goal",
        format_trace_status=lambda session_key, arg: f"Trace for {session_key} {arg}".strip(),
        resolve_approval_command=lambda session_key, arg: f"Approval {session_key} {arg}".strip(),
        resolve_worktree_command=lambda arg: f"Worktree {arg}".strip(),
        initialize_project=lambda: "Created AGENTS.md",
        format_action_event=lambda event: event.get("line"),
        label="SmolClaw",
    )


def test_tui_status_bars_include_satellite_info():
    tui = _fake_tui()
    tui.state = UiState(
        label="SmolClaw",
        mode="coder",
        model="gpt-test",
        cwd="~/code/smolclaw",
        git_state="git:main*",
        goal_state="goal:2",
        token_total=12400,
        active_tool="grep_search",
        activity="searching",
        safety_state="safety:gated",
        run_state="running",
    )

    top = "".join(text for _, text in tui._render_top_bar())
    bottom = "".join(text for _, text in tui._render_bottom_bar())

    assert "SmolClaw" in top
    assert "coder" in top
    assert "gpt-test" in top
    assert "~/code/smolclaw" in top
    assert "git:main*" in top
    assert "goal:2" in top
    assert "tok:12,400" in bottom
    assert "tools:grep_search" in bottom
    assert "safety:gated" in bottom
    assert "spin:|" in bottom
    assert "details:off" in bottom
    assert "status:searching" in bottom


def test_tui_top_bar_shows_reasoning_effort_when_set():
    tui = _fake_tui()
    tui.state.reasoning_effort = "high"

    top = "".join(text for _, text in tui._render_top_bar())

    assert "effort:high" in top


def test_tui_status_bars_pad_to_terminal_width(monkeypatch):
    tui = _fake_tui()
    monkeypatch.setattr("cli.tui.shutil.get_terminal_size", lambda fallback: os.terminal_size((80, 10)))

    long_bottom = "".join(text for _, text in tui._render_bottom_bar())
    tui.state.active_tool = "idle"
    tui.state.run_state = "idle"
    short_bottom = "".join(text for _, text in tui._render_bottom_bar())

    assert len(long_bottom) == 80
    assert len(short_bottom) == 80
    assert short_bottom.endswith(" ")


def test_tui_spinner_is_idle_marker_when_idle():
    tui = _fake_tui()
    tui.state.activity = "idle"
    tui.state.spinner_index = 2

    bottom = "".join(text for _, text in tui._render_bottom_bar())

    assert "spin:." in bottom


def test_tui_spinner_runs_while_shutting_down():
    tui = _fake_tui()
    tui.state.activity = "shutting down"
    tui.state.spinner_index = 1

    bottom = "".join(text for _, text in tui._render_bottom_bar())

    assert "spin:/" in bottom
    assert "status:shutting down" in bottom


@pytest.mark.asyncio
async def test_tui_spinner_advances_while_active():
    tui = _fake_tui()
    tui.state.activity = "running"
    task = asyncio.create_task(tui._animate_spinner())

    try:
        await asyncio.sleep(0.25)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert tui.state.spinner_index != 0


@pytest.mark.asyncio
async def test_tui_shutdown_reports_close_phases():
    tui = _fake_tui()
    tui.agent.close = AsyncMock()
    tui.smol_rag.close = AsyncMock()

    await tui._shutdown()

    rendered = "".join(text for _, text in tui._render_transcript())
    activity = "\n".join(entry.text for entry in tui.state.activity_log)
    assert "Closing agent session and hooks." in rendered
    assert "Closing memory stores." in rendered
    assert "Shutdown complete." in activity
    assert tui.state.run_state == "idle"
    assert tui.state.activity == "idle"


@pytest.mark.asyncio
async def test_tui_shutdown_stops_running_agent_turn():
    tui = _fake_tui()
    never_finishes = asyncio.create_task(asyncio.sleep(60))
    tui._agent_task = never_finishes
    tui.agent.close = AsyncMock()
    tui.smol_rag.close = AsyncMock()

    await tui._shutdown()

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Stopping active agent turn." in rendered
    tui.agent.request_stop.assert_called_once()
    assert never_finishes.cancelled()


@pytest.mark.asyncio
async def test_tui_shutdown_times_out_hung_agent_close(monkeypatch):
    tui = _fake_tui()
    monkeypatch.setattr("cli.tui.SHUTDOWN_PHASE_TIMEOUT", 0.01)

    async def never_closes():
        await asyncio.sleep(60)

    tui.agent.close = never_closes
    tui.smol_rag.close = AsyncMock()

    await tui._shutdown()

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Timed out while closing agent session and hooks; continuing shutdown." in rendered
    assert "Closing memory stores." in rendered
    assert tui.state.run_state == "idle"
    assert tui.state.activity == "idle"


@pytest.mark.asyncio
async def test_tui_force_exit_cancels_active_shutdown():
    tui = _fake_tui()
    tui._app = MagicMock()
    tui.state.run_state = "shutting_down"
    tui.state.activity = "shutting down"
    shutdown_task = asyncio.create_task(asyncio.sleep(60))
    tui._shutdown_task = shutdown_task

    tui._force_exit()
    await asyncio.sleep(0)

    assert shutdown_task.cancelled()
    assert tui._shutdown_forced is True
    assert tui.state.run_state == "idle"
    assert tui.state.activity == "idle"
    tui._app.exit.assert_called_once()


def test_fit_line_removes_stale_suffix_when_value_shrinks():
    previous = _fit_line("tools:memory_search running", 16)
    current = _fit_line("tools:idle", 16)

    assert len(previous) == 16
    assert len(current) == 16
    assert current == "tools:idle      "


def test_tui_transcript_renders_user_assistant_system_and_errors():
    tui = _fake_tui()
    tui.state.transcript = [
        TranscriptEntry(kind="user", title="you", text="hello"),
        TranscriptEntry(kind="assistant", title="smolclaw", text="hi"),
        TranscriptEntry(kind="system", text="Session note"),
        TranscriptEntry(kind="error", text="Error: failed"),
    ]

    rendered = "".join(text for _, text in tui._render_transcript())

    assert "you" in rendered
    assert "hello" in rendered
    assert "smolclaw" in rendered
    assert "hi" in rendered
    assert "Session note" in rendered
    assert "Error: failed" in rendered


@pytest.mark.asyncio
async def test_tui_logs_command_shows_workspace_diagnostics_paths():
    tui = _fake_tui()

    await tui.submit("/logs")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Diagnostics logs:" in rendered
    assert "events.jsonl" in rendered
    assert "smolclaw.log" in rendered


@pytest.mark.asyncio
async def test_tui_remember_thread_shows_slow_export_notice():
    tui = _fake_tui()
    tui.session_export_hook = AsyncMock()

    await tui.submit("/remember-thread")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Exporting current thread to memory" in rendered
    assert "Current thread exported to memory." in rendered
    tui.session_export_hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_tui_remember_thread_reports_export_failure():
    tui = _fake_tui()
    tui.session_export_hook = AsyncMock(side_effect=RuntimeError("export failed"))

    await tui.submit("/remember-thread")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Exporting current thread to memory" in rendered
    assert "incident" in rendered
    assert "export failed" in rendered


@pytest.mark.asyncio
async def test_tui_init_command_initializes_project_guidance():
    tui = _fake_tui()

    await tui.submit("/init")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Created AGENTS.md" in rendered


@pytest.mark.asyncio
async def test_tui_trace_command_shows_latest_trace_status():
    tui = _fake_tui()

    await tui.submit("/trace")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Trace for session" in rendered


@pytest.mark.asyncio
async def test_tui_trace_command_forwards_subcommand():
    tui = _fake_tui()

    await tui.submit("/trace events 5")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Trace for session events 5" in rendered


@pytest.mark.asyncio
async def test_tui_approval_command_shows_approval_status():
    tui = _fake_tui()

    await tui.submit("/approval status")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Approval session status" in rendered


@pytest.mark.asyncio
async def test_tui_worktree_command_shows_worktree_status():
    tui = _fake_tui()

    await tui.submit("/worktree status")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Worktree status" in rendered


@pytest.mark.asyncio
async def test_tui_undo_command_uses_checkpoint_store():
    tui = _fake_tui()

    await tui.submit("/undo")

    tui.checkpoint_store.undo_last.assert_called_once_with(session_key="session")
    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Undid checkpoint chk-1; restored 1 path." in rendered
    assert "/tmp/file.txt" in rendered


def test_tui_transcript_clips_to_available_terminal_height(monkeypatch):
    tui = _fake_tui()
    monkeypatch.setattr("cli.tui.shutil.get_terminal_size", lambda fallback: os.terminal_size((40, 9)))
    tui.state.transcript = [
        TranscriptEntry(kind="system", text=f"line {index}")
        for index in range(20)
    ]

    rendered_lines = "".join(text for _, text in tui._render_transcript()).splitlines()

    assert len(rendered_lines) <= 4
    assert "line 19" in "\n".join(rendered_lines)
    assert "line 0" not in "\n".join(rendered_lines)


def test_tui_builds_prompt_toolkit_application():
    tui = _fake_tui()

    app = tui._build_app()

    assert app is not None
    assert app.full_screen is True


def test_tui_layout_keeps_bars_and_input_exact_height():
    tui = _fake_tui()

    app = tui._build_app()
    top_bar, transcript, details, bottom_bar, input_area = app.layout.container.children
    prompt_window, input_window = input_area.children

    assert top_bar.height.min == top_bar.height.max == 1
    assert details.content.height.min == details.content.height.max == DETAILS_HEIGHT
    assert bottom_bar.height.min == bottom_bar.height.max == 1
    assert input_area.height.min == input_area.height.max == 3
    assert prompt_window.height.min == prompt_window.height.max == 3
    assert input_window.height.min == input_window.height.max == 3
    assert transcript.dont_extend_height()
    assert input_window.ignore_content_height()


@pytest.mark.asyncio
async def test_tui_details_command_toggles_activity_pane():
    tui = _fake_tui()

    assert tui.state.details_visible is False

    await tui.submit("/details")

    assert tui.state.details_visible is True
    assert "Tool details shown." in "".join(text for _, text in tui._render_transcript())
    assert "details:on" in "".join(text for _, text in tui._render_bottom_bar())

    await tui.submit("/details")

    assert tui.state.details_visible is False
    assert "Tool details hidden." in "".join(text for _, text in tui._render_transcript())
    assert "details:off" in "".join(text for _, text in tui._render_bottom_bar())


@pytest.mark.asyncio
async def test_tui_model_command_switches_model_and_effort():
    tui = _fake_tui()

    await tui.submit("/model gpt-5.5 high")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert tui.agent.llm.completion_model == "gpt-5.5"
    assert tui.agent.llm.reasoning_effort == "high"
    assert tui.state.model == "gpt-5.5"
    assert tui.state.reasoning_effort == "high"
    assert "Switched model:gpt-5.5 effort:high" in rendered


@pytest.mark.asyncio
async def test_tui_model_subagents_command_switches_subagent_default_only():
    tui = _fake_tui()

    await tui.submit("/model subagents gpt-5.4-pro high")

    rendered = "".join(text for _, text in tui._render_transcript())
    subagent_selection = tui.agent.model_settings.resolve("fallback", subagent=True)
    assert subagent_selection.model == "gpt-5.4-pro"
    assert subagent_selection.reasoning_effort == "high"
    assert tui.agent.llm.completion_model == "gpt-test"
    assert tui.state.model == "gpt-test"
    assert "Switched subagents model:gpt-5.4-pro effort:high" in rendered


@pytest.mark.asyncio
async def test_tui_model_command_rejects_non_gpt_54_or_55_model():
    tui = _fake_tui()

    await tui.submit("/model gpt-4.1 high")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Error: Model must start with gpt-5.4 or gpt-5.5." in rendered
    assert tui.agent.llm.completion_model == "gpt-test"


def test_tui_details_pane_renders_recent_activity_without_transcript():
    tui = _fake_tui()
    tui.state.activity_log = [
        ActivityEntry(kind="system", text="thinking..."),
        ActivityEntry(kind="tool", text="action: grep_search query=hello"),
        ActivityEntry(kind="tool", text="done: grep_search (0.1s)"),
        ActivityEntry(kind="tool", text="failed: web_search (1.0s) - timeout"),
    ]

    details = "".join(text for _, text in tui._render_details())
    transcript = "".join(text for _, text in tui._render_transcript())

    assert "details  /details to hide" in details
    assert "action: grep_search query=hello" in details
    assert "done: grep_search (0.1s)" in details
    assert "failed: web_search (1.0s) - timeout" in details
    assert "action: grep_search query=hello" not in transcript


def test_tui_transcript_height_accounts_for_details_pane(monkeypatch):
    tui = _fake_tui()
    monkeypatch.setattr("cli.tui.shutil.get_terminal_size", lambda fallback: os.terminal_size((40, 12)))

    tui.state.details_visible = False
    hidden_height = tui._transcript_height()
    tui.state.details_visible = True
    visible_height = tui._transcript_height()

    assert hidden_height == 7
    assert visible_height == 3


def test_tui_transcript_scrolls_and_clamps(monkeypatch):
    tui = _fake_tui()
    monkeypatch.setattr("cli.tui.shutil.get_terminal_size", lambda fallback: os.terminal_size((40, 9)))
    tui.state.transcript = [
        TranscriptEntry(kind="system", text=f"line {index}")
        for index in range(20)
    ]

    assert tui._scroll_offset == 0
    tui._scroll_lines(3)
    assert tui._scroll_offset == 3

    tui._scroll_page(up=True)
    assert tui._scroll_offset == 6

    tui._scroll_lines(1000)
    assert tui._scroll_offset == tui._max_scroll_offset()

    tui._scroll_page(up=False)
    assert tui._scroll_offset < tui._max_scroll_offset()

    tui._scroll_lines(-1000)
    assert tui._scroll_offset == 0


def test_tui_suppresses_internal_logs_while_fullscreen_active():
    tui = _fake_tui()
    app_logger = logging.getLogger("app")
    smolclaw_logger = logging.getLogger("smolclaw")
    rag_logger = logging.getLogger("smolclaw.rag")
    app_propagate = app_logger.propagate
    smolclaw_propagate = smolclaw_logger.propagate
    rag_propagate = rag_logger.propagate

    with tui._suppress_terminal_logs():
        assert tui._terminal_log_handler in app_logger.handlers
        assert tui._terminal_log_handler in smolclaw_logger.handlers
        assert tui._terminal_log_handler in rag_logger.handlers
        assert app_logger.propagate is False
        assert smolclaw_logger.propagate is False
        assert rag_logger.propagate is False

    assert tui._terminal_log_handler not in app_logger.handlers
    assert tui._terminal_log_handler not in smolclaw_logger.handlers
    assert tui._terminal_log_handler not in rag_logger.handlers
    assert app_logger.propagate is app_propagate
    assert smolclaw_logger.propagate is smolclaw_propagate
    assert rag_logger.propagate is rag_propagate


@pytest.mark.asyncio
async def test_tui_loop_exceptions_render_as_transcript_errors():
    tui = _fake_tui()
    loop = asyncio.get_running_loop()

    with tui._handle_loop_exceptions():
        loop.call_exception_handler({"exception": RuntimeError("layout safe")})

    rendered = "".join(text for _, text in tui._render_transcript())
    assert "Error: incident inc-" in rendered
    assert "layout safe" in rendered


@pytest.mark.asyncio
async def test_tui_captures_stderr_as_transcript_errors():
    tui = _fake_tui()
    original_stderr = sys.stderr

    with tui._capture_stderr():
        sys.stderr.write("raw traceback line\n")
    await asyncio.sleep(0)

    rendered = "".join(text for _, text in tui._render_transcript())
    assert sys.stderr is original_stderr
    assert "Error: incident inc-" in rendered
    assert "raw traceback line" in rendered


@pytest.mark.asyncio
async def test_tui_submit_streams_agent_events_without_real_llm():
    tui = _fake_tui()
    process_prompts = []

    async def fake_process(prompt, on_output=None, on_event=None):
        process_prompts.append(prompt)
        await on_event({"type": "llm", "phase": "start", "line": "thinking..."})
        await on_output("Plan: search the repo first.")
        await on_event({
            "type": "llm",
            "phase": "end",
            "model": "gpt-test",
            "total_tokens": 3,
            "has_tool_calls": True,
            "line": "thought: 3 tokens",
        })
        await on_event({
            "type": "tool",
            "phase": "start",
            "name": "grep_search",
            "line": "action: grep_search query=hello",
        })
        await on_event({
            "type": "tool",
            "phase": "end",
            "name": "grep_search",
            "line": "done: grep_search (0.1s)",
        })
        await on_event({"type": "llm", "phase": "start", "line": "thinking..."})
        await on_output("Final answer.")
        await on_event({
            "type": "llm",
            "phase": "end",
            "model": "gpt-test",
            "total_tokens": 4,
            "has_tool_calls": False,
            "line": "thought: 4 tokens",
        })
        return "Final answer."

    tui.agent.process = fake_process

    await tui.submit("say hello")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert process_prompts == ["say hello"]
    assert "say hello" in rendered
    assert "Final answer." in rendered
    assert "Plan: search the repo first." not in rendered
    details = "".join(text for _, text in tui._render_details())
    assert "action: grep_search query=hello" not in rendered
    assert "done: grep_search (0.1s)" not in rendered
    assert "thought: 4 tokens" not in rendered
    assert any(entry.text == "Plan: search the repo first." for entry in tui.state.activity_log)
    activity_text = "\n".join(entry.text for entry in tui.state.activity_log)
    assert "action: grep_search query=hello" in activity_text
    assert "done: grep_search (0.1s)" in activity_text
    assert "thought: 3 tokens" in activity_text
    assert "thought: 4 tokens" in details
    assert tui.state.token_total == 7
    assert tui.state.active_tool == "idle"
    assert tui.state.run_state == "idle"
    assert tui.state.activity == "idle"


@pytest.mark.asyncio
async def test_tui_bottom_bar_shows_thinking_and_tool_activity():
    tui = _fake_tui()

    await tui._handle_agent_event({"type": "llm", "phase": "start", "line": "thinking..."})
    bottom = "".join(text for _, text in tui._render_bottom_bar())

    assert "status:thinking" in bottom
    assert "thinking..." not in "".join(text for _, text in tui._render_transcript())

    await tui._handle_agent_event({
        "type": "tool",
        "phase": "start",
        "name": "web_search",
        "line": "action: web_search query=editors",
    })
    bottom = "".join(text for _, text in tui._render_bottom_bar())

    assert "tools:web_search" in bottom
    assert "status:searching" in bottom

    await tui._handle_agent_event({
        "type": "tool",
        "phase": "end",
        "name": "web_search",
        "line": "done: web_search (0.1s)",
    })
    bottom = "".join(text for _, text in tui._render_bottom_bar())

    assert "tools:idle" in bottom
    assert "status:running" in bottom


@pytest.mark.asyncio
async def test_tui_show_actions_starts_with_details_visible():
    tui = _fake_tui(show_actions=True)

    assert tui.state.details_visible is True
