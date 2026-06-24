import os

from app.memory_coding_eval import MemoryCodingEvalRunner, load_memory_coding_eval_task


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
