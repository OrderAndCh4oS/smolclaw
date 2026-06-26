import os

from app.memory_coding_eval import (
    MemoryCodingEvalRunner,
    build_memory_coding_eval_suite_report,
    load_memory_coding_eval_task,
    memory_coding_eval_regressions,
)


FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "agent_tasks",
    "csv_memory_policy",
)


def test_load_memory_coding_eval_task_reads_fixture():
    task = load_memory_coding_eval_task(FIXTURE_DIR)

    assert task.id == "csv_memory_policy"
    assert task.memory_source_id == "csv-parser-policy"
    assert "preserve empty fields" in task.memory_content
    assert "parser.py" in task.memory_on_patches
    assert "parser.py" in task.memory_off_patches


def test_memory_coding_eval_contrasts_memory_on_and_off():
    report = MemoryCodingEvalRunner().run(FIXTURE_DIR)

    assert report.status == "passed"
    assert report.score == 1.0
    assert report.checks == {
        "memory_on_passes": True,
        "memory_off_fails": True,
        "memory_terms_present": True,
        "contrast_observed": True,
    }
    assert report.memory_on.status == "passed"
    assert report.memory_off.status == "failed"
    assert "preserve empty fields" in report.memory_on.retrieved_memory
    assert "exit code 1" in report.memory_off.command_outputs["python -m pytest"]


def test_memory_coding_eval_suite_report_scores_deltas():
    report = MemoryCodingEvalRunner().run(FIXTURE_DIR)

    suite = build_memory_coding_eval_suite_report(
        [report],
        baseline={"csv_memory_policy": 0.5},
    )

    assert suite["status"] == "passed"
    assert suite["task_count"] == 1
    assert suite["checks"]["memory_on_passes"]["passed"] == 1
    assert suite["score_deltas"]["csv_memory_policy"]["delta"] == 0.5
    assert suite["reports"][0]["report_type"] == "memory_coding_eval"


def test_memory_coding_eval_regressions_report_score_drops():
    report = MemoryCodingEvalRunner().run(FIXTURE_DIR)
    suite = build_memory_coding_eval_suite_report(
        [report],
        baseline={"csv_memory_policy": 1.25},
    )

    regressions = memory_coding_eval_regressions(suite, max_score_drop=0.1)

    assert regressions == [{
        "task_id": "csv_memory_policy",
        "current": 1.0,
        "baseline": 1.25,
        "delta": -0.25,
        "max_score_drop": 0.1,
    }]
