from unittest.mock import MagicMock

import pytest

from cli.tui import CoderTui, TranscriptEntry, UiState


def _fake_tui():
    agent = MagicMock()
    agent.llm.completion_model = "gpt-test"
    agent.session.key = "session"
    agent.safety_state = object()
    goal_store = MagicMock()
    goal_store.load.return_value = None
    return CoderTui(
        agent=agent,
        goal_store=goal_store,
        session_manager=MagicMock(),
        memory_store_tool=MagicMock(),
        session_export_hook=MagicMock(),
        smol_rag=MagicMock(),
        workspace_root=".",
        model="fallback-model",
        auto_export=True,
        show_actions=True,
        slash_commands_help="help",
        format_goal_status=lambda goal: "No goal" if goal is None else goal.status,
        parse_goal_run_count=lambda value: int(value or "3"),
        build_goal_loop_prompt=lambda: "continue goal",
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
    assert "running" in bottom


def test_tui_transcript_renders_user_assistant_tool_and_errors():
    tui = _fake_tui()
    tui.state.transcript = [
        TranscriptEntry(kind="user", title="you", text="hello"),
        TranscriptEntry(kind="assistant", title="smolclaw", text="hi"),
        TranscriptEntry(kind="tool", text="action: grep_search query=test"),
        TranscriptEntry(kind="error", text="Error: failed"),
    ]

    rendered = "".join(text for _, text in tui._render_transcript())

    assert "you" in rendered
    assert "hello" in rendered
    assert "smolclaw" in rendered
    assert "hi" in rendered
    assert "action: grep_search query=test" in rendered
    assert "Error: failed" in rendered


def test_tui_builds_prompt_toolkit_application():
    tui = _fake_tui()

    app = tui._build_app()

    assert app is not None
    assert app.full_screen is True


@pytest.mark.asyncio
async def test_tui_submit_streams_agent_events_without_real_llm():
    tui = _fake_tui()
    process_prompts = []

    async def fake_process(prompt, on_output=None, on_event=None):
        process_prompts.append(prompt)
        await on_event({"type": "llm", "phase": "start", "line": "thinking..."})
        await on_output("hello")
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
        await on_output(" world")
        await on_event({
            "type": "llm",
            "phase": "end",
            "model": "gpt-test",
            "total_tokens": 7,
            "line": "thought: 7 tokens",
        })
        return "hello world"

    tui.agent.process = fake_process

    await tui.submit("say hello")

    rendered = "".join(text for _, text in tui._render_transcript())
    assert process_prompts == ["say hello"]
    assert "say hello" in rendered
    assert "hello world" in rendered
    assert "action: grep_search query=hello" in rendered
    assert "done: grep_search (0.1s)" in rendered
    assert tui.state.token_total == 7
    assert tui.state.active_tool == "idle"
    assert tui.state.run_state == "idle"
