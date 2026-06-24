from unittest.mock import MagicMock

import pytest

from cli.commands import (
    GOAL_COMMAND_HELP,
    SlashCommandDispatcher,
    _InteractiveWorktreeState,
    _build_goal_inference_prompt,
    _format_diagnostics_paths,
    _format_goal_started,
    _format_goal_inference_thread,
    _format_inferred_goal_started,
    _format_undo_result,
    infer_goal_from_thread,
    _parse_goal_command,
    _resolve_worktree_command,
    parse_slash_command,
)


def test_parse_slash_command_splits_name_and_argument():
    parsed = parse_slash_command("  /trace events run-1 5  ")

    assert parsed.raw == "/trace events run-1 5"
    assert parsed.name == "/trace"
    assert parsed.arg == "events run-1 5"
    assert parsed.is_slash is True


def test_parse_slash_command_marks_regular_prompt():
    parsed = parse_slash_command("inspect this project")

    assert parsed.name == "inspect"
    assert parsed.arg == "this project"
    assert parsed.is_slash is False


@pytest.mark.asyncio
async def test_slash_command_dispatcher_routes_registered_command():
    dispatcher = SlashCommandDispatcher()
    calls = []

    @dispatcher.register("/trace", "/t")
    async def _trace(parsed):
        calls.append((parsed.name, parsed.arg))
        return True

    handled = await dispatcher.dispatch("/t events 5")

    assert handled is True
    assert calls == [("/t", "events 5")]


@pytest.mark.asyncio
async def test_slash_command_dispatcher_ignores_unknown_and_regular_input():
    dispatcher = SlashCommandDispatcher()

    assert await dispatcher.dispatch("/missing") is False
    assert await dispatcher.dispatch("not a command") is False


def test_shared_undo_formatter_includes_restored_paths():
    result = MagicMock()
    result.ok = True
    result.message = "Undid checkpoint chk-1; restored 1 path."
    result.restored_paths = ["app/file.py"]

    assert _format_undo_result(result) == "Undid checkpoint chk-1; restored 1 path.\n- app/file.py"


def test_shared_diagnostics_paths_format():
    output = _format_diagnostics_paths("/tmp/logs")

    assert "Diagnostics logs: /tmp/logs" in output
    assert "Events: /tmp/logs/events.jsonl" in output
    assert "Text log: /tmp/logs/smolclaw.log" in output


def test_goal_command_parser_uses_canonical_subcommands():
    assert _parse_goal_command("") == ("status", "")
    assert _parse_goal_command("help") == ("help", "")
    assert _parse_goal_command("status") == ("status", "")
    assert _parse_goal_command("infer") == ("infer", "")
    assert _parse_goal_command("Ship memory evals") == ("start", "Ship memory evals")
    assert _parse_goal_command("start Ship memory evals") == ("start", "Ship memory evals")
    assert _parse_goal_command("run 2") == ("run", "2")
    assert _parse_goal_command("complete tests passed") == ("complete", "tests passed")
    assert _parse_goal_command("block waiting on approval") == ("block", "waiting on approval")
    assert _parse_goal_command("clear") == ("clear", "")
    assert _parse_goal_command("thread") == ("start", "thread")
    assert _parse_goal_command("from-chat") == ("start", "from-chat")


def test_goal_help_and_started_message_are_actionable():
    goal = MagicMock()
    goal.objective = "Ship it"

    assert "/goal <objective>" in GOAL_COMMAND_HELP
    started = _format_goal_started(goal)
    assert "Goal set: Ship it" in started
    assert "/goal run" in started

    inferred = MagicMock()
    inferred.acceptance_criteria = ["Tests pass"]
    inferred.rationale = "User asked for it."
    inferred_started = _format_inferred_goal_started(goal, inferred)
    assert "Acceptance criteria:" in inferred_started
    assert "Inferred from: User asked for it." in inferred_started


def test_goal_inference_thread_skips_tool_messages_and_builds_prompt():
    transcript = _format_goal_inference_thread([
        {"role": "user", "content": "We should add goal inference."},
        {"role": "tool", "content": "irrelevant"},
        {"role": "assistant", "content": "Agreed, infer from decisions."},
    ])

    assert "tool:" not in transcript
    assert "We should add goal inference" in transcript
    prompt = _build_goal_inference_prompt(transcript)
    assert "Return only JSON" in prompt
    assert "explicitly stated or agreed" in prompt


@pytest.mark.asyncio
async def test_infer_goal_from_thread_parses_objective_and_criteria():
    class FakeLlm:
        async def get_completion(self, prompt):
            assert "Infer the current working goal" in prompt
            return (
                '{"objective": "Add inferred goal creation", '
                '"acceptance_criteria": ["Infer from recent chat", "Create a goal"], '
                '"rationale": "The user requested it."}'
            )

    inferred = await infer_goal_from_thread(FakeLlm(), [
        {"role": "user", "content": "Can we infer a goal from this thread?"},
        {"role": "assistant", "content": "Yes, with /goal infer."},
    ])

    assert inferred.objective == "Add inferred goal creation"
    assert inferred.acceptance_criteria == ["Infer from recent chat", "Create a goal"]
    assert inferred.rationale == "The user requested it."


@pytest.mark.asyncio
async def test_infer_goal_from_thread_requires_history():
    class FakeLlm:
        async def get_completion(self, prompt):
            raise AssertionError("should not call model")

    with pytest.raises(ValueError, match="No prior chat messages"):
        await infer_goal_from_thread(FakeLlm(), [])


def test_worktree_command_state_lives_with_command_resolver():
    ctx = MagicMock()
    ctx.diff.return_value = "diff --git a/file b/file"
    ctx.apply_back.return_value = "Applied 1 file."
    ctx.created_by_git_worktree = True
    ctx.run_id = "run-1"
    ctx.path = "/tmp/worktree"
    ctx.base_repo = "/repo"
    state = _InteractiveWorktreeState(context=ctx, state_root="/repo/.smolclaw")

    assert "Worktree: active" in _resolve_worktree_command(state, "status")
    assert "diff --git" in _resolve_worktree_command(state, "diff")
    assert _resolve_worktree_command(state, "apply") == "Applied 1 file."
    assert state.applied_count == 1
