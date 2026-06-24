from unittest.mock import MagicMock

import pytest

from cli.commands import (
    SlashCommandDispatcher,
    _InteractiveWorktreeState,
    _format_diagnostics_paths,
    _format_undo_result,
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
