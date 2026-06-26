#!/usr/bin/env python3
"""Run a local SmolClaw agent evaluation task."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from typing import Any

from app.agent_eval import AgentEvalRunner, report_to_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a SmolClaw agent eval task")
    parser.add_argument(
        "task_dir",
        nargs="+",
        help="One or more directories containing task.yaml and optional repo/",
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "recorded", "live"],
        default="mock",
        help="Eval execution mode. Mock and recorded are deterministic; live runs smolclaw run.",
    )
    parser.add_argument("--output", help="Directory for eval reports")
    parser.add_argument("--model", help="Model to use for live eval mode")
    parser.add_argument("--agent", help="Agent name to use for live eval mode")
    parser.add_argument("--max-turns", type=int, default=3, help="Maximum live goal-loop turns")
    parser.add_argument("--timeout", type=int, default=300, help="Live eval subprocess timeout in seconds")
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Keep the temporary copied workspace after the run",
    )
    parser.add_argument(
        "--baseline",
        help="Optional prior suite/report JSON used to calculate per-task score deltas",
    )
    parser.add_argument(
        "--write-baseline",
        help="Optional path to write the current suite JSON for future delta comparisons",
    )
    parser.add_argument(
        "--max-score-drop",
        type=float,
        default=None,
        help="Fail when any baseline score delta is below -N. Use 0 to fail on any regression.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = AgentEvalRunner(
        mode=args.mode,
        output_dir=args.output,
        keep_workspace=args.keep_workspace,
        model=args.model,
        agent=args.agent,
        max_turns=args.max_turns,
        timeout_seconds=args.timeout,
    )
    reports = []
    try:
        for task_dir in args.task_dir:
            reports.append(runner.run(task_dir))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if len(reports) == 1 and not args.baseline and not args.write_baseline:
        print(report_to_json(reports[0]))
        return 0 if reports[0].status == "passed" else 2
    baseline = load_agent_eval_baseline_scores(args.baseline) if args.baseline else {}
    suite = build_agent_eval_suite_report(reports, baseline=baseline)
    regressions = (
        agent_eval_regressions(suite, max_score_drop=args.max_score_drop)
        if args.max_score_drop is not None
        else []
    )
    if regressions:
        suite["status"] = "failed"
        suite["regressions"] = regressions
    if args.write_baseline:
        with open(args.write_baseline, "w", encoding="utf-8") as handle:
            json.dump(suite, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(agent_eval_suite_report_to_json(suite))
    return 0 if suite["status"] == "passed" else 2


def build_agent_eval_suite_report(reports, *, baseline: dict[str, float]) -> dict[str, Any]:
    report_payloads = [report.to_dict() for report in reports]
    passed = sum(1 for report in reports if report.status == "passed")
    failed = len(reports) - passed
    check_counts: dict[str, dict[str, int | float]] = {}
    raw_check_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    failure_classes: list[str] = []
    recommended_actions: list[str] = []
    score_deltas: dict[str, dict[str, float | None]] = {}
    for report in reports:
        for check, ok in report.checks.items():
            raw_check_counts[check][1] += 1
            if ok:
                raw_check_counts[check][0] += 1
        _extend_unique(failure_classes, report.failure_classes)
        _extend_unique(recommended_actions, report.recommended_actions)
        baseline_score = baseline.get(report.task_id)
        score_deltas[report.task_id] = {
            "current": report.score,
            "baseline": baseline_score,
            "delta": None if baseline_score is None else report.score - baseline_score,
        }
    for check, (check_passed, total) in sorted(raw_check_counts.items()):
        check_counts[check] = {
            "passed": check_passed,
            "total": total,
            "rate": check_passed / total if total else 0.0,
        }
    average_score = (
        sum(report.score for report in reports) / len(reports)
        if reports
        else 0.0
    )
    return {
        "status": "passed" if failed == 0 else "failed",
        "mode": reports[0].mode if reports else None,
        "task_count": len(reports),
        "passed": passed,
        "failed": failed,
        "average_score": average_score,
        "checks": check_counts,
        "failure_classes": failure_classes,
        "recommended_actions": recommended_actions,
        "score_deltas": score_deltas,
        "reports": report_payloads,
        "created_at": time.time(),
    }


def load_agent_eval_baseline_scores(path: str) -> dict[str, float]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return _extract_baseline_scores(payload)


def agent_eval_regressions(suite_report: dict[str, Any], *, max_score_drop: float) -> list[dict[str, Any]]:
    regressions: list[dict[str, Any]] = []
    for task_id, delta in (suite_report.get("score_deltas") or {}).items():
        if not isinstance(delta, dict) or delta.get("delta") is None:
            continue
        if float(delta["delta"]) < -max_score_drop:
            regressions.append({
                "task_id": str(task_id),
                "current": float(delta["current"]),
                "baseline": float(delta["baseline"]),
                "delta": float(delta["delta"]),
                "max_score_drop": max_score_drop,
            })
    return regressions


def agent_eval_suite_report_to_json(suite_report: dict[str, Any]) -> str:
    return json.dumps(suite_report, indent=2, sort_keys=True)


def _extract_baseline_scores(payload: Any) -> dict[str, float]:
    scores: dict[str, float] = {}
    if isinstance(payload, dict) and isinstance(payload.get("reports"), list):
        for report in payload["reports"]:
            if isinstance(report, dict) and "task_id" in report and "score" in report:
                scores[str(report["task_id"])] = float(report["score"])
        return scores
    if isinstance(payload, dict) and "task_id" in payload and "score" in payload:
        return {str(payload["task_id"]): float(payload["score"])}
    if isinstance(payload, dict):
        for task_id, value in payload.items():
            if isinstance(value, dict) and "score" in value:
                scores[str(task_id)] = float(value["score"])
            elif isinstance(value, (int, float)):
                scores[str(task_id)] = float(value)
            elif isinstance(value, dict):
                for nested_score_id, nested_score in _extract_baseline_scores(value).items():
                    scores[nested_score_id] = nested_score
    return scores


def _extend_unique(target: list[str], values: list[str]):
    seen = set(target)
    for value in values:
        if value not in seen:
            target.append(value)
            seen.add(value)


if __name__ == "__main__":
    raise SystemExit(main())
