import json
import os
import subprocess
import sys

import pytest

from app.agent_eval import AgentEvalRunner, load_agent_eval_task, score_agent_eval
from app.definitions import build_workspace_paths
from app.goal_ledger import (
    AcceptanceCriterion,
    ChangedFileRef,
    EvidenceRef,
    GoalLedger,
    VerificationEvidence,
)
from app.goal_ledger import GoalLedgerStore
from app.run_trace import RunTraceStore, RunTraceSummary
from scripts.run_agent_eval import main as run_agent_eval_main


def _write_task(temp_dir, body: str) -> str:
    task_dir = os.path.join(temp_dir, "task")
    repo_dir = os.path.join(task_dir, "repo")
    os.makedirs(repo_dir, exist_ok=True)
    with open(os.path.join(task_dir, "task.yaml"), "w", encoding="utf-8") as handle:
        handle.write(body)
    with open(os.path.join(repo_dir, "app.py"), "w", encoding="utf-8") as handle:
        handle.write("print('hello')\n")
    return task_dir


def _write_recorded_artifacts(task_dir: str, task_id: str):
    recorded_dir = os.path.join(task_dir, "recorded")
    os.makedirs(recorded_dir, exist_ok=True)
    ledger = GoalLedger(
        session_key=f"eval-{task_id}",
        objective="Fix the parser.",
        status="complete",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="crit-1",
                description="Eval task passes",
                status="satisfied",
                evidence=["recorded run passed"],
            ),
        ],
        inspected_files=[
            EvidenceRef(kind="status", summary="checked git status", path="."),
            EvidenceRef(kind="read", summary="read target", path="app.py"),
        ],
        verification=[
            VerificationEvidence(
                command="pytest",
                status="passed",
                summary="tests passed",
                trace_event_id="evt-verify",
            ),
        ],
        stop_reason="assistant_final",
    )
    summary = RunTraceSummary(
        run_id="run-recorded",
        session_key=f"eval-{task_id}",
        status="complete",
        model="recorded",
        tool_calls=3,
        denied_tool_calls=0,
        commands_run=["pytest"],
        verification=[{"command": "pytest", "status": "passed"}],
        stop_reason="assistant_final",
        trace_path=os.path.join(recorded_dir, "trace.jsonl"),
    )
    with open(os.path.join(recorded_dir, "ledger.json"), "w", encoding="utf-8") as handle:
        json.dump(ledger.to_dict(), handle)
    with open(os.path.join(recorded_dir, "trace.summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary.to_dict(), handle)
    with open(os.path.join(recorded_dir, "trace.jsonl"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "event_id": "evt-verify",
            "event": "verification.recorded",
            "run_id": "run-recorded",
            "session_key": f"eval-{task_id}",
            "data": {"command": "pytest", "status": "passed"},
        }) + "\n")
    with open(os.path.join(recorded_dir, "diff"), "w", encoding="utf-8") as handle:
        handle.write("diff --git a/app.py b/app.py\n")
    with open(os.path.join(recorded_dir, "command_outputs.json"), "w", encoding="utf-8") as handle:
        json.dump({"pytest": "exit code 0\npassed"}, handle)


def test_load_agent_eval_task_validates_schema(temp_dir):
    task_dir = _write_task(temp_dir, "id: demo\n")

    with pytest.raises(ValueError, match="prompt"):
        load_agent_eval_task(task_dir)


def test_load_agent_eval_task_reads_fields(temp_dir):
    task_dir = _write_task(temp_dir, """
id: python_bugfix
prompt: Fix the parser.
verification:
  - pytest
required_evidence:
  - git_status
  - read_target
allowed_files:
  - app.py
forbidden_files:
  - .env
expected_status: complete
""")

    task = load_agent_eval_task(task_dir)

    assert task.id == "python_bugfix"
    assert task.verification == ["pytest"]
    assert task.required_evidence == ["git_status", "read_target"]
    assert task.allowed_files == ["app.py"]


def test_mock_agent_eval_runner_writes_report(temp_dir):
    task_dir = _write_task(temp_dir, """
id: python_bugfix
prompt: Fix the parser.
verification:
  - pytest
required_evidence:
  - git_status
  - read_target
  - test_command
allowed_files:
  - app.py
forbidden_files:
  - .env
expected_status: complete
""")
    output_dir = os.path.join(temp_dir, "reports")

    report = AgentEvalRunner(
        mode="mock",
        output_dir=output_dir,
        keep_workspace=True,
    ).run(task_dir)

    assert report.status == "passed"
    assert report.score == 1.0
    assert report.checks["required_evidence"] is True
    assert os.path.exists(os.path.join(output_dir, "python_bugfix.report.json"))
    assert os.path.exists(report.diff_path)
    assert "pytest" in report.command_outputs
    assert os.path.exists(report.trace_path)
    assert os.path.exists(report.ledger_path)
    assert report.run_status["trace_run_id"]
    assert report.run_status["goal_objective"] == "Fix the parser."
    assert "Trace:" in report.run_summary
    assert report.failure_classes == []
    assert report.failures == []
    assert report.recommended_actions == []
    assert report.evaluation_summary == "Evaluation: passed"
    with open(os.path.join(output_dir, "python_bugfix.report.json"), encoding="utf-8") as handle:
        saved_report = json.load(handle)
    assert saved_report["run_status"]["ledger_path"] == report.ledger_path
    assert "Verification:" in saved_report["run_summary"]
    assert saved_report["evaluation_summary"] == "Evaluation: passed"


def test_agent_eval_fixture_runs_in_mock_mode(temp_dir):
    fixture_dir = os.path.join(
        os.path.dirname(__file__),
        "fixtures",
        "agent_tasks",
        "python_parser_bug",
    )
    output_dir = os.path.join(temp_dir, "reports")

    report = AgentEvalRunner(
        mode="mock",
        output_dir=output_dir,
        keep_workspace=True,
    ).run(fixture_dir)

    assert report.task_id == "python_parser_bug"
    assert report.status == "passed"
    assert report.score == 1.0
    assert os.path.exists(os.path.join(output_dir, "python_parser_bug.report.json"))


def test_recorded_agent_eval_runner_scores_saved_artifacts(temp_dir):
    task_dir = _write_task(temp_dir, """
id: recorded_bugfix
prompt: Fix the parser.
verification:
  - pytest
required_evidence:
  - git_status
  - read_target
  - test_command
allowed_files: []
expected_status: complete
""")
    _write_recorded_artifacts(task_dir, "recorded_bugfix")
    output_dir = os.path.join(temp_dir, "reports")

    report = AgentEvalRunner(
        mode="recorded",
        output_dir=output_dir,
    ).run(task_dir)

    assert report.status == "passed"
    assert report.mode == "recorded"
    assert report.score == 1.0
    assert report.checks["trace_ledger_integrity"] is True
    assert report.trace_path.endswith("trace.jsonl")
    assert report.ledger_path.endswith("ledger.json")
    assert report.run_status["trace_path"].endswith("trace.jsonl")
    assert report.run_status["ledger_path"].endswith("ledger.json")
    assert report.run_status["goal_status"] == "complete"
    assert "Goal status: complete" in report.run_summary
    assert os.path.exists(os.path.join(output_dir, "recorded_bugfix.report.json"))
    assert os.path.exists(os.path.join(output_dir, "recorded_bugfix.diff"))
    assert report.command_outputs["pytest"].startswith("exit code 0")


def test_recorded_agent_eval_runner_requires_recorded_artifacts(temp_dir):
    task_dir = _write_task(temp_dir, """
id: missing_recording
prompt: Fix the parser.
expected_status: complete
""")

    with pytest.raises(ValueError, match="Recorded eval artifacts are missing"):
        AgentEvalRunner(mode="recorded").run(task_dir)


def test_live_agent_eval_runner_scores_subprocess_artifacts(temp_dir):
    task_dir = _write_task(temp_dir, """
id: live_bugfix
prompt: Fix the parser.
verification:
  - pytest
required_evidence:
  - git_status
  - read_target
  - test_command
allowed_files: []
expected_status: complete
""")
    output_dir = os.path.join(temp_dir, "reports")

    def fake_run(command, **kwargs):
        if "--workspace" not in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        workspace = command[command.index("--workspace") + 1]
        paths = build_workspace_paths(workspace)
        session_key = command[command.index("--session") + 1]
        goal_store = GoalLedgerStore(paths.ledgers_dir)
        ledger = goal_store.start(
            session_key,
            "Fix the parser.",
            acceptance_criteria=["Eval task passes"],
        )
        goal_store.record_evidence(session_key, kind="status", summary="checked git status", path=".")
        goal_store.record_evidence(session_key, kind="read", summary="read app.py", path="app.py")
        trace_store = RunTraceStore(paths.traces_dir)
        recorder = trace_store.start_run(session_key, goal_id=ledger.goal_id, metadata={"mode": "live"})
        event = recorder.append("verification.recorded", {
            "command": "pytest",
            "status": "passed",
            "summary": "tests passed",
        })
        goal_store.record_evidence(
            session_key,
            kind="test",
            summary="tests passed",
            command="pytest",
            status="passed",
            trace_event_id=event.event_id,
        )
        ledger = goal_store.load(session_key)
        goal_store.update(
            session_key,
            status="complete",
            acceptance_updates=[
                {
                    "id": ledger.acceptance_criteria[0].id,
                    "status": "satisfied",
                    "evidence": "live eval passed",
                },
            ],
        )
        summary = recorder.finish("complete", stop_reason="assistant_final")
        ledger_path = os.path.join(paths.ledgers_dir, f"{session_key}.ledger.json")
        payload = {
            "status": "complete",
            "trace_path": summary.trace_path,
            "ledger_path": ledger_path,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    calls = []

    def recording_run(*args, **kwargs):
        calls.append((args, kwargs))
        return fake_run(*args, **kwargs)

    report = AgentEvalRunner(
        mode="live",
        output_dir=output_dir,
        model="gpt-test",
        agent="coder",
        max_turns=2,
        timeout_seconds=30,
        command_runner=recording_run,
    ).run(task_dir)

    command = calls[0][0][0]
    assert command[:3] == [sys.executable, "-m", "cli.main"]
    assert "--goal" in command
    assert command[command.index("--max-turns") + 1] == "2"
    assert command[command.index("--model") + 1] == "gpt-test"
    assert command[command.index("--agent") + 1] == "coder"
    assert report.status == "passed"
    assert report.mode == "live"
    assert report.score == 1.0
    assert os.path.exists(os.path.join(output_dir, "live_bugfix.report.json"))
    assert os.path.exists(report.diff_path)
    assert os.path.exists(report.trace_path)
    assert os.path.exists(report.ledger_path)
    assert report.run_status["trace_path"] == report.trace_path
    assert report.run_status["ledger_path"] == report.ledger_path
    assert "Trace:" in report.run_summary
    assert os.path.exists(os.path.join(output_dir, "live_bugfix.trace.summary.json"))
    assert not os.path.exists(report.workspace)


def test_agent_eval_scores_trace_ledger_integrity_failure(temp_dir):
    trace_path = os.path.join(temp_dir, "trace.jsonl")
    with open(trace_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_id": "evt-other"}) + "\n")
    task = load_agent_eval_task(_write_task(temp_dir, """
id: integrity
prompt: Fix the parser.
verification:
  - pytest
expected_status: complete
"""))
    ledger = GoalLedger(
        session_key="eval-integrity",
        objective="Fix the parser.",
        status="complete",
        verification=[
            VerificationEvidence(
                command="pytest",
                status="passed",
                summary="tests passed",
                trace_event_id="evt-missing",
            ),
        ],
    )
    summary = RunTraceSummary(
        run_id="run-integrity",
        session_key="eval-integrity",
        status="complete",
        trace_path=trace_path,
    )

    report = score_agent_eval(
        task=task,
        mode="recorded",
        workspace_root=temp_dir,
        ledger=ledger,
        trace_summary=summary,
        diff_path=None,
        command_outputs={},
    )

    assert report.status == "failed"
    assert report.checks["trace_ledger_integrity"] is False
    assert "artifact_integrity" in report.failure_classes
    assert report.failures[0]["check"] == "trace_ledger_integrity"
    assert "middleware join" in report.recommended_actions[0]
    assert "Failure classes:" in report.evaluation_summary


def test_agent_eval_scores_missing_changed_file_tool_event_as_integrity_failure(temp_dir):
    trace_path = os.path.join(temp_dir, "trace.jsonl")
    with open(trace_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_id": "evt-checkpoint", "event": "checkpoint.created"}) + "\n")
    task = load_agent_eval_task(_write_task(temp_dir, """
id: changed_integrity
prompt: Fix the parser.
expected_status: complete
"""))
    ledger = GoalLedger(
        session_key="eval-changed-integrity",
        objective="Fix the parser.",
        status="complete",
        changed_files=[
            ChangedFileRef(
                path="app.py",
                checkpoint_id="chk-1",
                trace_event_id="evt-checkpoint",
                tool_trace_event_id="evt-missing-tool",
            ),
        ],
    )
    summary = RunTraceSummary(
        run_id="run-changed-integrity",
        session_key="eval-changed-integrity",
        status="complete",
        checkpoints=["chk-1"],
        trace_path=trace_path,
    )

    report = score_agent_eval(
        task=task,
        mode="recorded",
        workspace_root=temp_dir,
        ledger=ledger,
        trace_summary=summary,
        diff_path=None,
        command_outputs={},
    )

    assert report.status == "failed"
    assert report.checks["trace_ledger_integrity"] is False


def test_agent_eval_scores_bad_inspected_file_origin_as_integrity_failure(temp_dir):
    trace_path = os.path.join(temp_dir, "trace.jsonl")
    with open(trace_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_id": "evt-read", "event": "verification.recorded"}) + "\n")
    task = load_agent_eval_task(_write_task(temp_dir, """
id: inspected_integrity
prompt: Fix the parser.
expected_status: complete
"""))
    ledger = GoalLedger(
        session_key="eval-inspected-integrity",
        objective="Fix the parser.",
        status="complete",
        inspected_files=[
            EvidenceRef(
                kind="read",
                summary="read app.py",
                path="app.py",
                trace_event_id="evt-read",
            ),
        ],
    )
    summary = RunTraceSummary(
        run_id="run-inspected-integrity",
        session_key="eval-inspected-integrity",
        status="complete",
        trace_path=trace_path,
    )

    report = score_agent_eval(
        task=task,
        mode="recorded",
        workspace_root=temp_dir,
        ledger=ledger,
        trace_summary=summary,
        diff_path=None,
        command_outputs={},
    )

    assert report.status == "failed"
    assert report.checks["trace_ledger_integrity"] is False


def test_mock_agent_eval_runner_scores_missing_evidence_as_failure(temp_dir):
    task_dir = _write_task(temp_dir, """
id: missing_evidence
prompt: Fix the parser.
required_evidence:
  - read_target
allowed_files:
  - app.py
expected_status: complete
""")
    output_dir = os.path.join(temp_dir, "reports")

    report = AgentEvalRunner(
        mode="mock",
        output_dir=output_dir,
        keep_workspace=True,
    ).run(task_dir)

    assert report.status == "passed"

    task = load_agent_eval_task(task_dir)
    failed_report = score_agent_eval(
        task=task,
        mode="mock",
        workspace_root=temp_dir,
        ledger=None,
        trace_summary=type("Summary", (), {
            "status": "complete",
            "denied_tool_calls": 0,
            "trace_path": None,
        })(),
        diff_path=None,
        command_outputs={},
    )
    assert failed_report.status == "failed"
    assert failed_report.checks["required_evidence"] is False
    assert "exploration" in failed_report.failure_classes
    assert failed_report.failures
    assert failed_report.failures[0]["check"] == "expected_status"
    assert any(item["check"] == "required_evidence" for item in failed_report.failures)
    assert any("Missing required evidence: read_target" in item["summary"] for item in failed_report.failures)
    assert "Recommended next actions:" in failed_report.evaluation_summary


def test_run_agent_eval_script_outputs_json(temp_dir, capsys):
    task_dir = _write_task(temp_dir, """
id: cli_eval
prompt: Fix the parser.
verification:
  - pytest
required_evidence:
  - test_command
expected_status: complete
""")
    output_dir = os.path.join(temp_dir, "reports")

    exit_code = run_agent_eval_main([task_dir, "--mode", "mock", "--output", output_dir, "--keep-workspace"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["task_id"] == "cli_eval"
    assert payload["status"] == "passed"


def test_run_agent_eval_script_outputs_recorded_json(temp_dir, capsys):
    task_dir = _write_task(temp_dir, """
id: recorded_cli_eval
prompt: Fix the parser.
verification:
  - pytest
required_evidence:
  - test_command
expected_status: complete
""")
    _write_recorded_artifacts(task_dir, "recorded_cli_eval")
    output_dir = os.path.join(temp_dir, "reports")

    exit_code = run_agent_eval_main([task_dir, "--mode", "recorded", "--output", output_dir])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["task_id"] == "recorded_cli_eval"
    assert payload["mode"] == "recorded"
    assert payload["status"] == "passed"


def test_run_agent_eval_script_outputs_suite_json_with_score_deltas(temp_dir, capsys):
    task_one = _write_task(os.path.join(temp_dir, "one"), """
id: suite_eval_one
prompt: Fix the parser.
verification:
  - pytest
required_evidence:
  - test_command
expected_status: complete
""")
    task_two = _write_task(os.path.join(temp_dir, "two"), """
id: suite_eval_two
prompt: Fix the parser.
verification:
  - pytest
required_evidence:
  - test_command
expected_status: complete
""")
    output_dir = os.path.join(temp_dir, "reports")
    baseline_path = os.path.join(temp_dir, "baseline.json")
    current_baseline_path = os.path.join(temp_dir, "current-baseline.json")
    with open(baseline_path, "w", encoding="utf-8") as handle:
        json.dump({
            "suite_eval_one": 0.5,
            "suite_eval_two": {"score": 1.0},
        }, handle)

    exit_code = run_agent_eval_main([
        task_one,
        task_two,
        "--mode",
        "mock",
        "--output",
        output_dir,
        "--baseline",
        baseline_path,
        "--write-baseline",
        current_baseline_path,
    ])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "passed"
    assert payload["task_count"] == 2
    assert payload["passed"] == 2
    assert payload["failed"] == 0
    assert payload["average_score"] == 1.0
    assert payload["checks"]["required_evidence"]["passed"] == 2
    assert payload["checks"]["required_evidence"]["total"] == 2
    assert payload["score_deltas"]["suite_eval_one"]["delta"] == 0.5
    assert payload["score_deltas"]["suite_eval_two"]["delta"] == 0.0
    assert payload["reports"][0]["evaluation_summary"] == "Evaluation: passed"
    with open(current_baseline_path, encoding="utf-8") as handle:
        saved_baseline = json.load(handle)
    assert saved_baseline["task_count"] == 2
    assert saved_baseline["reports"][1]["task_id"] == "suite_eval_two"
