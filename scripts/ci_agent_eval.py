#!/usr/bin/env python3
"""CI entrypoint for deterministic SmolClaw coding-agent evals."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.agent_eval import AgentEvalRunner
from app.memory_coding_eval import (
    MemoryCodingEvalRunner,
    build_memory_coding_eval_suite_report,
    memory_coding_eval_regressions,
)
from scripts.run_agent_eval import (
    agent_eval_regressions,
    build_agent_eval_suite_report,
    load_agent_eval_baseline_scores,
)


DEFAULT_AGENT_TASKS = [
    "tests/fixtures/agent_tasks/python_parser_bug",
    "tests/fixtures/agent_tasks/docs_only_change",
    "tests/fixtures/agent_tasks/blocked_secret_read",
    "tests/fixtures/agent_tasks/approval_required_command",
    "tests/fixtures/agent_tasks/generated_file_edit",
    "tests/fixtures/agent_tasks/large_repo_exploration",
    "tests/fixtures/agent_tasks/dirty_worktree_preservation",
]

DEFAULT_MEMORY_CODING_TASKS = [
    "tests/fixtures/agent_tasks/csv_memory_policy",
]


def main(argv: list[str] | None = None) -> int:
    agent_tasks = argv or _env_list("SMOLCLAW_AGENT_EVAL_TASKS") or DEFAULT_AGENT_TASKS
    memory_tasks = _env_list("SMOLCLAW_MEMORY_CODING_EVAL_TASKS") or DEFAULT_MEMORY_CODING_TASKS
    output_dir = os.environ.get("SMOLCLAW_AGENT_EVAL_OUTPUT", ".smolclaw/stores/evals/agent-ci")
    baseline_path = os.environ.get("SMOLCLAW_AGENT_EVAL_BASELINE")
    baseline = load_agent_eval_baseline_scores(baseline_path) if baseline_path else {}
    max_drop = os.environ.get("SMOLCLAW_AGENT_EVAL_MAX_DROP")
    max_score_drop = float(max_drop) if max_drop is not None else (0.0 if baseline_path else None)

    agent_report_dir = os.path.join(output_dir, "agent")
    memory_report_dir = os.path.join(output_dir, "memory-coding")
    agent_runner = AgentEvalRunner(mode="recorded", output_dir=agent_report_dir)
    memory_runner = MemoryCodingEvalRunner()

    try:
        agent_reports = [agent_runner.run(task) for task in agent_tasks]
        memory_reports = [memory_runner.run(task) for task in memory_tasks]
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    agent_suite = build_agent_eval_suite_report(agent_reports, baseline=baseline)
    memory_suite = build_memory_coding_eval_suite_report(memory_reports, baseline=baseline)
    regressions: list[dict[str, Any]] = []
    if max_score_drop is not None:
        regressions.extend(agent_eval_regressions(agent_suite, max_score_drop=max_score_drop))
        regressions.extend(memory_coding_eval_regressions(memory_suite, max_score_drop=max_score_drop))
    if regressions:
        agent_suite["status"] = "failed"
        memory_suite["status"] = "failed"

    combined = {
        "status": "passed"
        if agent_suite["status"] == "passed" and memory_suite["status"] == "passed" and not regressions
        else "failed",
        "mode": "deterministic",
        "task_count": agent_suite["task_count"] + memory_suite["task_count"],
        "agent_eval": agent_suite,
        "memory_coding_eval": memory_suite,
        "regressions": regressions,
        "created_at": time.time(),
    }

    write_baseline = os.environ.get("SMOLCLAW_AGENT_EVAL_WRITE_BASELINE")
    if write_baseline:
        os.makedirs(os.path.dirname(os.path.abspath(write_baseline)), exist_ok=True)
        with open(write_baseline, "w", encoding="utf-8") as handle:
            json.dump(combined, handle, indent=2, sort_keys=True)
            handle.write("\n")
    if memory_report_dir:
        os.makedirs(memory_report_dir, exist_ok=True)
        with open(os.path.join(memory_report_dir, "memory-coding-suite.json"), "w", encoding="utf-8") as handle:
            json.dump(memory_suite, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(combined, indent=2, sort_keys=True))
    return 0 if combined["status"] == "passed" else 2


def _env_list(name: str) -> list[str]:
    return os.environ.get(name, "").split()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
