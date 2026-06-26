import json
import os

import numpy as np
import pytest
from typer.testing import CliRunner

from app.memory_eval import (
    MemoryEvalRunner,
    build_memory_eval_suite_report,
    load_latest_memory_eval_summary,
    load_memory_eval_suite,
    memory_eval_regressions,
)
from cli.main import app as cli_app
from scripts.ci_memory_eval import main as ci_memory_eval_main
from scripts.run_memory_eval import main as run_memory_eval_main


class OfflineMemoryEvalLlm:
    completion_model = "offline-memory-eval"
    embedding_model = "offline-embedding"

    async def get_completion(self, prompt, **kwargs):
        if "Answer the question using only the provided sources" in str(prompt):
            answer_parts = []
            if "Source ID: roadmap" in prompt:
                answer_parts.append(
                    "SmolClaw should track loop state using roadmap (Kind: produced)."
                )
            if "Source ID: anthropic-agents" in prompt:
                answer_parts.append(
                    "Automated tests are supported by anthropic-agents "
                    "(Kind: sourced, https://www.anthropic.com/engineering/building-effective-agents)."
                )
            return " ".join(answer_parts)
        if kwargs.get("context"):
            return "offline answer"
        return "offline summary"

    async def get_embedding(self, text, **kwargs):
        return self._embedding(text)

    async def get_embeddings(self, texts, **kwargs):
        return [self._embedding(text) for text in texts]

    def _embedding(self, text):
        vector = np.zeros(1536, dtype=np.float32)
        for token in str(text).lower().split():
            index = sum(ord(char) for char in token) % 1536
            vector[index] += 1.0
        if not vector.any():
            vector[0] = 1.0
        return vector.tolist()

    async def close(self):
        pass


class UncitedAnswerLlm(OfflineMemoryEvalLlm):
    async def get_completion(self, prompt, **kwargs):
        if "Answer the question using only the provided sources" in str(prompt):
            return "The answer is supported by the provided material."
        return await super().get_completion(prompt, **kwargs)


def _write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _write_suite(temp_dir: str) -> str:
    _write_file(os.path.join(temp_dir, "docs", "roadmap.md"), """---
source_id: roadmap
title: Reliability Roadmap
kind: produced
entities:
  - SmolClaw
  - Long-running loops
relationships:
  - source: SmolClaw
    relation: prioritizes
    target: Long-running loops
---

SmolClaw should support bounded long-running loops with traceable stop reasons,
verification evidence, and resumable run state.
""")
    _write_file(os.path.join(temp_dir, "research", "agents.md"), """---
source_id: anthropic-agents
title: Building Effective Agents
kind: sourced
source_url: https://www.anthropic.com/engineering/building-effective-agents
entities:
  - Coding agents
  - Automated tests
relationships:
  - source: Coding agents
    relation: use
    target: Automated tests
---

Coding agents need environment feedback. Automated tests provide verification
signals for implementation work. See also [[SmolClaw]] #agent-research.
""")
    suite_path = os.path.join(temp_dir, "memory-eval.yaml")
    _write_file(suite_path, """
id: memory_corpus_demo
corpus:
  - path: docs/roadmap.md
  - path: research/agents.md
questions:
  - id: loop_support
    query: How should SmolClaw handle long-running loops and stop reasons?
    expected_sources:
      - roadmap
    expected_entities:
      - SmolClaw
      - Long-running loops
    expected_relationships:
      - source: SmolClaw
        relation: prioritizes
        target: Long-running loops
    required_terms:
      - stop reasons
  - id: coding_agent_evidence
    query: Which evidence supports automated tests for coding agents?
    expected_sources:
      - anthropic-agents
    expected_entities:
      - Coding agents
      - Automated tests
    expected_relationships:
      - source: Coding agents
        relation: use
        target: Automated tests
    required_terms:
      - verification
""")
    return suite_path


def _write_second_suite(temp_dir: str) -> str:
    _write_file(os.path.join(temp_dir, "other", "source.md"), """---
source_id: second-source
title: Second Source
kind: produced
entities:
  - Evaluation baselines
relationships:
  - source: Evaluation baselines
    relation: compare
    target: Scores
---

Evaluation baselines compare scores over time for regression tracking.
""")
    suite_path = os.path.join(temp_dir, "memory-eval-second.yaml")
    _write_file(suite_path, """
id: memory_corpus_second
corpus:
  - path: other/source.md
questions:
  - id: baseline_tracking
    query: How do evaluation baselines compare scores?
    expected_sources:
      - second-source
    expected_entities:
      - Evaluation baselines
    expected_relationships:
      - source: Evaluation baselines
        relation: compare
        target: Scores
    required_terms:
      - regression tracking
""")
    return suite_path


def _write_hygiene_suite(temp_dir: str) -> str:
    _write_file(os.path.join(temp_dir, "docs", "current.md"), """---
source_id: current-loop-design
title: Current Loop Design
kind: produced
captured_at: "2026-06-01"
entities:
  - SmolClaw
claims:
  - subject: SmolClaw loop state
    predicate: persistence
    object: durable
---

SmolClaw loop state should be durable and resumable.
""")
    _write_file(os.path.join(temp_dir, "docs", "stale.md"), """---
source_id: stale-loop-note
title: Stale Loop Note
kind: produced
captured_at: "2024-01-01"
entities:
  - SmolClaw
claims:
  - subject: SmolClaw loop state
    predicate: persistence
    object: stateless
---

An old loop note said loop state should be stateless.
""")
    suite_path = os.path.join(temp_dir, "memory-eval-hygiene.yaml")
    _write_file(suite_path, """
id: memory_corpus_hygiene
corpus:
  - path: docs/current.md
  - path: docs/stale.md
questions:
  - id: loop_state
    query: How should SmolClaw handle loop state?
    expected_sources:
      - current-loop-design
    expected_entities:
      - SmolClaw
    required_terms:
      - durable
staleness:
  - id: current_loop_design_is_fresh
    source_id: current-loop-design
    expected: fresh
    max_age_days: 90
    as_of: "2026-06-24"
  - id: stale_loop_note_is_stale
    source_id: stale-loop-note
    expected: stale
    max_age_days: 365
    as_of: "2026-06-24"
contradictions:
  - id: loop_state_persistence_conflict
    subject: SmolClaw loop state
    predicate: persistence
    sources:
      - current-loop-design
      - stale-loop-note
""")
    return suite_path


def test_load_memory_eval_suite_reads_corpus_frontmatter(temp_dir):
    suite_path = _write_suite(temp_dir)

    suite = load_memory_eval_suite(suite_path)

    assert suite.id == "memory_corpus_demo"
    assert [source.source_id for source in suite.corpus] == ["roadmap", "anthropic-agents"]
    assert suite.corpus[1].metadata["source_url"].startswith("https://")
    assert suite.questions[0].expected_sources == ["roadmap"]


def test_load_memory_eval_suite_reads_claims_and_hygiene_expectations(temp_dir):
    suite_path = _write_hygiene_suite(temp_dir)

    suite = load_memory_eval_suite(suite_path)

    assert suite.corpus[0].metadata["claims"][0]["object"] == "durable"
    assert suite.staleness[0].source_id == "current-loop-design"
    assert suite.contradictions[0].subject == "SmolClaw loop state"


def test_memory_eval_runner_scores_sources_entities_and_relationships(temp_dir):
    suite_path = _write_suite(temp_dir)
    output_dir = os.path.join(temp_dir, "reports")

    report = MemoryEvalRunner(output_dir=output_dir).run(suite_path)

    assert report.status == "passed"
    assert report.score == 1.0
    assert report.corpus_size == 2
    assert report.entity_count >= 4
    assert report.relationship_count >= 3
    assert os.path.exists(report.output_path)
    with open(report.output_path, encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["suite_id"] == "memory_corpus_demo"
    assert saved["questions"][0]["checks"]["source_retrieval"] is True


def test_memory_eval_suite_report_aggregates_checks_and_score_deltas(temp_dir):
    first = MemoryEvalRunner().run(_write_suite(temp_dir))
    second = MemoryEvalRunner().run(_write_second_suite(temp_dir))

    suite = build_memory_eval_suite_report(
        [first, second],
        baseline={"memory_corpus_demo": 0.5},
    )

    assert suite["status"] == "passed"
    assert suite["suite_count"] == 2
    assert suite["passed"] == 2
    assert suite["average_score"] == 1.0
    assert suite["checks"]["source_retrieval"]["rate"] == 1.0
    assert suite["score_deltas"]["memory_corpus_demo"]["delta"] == 0.5
    assert suite["score_deltas"]["memory_corpus_second"]["baseline"] is None


def test_memory_eval_regressions_reports_excessive_score_drop(temp_dir):
    report = MemoryEvalRunner().run(_write_suite(temp_dir))
    suite = build_memory_eval_suite_report(
        [report],
        baseline={"memory_corpus_demo": 1.25},
    )

    regressions = memory_eval_regressions(suite, max_score_drop=0.1)

    assert regressions == [{
        "suite_id": "memory_corpus_demo",
        "current": 1.0,
        "baseline": 1.25,
        "delta": -0.25,
        "max_score_drop": 0.1,
    }]


def test_memory_eval_runner_scores_staleness_and_contradictions(temp_dir):
    report = MemoryEvalRunner().run(_write_hygiene_suite(temp_dir))

    assert report.status == "passed"
    assert report.score == 1.0
    checks = {item.expectation_id: item for item in report.hygiene_reports}
    assert checks["current_loop_design_is_fresh"].passed is True
    assert checks["stale_loop_note_is_stale"].details["actual"] == "stale"
    assert checks["loop_state_persistence_conflict"].check == "contradiction"
    assert len(checks["loop_state_persistence_conflict"].details["matched_claims"]) == 2


def test_project_docs_memory_eval_suite_passes():
    suite_path = os.path.join(os.getcwd(), "docs", "smolclaw-memory-eval.yaml")

    report = MemoryEvalRunner().run(suite_path)

    assert report.status == "passed"
    assert report.corpus_size >= 4
    assert any(item.check == "staleness" for item in report.hygiene_reports)
    assert report.question_reports[0].checks["source_retrieval"] is True


def test_latest_memory_eval_summary_uses_newest_report(temp_dir):
    reports_dir = os.path.join(temp_dir, "evals", "memory")
    old_suite = _write_suite(os.path.join(temp_dir, "old"))
    new_suite = _write_hygiene_suite(os.path.join(temp_dir, "new"))
    MemoryEvalRunner(output_dir=reports_dir).run(old_suite)
    latest = MemoryEvalRunner(output_dir=reports_dir).run(new_suite)

    summary = load_latest_memory_eval_summary(os.path.join(temp_dir, "evals"))

    assert latest.suite_id in summary
    assert "status=passed" in summary
    assert "Memory corpus checks passed" in summary


def test_memory_eval_runner_fails_missing_staleness_metadata(temp_dir):
    suite_path = _write_suite(temp_dir)
    with open(suite_path, "a", encoding="utf-8") as handle:
        handle.write("""
staleness:
  - id: roadmap_needs_capture_date
    source_id: roadmap
    expected: fresh
    max_age_days: 30
    as_of: "2026-06-24"
""")

    report = MemoryEvalRunner().run(suite_path)

    assert report.status == "failed"
    assert report.hygiene_reports[0].check == "staleness"
    assert report.hygiene_reports[0].details["missing_captured_at"] is True


def test_memory_eval_suite_report_aggregates_hygiene_checks(temp_dir):
    first = MemoryEvalRunner().run(_write_hygiene_suite(temp_dir))

    suite = build_memory_eval_suite_report([first])

    assert suite["checks"]["staleness"]["rate"] == 1.0
    assert suite["checks"]["contradiction"]["rate"] == 1.0


def test_memory_eval_runner_rag_mode_scores_ingested_sources_and_graph(temp_dir):
    suite_path = _write_suite(temp_dir)
    output_dir = os.path.join(temp_dir, "reports")

    report = MemoryEvalRunner(
        mode="rag",
        output_dir=output_dir,
        llm=OfflineMemoryEvalLlm(),
    ).run(suite_path)

    assert report.mode == "rag"
    assert report.status == "passed"
    assert report.score == 1.0
    first = report.question_reports[0]
    assert first.checks["source_retrieval"] is True
    assert first.checks["entity_coverage"] is True
    assert first.checks["relationship_coverage"] is True
    assert first.checks["term_coverage"] is True
    assert "roadmap" in first.retrieved_sources
    assert {"SmolClaw", "Long-running loops"}.issubset(set(first.matched_entities))
    assert {
        "source": "SmolClaw",
        "relation": "prioritizes",
        "target": "Long-running loops",
        "source_id": "",
    } in first.matched_relationships
    assert first.missing_sources == []
    assert first.missing_entities == []
    assert first.missing_relationships == []
    assert first.missing_terms == []
    assert first.retrieval_details["bm25_excerpt_ids"]
    assert first.retrieval_details["bm25_sources"]
    assert os.path.exists(os.path.join(output_dir, "memory_corpus_demo.rag-memory-eval.json"))


def test_memory_eval_runner_answer_mode_grades_citations_and_source_kinds(temp_dir):
    suite_path = _write_suite(temp_dir)
    output_dir = os.path.join(temp_dir, "reports")

    report = MemoryEvalRunner(
        mode="answer",
        output_dir=output_dir,
        llm=OfflineMemoryEvalLlm(),
    ).run(suite_path)

    assert report.mode == "answer"
    assert report.status == "passed"
    assert report.score == 1.0
    first = report.question_reports[0]
    assert first.checks["answer_citations"] is True
    assert first.checks["source_kind_distinction"] is True
    assert "roadmap" in first.answer
    assert os.path.exists(os.path.join(output_dir, "memory_corpus_demo.answer-memory-eval.json"))


def test_memory_eval_runner_answer_mode_reports_missing_citations(temp_dir):
    suite_path = _write_suite(temp_dir)

    report = MemoryEvalRunner(
        mode="answer",
        llm=UncitedAnswerLlm(),
    ).run(suite_path)

    assert report.status == "failed"
    first = report.question_reports[0]
    assert first.checks["answer_citations"] is False
    assert first.checks["source_kind_distinction"] is False
    assert first.missing_citations == ["roadmap"]
    assert first.missing_source_kinds == ["roadmap"]


def test_memory_eval_runner_reports_missing_evidence(temp_dir):
    suite_path = _write_suite(temp_dir)
    with open(suite_path, "a", encoding="utf-8") as handle:
        handle.write("""
  - id: unsupported_claim
    query: What supports browser control?
    expected_sources:
      - missing-source
    expected_entities:
      - Browser control
    required_terms:
      - sandbox
""")

    report = MemoryEvalRunner().run(suite_path)

    assert report.status == "failed"
    failed = report.question_reports[-1]
    assert failed.checks["source_retrieval"] is False
    assert failed.missing_sources == ["missing-source"]
    assert failed.missing_entities == ["Browser control"]
    assert failed.missing_terms == ["sandbox"]


def test_memory_eval_rejects_corpus_paths_outside_suite(temp_dir):
    suite_path = os.path.join(temp_dir, "memory-eval.yaml")
    _write_file(suite_path, """
id: bad
corpus:
  - path: ../outside.md
questions:
  - id: q
    query: q
""")

    with pytest.raises(ValueError, match="escapes"):
        load_memory_eval_suite(suite_path)


def test_run_memory_eval_script_outputs_json(temp_dir, capsys):
    suite_path = _write_suite(temp_dir)
    output_dir = os.path.join(temp_dir, "reports")

    exit_code = run_memory_eval_main([suite_path, "--output", output_dir])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "passed"
    assert os.path.exists(os.path.join(output_dir, "memory_corpus_demo.memory-eval.json"))


def test_run_memory_eval_script_outputs_suite_report_and_baseline(temp_dir, capsys):
    first = _write_suite(temp_dir)
    second = _write_second_suite(temp_dir)
    baseline_path = os.path.join(temp_dir, "baseline.json")

    exit_code = run_memory_eval_main([first, second, "--write-baseline", baseline_path])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["suite_count"] == 2
    assert payload["status"] == "passed"
    assert os.path.exists(baseline_path)


def test_run_memory_eval_script_fails_on_score_regression(temp_dir, capsys):
    suite_path = _write_suite(temp_dir)
    baseline_path = os.path.join(temp_dir, "baseline.json")
    _write_file(baseline_path, json.dumps({"memory_corpus_demo": 1.25}))

    exit_code = run_memory_eval_main([
        suite_path,
        "--baseline",
        baseline_path,
        "--max-score-drop",
        "0.1",
    ])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["regressions"][0]["suite_id"] == "memory_corpus_demo"


def test_ci_memory_eval_runs_default_deterministic_suites(monkeypatch, capsys):
    monkeypatch.delenv("SMOLCLAW_MEMORY_EVAL_SUITES", raising=False)
    monkeypatch.delenv("SMOLCLAW_MEMORY_EVAL_BASELINE", raising=False)
    monkeypatch.setenv("SMOLCLAW_MEMORY_EVAL_OUTPUT", "")

    exit_code = ci_memory_eval_main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["suite_count"] == 2


def test_smolclaw_memory_eval_command_outputs_json(temp_dir):
    suite_path = _write_suite(temp_dir)
    output_dir = os.path.join(temp_dir, "reports")

    result = CliRunner().invoke(
        cli_app,
        ["memory-eval", suite_path, "--output", output_dir],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "deterministic"
    assert payload["status"] == "passed"
    assert os.path.exists(os.path.join(output_dir, "memory_corpus_demo.memory-eval.json"))


def test_smolclaw_memory_eval_command_outputs_suite_report_with_baseline(temp_dir):
    first = _write_suite(temp_dir)
    second = _write_second_suite(temp_dir)
    baseline_path = os.path.join(temp_dir, "baseline.json")
    _write_file(baseline_path, json.dumps({"memory_corpus_demo": 0.75}))

    result = CliRunner().invoke(
        cli_app,
        ["memory-eval", first, second, "--baseline", baseline_path],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["suite_count"] == 2
    assert payload["score_deltas"]["memory_corpus_demo"]["delta"] == 0.25

    _write_file(baseline_path, json.dumps({"memory_corpus_demo": 1.25}))
    result = CliRunner().invoke(
        cli_app,
        [
            "memory-eval",
            first,
            "--baseline",
            baseline_path,
            "--max-score-drop",
            "0.1",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["regressions"][0]["suite_id"] == "memory_corpus_demo"
