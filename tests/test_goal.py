import pytest
import os

from app.goal import GoalState
from app.goal_ledger import GoalLedgerStore
from app.tools.base import ToolRuntimeContext
from app.tools.factory import build_tool_registry
from app.tools.goal import (
    GoalRecordEvidenceTool,
    GoalStartTool,
    GoalStatusTool,
    GoalUpdateTool,
)
from cli.main import _format_goal_status, _parse_goal_run_count


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
    store = GoalLedgerStore(os.path.join(temp_dir, "ledgers"))
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
    assert completed.loop_status == "complete"
    assert completed.verification[0].summary == "pytest passed"
    assert store.load("session-a").status == "complete"


def test_goal_ledger_records_durable_loop_state(temp_dir):
    store = GoalLedgerStore(os.path.join(temp_dir, "ledgers"))
    store.start("session-a", "Ship ledger")

    running = store.mark_loop_started("session-a", run_id="run-123")

    assert running.run_id == "run-123"
    assert running.loop_status == "running"
    assert running.loop_started_at is not None
    assert running.stop_reason is None

    waiting = store.mark_loop_finished("session-a", stop_reason="assistant_final")

    assert waiting.loop_status == "waiting"
    assert waiting.stop_reason == "assistant_final"
    assert waiting.loop_finished_at is not None

    paused = store.mark_loop_finished(
        "session-a",
        stop_reason="assistant_final",
        pending_approvals=2,
    )

    assert paused.loop_status == "paused"
    assert paused.pending_approvals == 2
    assert "Loop status: paused" in paused.render_for_prompt()
    assert "Pending approvals: 2" in paused.render_for_prompt()


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

    assert "Start one with /goal <objective>" in _format_goal_status(None)
    assert "Status: blocked" in formatted
    assert "Turns: 4" in formatted
    assert "Note: needs key" in formatted
