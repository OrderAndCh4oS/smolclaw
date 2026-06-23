import os

from app.goal_ledger import GoalLedgerStore
from app.run_trace import RunTraceStore
from app.run_views import (
    build_run_status_view,
    format_goal_status,
    format_run_status_view,
    format_trace_replay,
    format_trace_status,
)


def test_format_trace_status_can_include_goal_ledger(temp_dir):
    trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
    goal_store.start("session-a", "Fix parser", acceptance_criteria=["Tests pass"])
    recorder = trace_store.start_run("session-a")
    recorder.append("tool.started", {"name": "run_command", "command": "pytest"})
    recorder.append("verification.recorded", {
        "command": "pytest",
        "status": "passed",
        "summary": "tests passed",
    })
    recorder.finish("complete", stop_reason="assistant_final")

    output = format_trace_status(trace_store, "session-a", goal_store=goal_store)

    assert f"Trace: {recorder.run_id}" in output
    assert "Status: complete" in output
    assert "Goal: Fix parser" in output
    assert "Goal status: active" in output
    assert "Ledger path:" in output


def test_run_status_view_combines_trace_and_ledger_state(temp_dir):
    trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
    goal_store.start("session-a", "Fix parser", acceptance_criteria=["Tests pass"])
    goal_store.record_evidence_with_result(
        "session-a",
        kind="checkpoint",
        summary="write_file changed parser.py",
        path="parser.py",
        checkpoint_id="chk-1",
    )
    goal_store.record_evidence(
        "session-a",
        kind="test",
        summary="pytest passed",
        command="pytest",
        status="passed",
    )
    recorder = trace_store.start_run("session-a")
    recorder.append("checkpoint.created", {
        "checkpoint_id": "chk-1",
        "changed_paths": ["parser.py"],
    })
    recorder.finish("complete", stop_reason="assistant_final")

    view = build_run_status_view(
        session_key="session-a",
        trace_store=trace_store,
        goal_store=goal_store,
    )
    output = format_run_status_view(view)

    assert view.trace_run_id == recorder.run_id
    assert view.goal_objective == "Fix parser"
    assert view.changed_files == ["parser.py"]
    assert view.verification_summaries == ["pytest passed"]
    assert "Changed files: parser.py" in output
    assert "Verification:" in output
    assert "- pytest passed" in output


def test_goal_status_renders_ledger_details(temp_dir):
    goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
    goal_store.start("session-a", "Fix parser", acceptance_criteria=["Tests pass"])
    goal_store.record_evidence(
        "session-a",
        kind="test",
        summary="pytest passed",
        command="pytest",
        status="passed",
    )
    goal = goal_store.load("session-a")

    output = format_goal_status(goal)

    assert "Goal: Fix parser" in output
    assert "Acceptance criteria:" in output
    assert "- [pending] Tests pass" in output
    assert "Verification:" in output
    assert "- pytest passed" in output


def test_trace_replay_surfaces_origin_tool_event_id(temp_dir):
    trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = trace_store.start_run("session-a")
    tool_started = recorder.append("tool.started", {"name": "write_file"})
    recorder.append("checkpoint.created", {
        "checkpoint_id": "chk-1",
        "changed_paths": ["parser.py"],
        "tool_trace_event_id": tool_started.event_id,
    })
    recorder.finish("complete", stop_reason="assistant_final")

    output = format_trace_replay(trace_store, "session-a", run_id=recorder.run_id)

    assert "checkpoint.created" in output
    assert f"tool_trace_event_id={tool_started.event_id}" in output
