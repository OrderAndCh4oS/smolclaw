import pytest
import os

from app.goal import GoalState, GoalStore
from app.goal_ledger import GoalLedgerStore
from app.storage_paths import backup_storage_path
from app.tools.base import ToolRuntimeContext
from app.tools.factory import build_tool_registry
from app.tools.goal import (
    GoalRecordEvidenceTool,
    GoalStartTool,
    GoalStatusTool,
    GoalUpdateTool,
)
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


def test_goal_store_recovers_from_corrupt_json_using_backup(temp_dir):
    store = GoalStore(temp_dir)
    store.start("session-a", "Recover this goal")
    store.update("session-a", status="complete", note="done")
    path = os.path.join(temp_dir, "session-a.goal.json")
    assert os.path.exists(backup_storage_path(path))

    with open(path, "w") as f:
        f.write("{not-json")

    recovered = store.load("session-a")
    assert recovered is not None
    assert recovered.objective == "Recover this goal"
    assert recovered.status == "active"


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
    assert "goal_record_evidence" in registry.tool_names()


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


def test_goal_ledger_store_start_record_and_complete(temp_dir):
    store = GoalLedgerStore(os.path.join(temp_dir, "ledgers"))
    ledger = store.start("session-a", "Ship ledger", acceptance_criteria=["Tests pass"])

    assert ledger.goal_id.startswith("goal-")
    assert ledger.acceptance_criteria[0].description == "Tests pass"

    ledger.acceptance_criteria[0].status = "satisfied"
    store.save("session-a", ledger)
    store.record_evidence(
        "session-a",
        kind="test",
        summary="pytest passed",
        command="pytest",
        status="passed",
    )
    completed = store.update("session-a", status="complete", note="done")

    assert completed.status == "complete"
    assert completed.verification[0].summary == "pytest passed"
    assert store.load("session-a").status == "complete"


def test_goal_ledger_store_migrates_legacy_goal(temp_dir):
    legacy = GoalStore(os.path.join(temp_dir, "sessions"))
    legacy.start("session-a", "Legacy goal")
    legacy.increment_turn_count("session-a")

    store = GoalLedgerStore(
        os.path.join(temp_dir, "ledgers"),
        legacy_sessions_dir=os.path.join(temp_dir, "sessions"),
    )
    ledger = store.load("session-a")

    assert ledger is not None
    assert ledger.objective == "Legacy goal"
    assert ledger.turn_count == 1
    incremented = store.increment_turn_count("session-a")
    assert incremented.turn_count == 2
    assert os.path.exists(os.path.join(temp_dir, "ledgers", "session-a.ledger.json"))


def test_goal_ledger_completion_requires_criteria_or_verification_reason(temp_dir):
    store = GoalLedgerStore(os.path.join(temp_dir, "ledgers"))
    store.start("session-a", "Ship ledger", acceptance_criteria=["Tests pass"])

    with pytest.raises(ValueError, match="acceptance criterion"):
        store.update("session-a", status="complete")

    ledger = store.load("session-a")
    ledger.acceptance_criteria[0].status = "not_applicable"
    store.save("session-a", ledger)
    completed = store.update(
        "session-a",
        status="complete",
        no_verification_reason="documentation-only goal",
    )
    assert completed.status == "complete"
    assert completed.verification[0].status == "not_applicable"


def test_goal_ledger_completion_requires_all_criteria_done(temp_dir):
    store = GoalLedgerStore(os.path.join(temp_dir, "ledgers"))
    store.start(
        "session-a",
        "Ship ledger",
        acceptance_criteria=["Tests pass", "Docs updated"],
    )
    store.update(
        "session-a",
        acceptance_updates=[
            {
                "description": "Tests pass",
                "status": "satisfied",
                "evidence": "pytest passed",
            },
        ],
    )

    with pytest.raises(ValueError, match="every acceptance criterion"):
        store.update(
            "session-a",
            status="complete",
            no_verification_reason="verification not applicable",
        )

    completed = store.update(
        "session-a",
        acceptance_updates=[
            {"description": "Docs updated", "status": "not_applicable"},
        ],
        status="complete",
        no_verification_reason="documentation criterion not applicable",
    )

    assert completed.status == "complete"
    assert [item.status for item in completed.acceptance_criteria] == [
        "satisfied",
        "not_applicable",
    ]


@pytest.mark.asyncio
async def test_goal_ledger_tools_record_evidence_and_status(temp_dir):
    store = GoalLedgerStore(os.path.join(temp_dir, "ledgers"))
    runtime = ToolRuntimeContext(goal_store=store, session_key="session-a")

    start_tool = GoalStartTool().bind(runtime)
    update_tool = GoalUpdateTool().bind(runtime)
    evidence_tool = GoalRecordEvidenceTool().bind(runtime)
    status_tool = GoalStatusTool().bind(runtime)

    result = await start_tool.execute(
        objective="Ship ledger",
        acceptance_criteria=["Tests pass"],
    )
    assert result == "Goal set: Ship ledger"

    result = await update_tool.execute(
        plan=["Inspect code", "Run tests"],
        current_step="Run tests",
        acceptance_updates=[
            {
                "description": "Tests pass",
                "status": "satisfied",
                "evidence": "pytest passed",
            },
        ],
    )
    assert result == "Goal updated: Ship ledger"
    ledger = store.load("session-a")
    assert ledger.current_step_id == ledger.plan[1].id
    assert ledger.acceptance_criteria[0].status == "satisfied"

    result = await evidence_tool.execute(
        kind="test",
        summary="pytest passed",
        command="pytest",
        status="passed",
    )
    assert result == "Recorded test evidence for goal: Ship ledger"

    status = await status_tool.execute()
    assert "Acceptance criteria:" in status
    assert "Verification:" in status
    assert "pytest passed" in status


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
