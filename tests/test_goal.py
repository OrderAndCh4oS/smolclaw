import pytest
import os

from app.goal import GoalState, GoalStore
from app.tools.base import ToolRuntimeContext
from app.tools.factory import build_tool_registry
from app.tools.goal import GoalStartTool, GoalStatusTool, GoalUpdateTool
from cli.main import _format_goal_status, _parse_goal_run_count


def test_goal_store_start_update_clear(temp_dir):
    store = GoalStore(temp_dir)

    goal = store.start("session-a", "Finish harness loop")
    assert goal.objective == "Finish harness loop"
    assert goal.status == "active"

    incremented = store.increment_turn_count("session-a")
    assert incremented.turn_count == 1

    updated = store.update("session-a", status="complete", note="done")
    assert updated.status == "complete"
    assert updated.note == "done"

    assert store.load("session-a").status == "complete"
    assert store.clear("session-a") is True
    assert store.load("session-a") is None


def test_goal_store_rejects_empty_objective(temp_dir):
    store = GoalStore(temp_dir)
    with pytest.raises(ValueError):
        store.start("session-a", "   ")


def test_goal_store_keeps_unsafe_session_key_inside_sessions_dir(temp_dir):
    store = GoalStore(temp_dir)
    unsafe_key = "../outside/goal-session"

    store.start(unsafe_key, "Keep goal contained")

    assert not os.path.exists(os.path.join(temp_dir, "..", "outside", "goal-session.goal.json"))
    goal_files = [name for name in os.listdir(temp_dir) if name.endswith(".goal.json")]
    assert len(goal_files) == 1
    assert "/" not in goal_files[0]
    assert store.load(unsafe_key).objective == "Keep goal contained"
    assert store.clear(unsafe_key) is True
    assert store.load(unsafe_key) is None


def test_goal_capability_registers_goal_start_when_session_manager_available(temp_dir):
    registry = build_tool_registry(
        smol_rag=None,
        session_manager=object(),
        capability_names=["goal"],
    )

    assert "goal_start" in registry.tool_names()
    assert "goal_status" in registry.tool_names()
    assert "goal_update" in registry.tool_names()


@pytest.mark.asyncio
async def test_goal_tools_bind_to_runtime_context(temp_dir):
    store = GoalStore(temp_dir)
    store.start("session-a", "Write code")
    runtime = ToolRuntimeContext(goal_store=store, session_key="session-a")

    start_tool = GoalStartTool().bind(runtime)
    status_tool = GoalStatusTool().bind(runtime)
    update_tool = GoalUpdateTool().bind(runtime)

    assert await start_tool.execute(objective="Ship the goal tool") == "Goal set: Ship the goal tool"
    assert store.load("session-a").objective == "Ship the goal tool"

    assert "Ship the goal tool" in await status_tool.execute()

    result = await update_tool.execute(status="blocked", note="waiting on API key")
    assert result == "Goal marked blocked. Note: waiting on API key"
    assert store.load("session-a").status == "blocked"


def test_cli_goal_helpers():
    assert _parse_goal_run_count("") == 3
    assert _parse_goal_run_count("2") == 2
    assert _parse_goal_run_count("999") == 20

    with pytest.raises(Exception):
        _parse_goal_run_count("zero")

    formatted = _format_goal_status(
        GoalState(objective="Ship it", status="blocked", note="needs key", turn_count=4)
    )
    assert "Goal: Ship it" in formatted
    assert "Status: blocked" in formatted
    assert "Turns: 4" in formatted
    assert "Note: needs key" in formatted
