import json
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
    assert "Summary path:" in output


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
    recorder.append("tool.started", {"name": "run_command", "command": "pytest"})
    recorder.append("checkpoint.created", {
        "checkpoint_id": "chk-1",
        "changed_paths": ["parser.py"],
    })
    recorder.finish("complete", stop_reason="assistant_final")
    goal_store.mark_loop_finished("session-a", stop_reason="approval_required", pending_approvals=2)

    view = build_run_status_view(
        session_key="session-a",
        trace_store=trace_store,
        goal_store=goal_store,
        worktree_path="/tmp/smolclaw-worktree",
        worktree_diff="diff --git a/parser.py b/parser.py\n",
        worktree_metadata={
            "mode": "dirty-copy",
            "dirty_copy": True,
            "copied_file_count": 12,
            "copied_byte_count": 345,
            "excluded_path_count": 3,
            "warning_count": 1,
            "warnings": ["Dirty copy excluded 3 path(s)."],
        },
        sandbox_metadata={
            "provider": "docker",
            "image": "smolclaw-dev:latest",
            "network": "none",
            "source_root": "/tmp/smolclaw-worktree",
            "state_root": temp_dir,
            "container_workspace": "/workspace",
            "resource_limits": {
                "cpus": "2",
                "memory": "2g",
                "pids": 256,
            },
            "env_policy": {
                "allowed_host_keys": ["CI"],
                "injected_keys": ["HOME", "PATH"],
                "stripped_sensitive_count": 3,
                "host_path_passthrough": False,
            },
            "warnings": ["Sandbox mounts only the isolated source root."],
        },
    )
    output = format_run_status_view(view)
    encoded = json.loads(json.dumps(view.to_dict()))

    assert view.trace_run_id == recorder.run_id
    assert view.goal_objective == "Fix parser"
    assert view.commands_run == ["pytest"]
    assert view.checkpoints == ["chk-1"]
    assert view.pending_approvals == 2
    assert view.goal_pending_approvals == 2
    assert view.worktree_has_diff is True
    assert view.worktree_mode == "dirty-copy"
    assert view.worktree_dirty_copy is True
    assert view.worktree_copied_file_count == 12
    assert view.worktree_warning_count == 1
    assert view.sandbox_provider == "docker"
    assert view.sandbox_image == "smolclaw-dev:latest"
    assert view.sandbox_network == "none"
    assert view.sandbox_resource_limits["memory"] == "2g"
    assert encoded["worktree_diff_size"] == len("diff --git a/parser.py b/parser.py\n")
    assert encoded["sandbox_provider"] == "docker"
    assert view.changed_files == ["parser.py"]
    assert view.verification_summaries == ["pytest passed"]
    assert "Changed files: parser.py" in output
    assert "Commands: pytest" in output
    assert "Checkpoints: chk-1" in output
    assert "Pending approvals: 2" in output
    assert "Worktree mode: dirty-copy" in output
    assert "Copied files: 12" in output
    assert "- Dirty copy excluded 3 path(s)." in output
    assert "Worktree diff: present" in output
    assert "Sandbox: docker" in output
    assert "Sandbox image: smolclaw-dev:latest" in output
    assert "Sandbox network: none" in output
    assert "Sandbox limits: cpus=2, memory=2g, pids=256" in output
    assert "Sandbox env: allowed_host_keys=1, injected_keys=2, stripped_sensitive=3, host_path_passthrough=no" in output
    assert "- Sandbox mounts only the isolated source root." in output
    assert "Verification:" in output
    assert "- pytest passed" in output


def test_trace_status_uses_canonical_run_status_renderer(temp_dir):
    trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
    goal_store.start("session-a", "Fix parser")
    recorder = trace_store.start_run("session-a")
    recorder.append("tool.started", {"name": "run_command", "command": "pytest"})
    recorder.finish("complete", stop_reason="assistant_final")

    output = format_trace_status(trace_store, "session-a", goal_store=goal_store)
    canonical = format_run_status_view(build_run_status_view(
        session_key="session-a",
        trace_store=trace_store,
        goal_store=goal_store,
    ))

    assert output == canonical
    assert f"Trace: {recorder.run_id}" in output
    assert "Commands: pytest" in output


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
