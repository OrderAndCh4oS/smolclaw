#!/usr/bin/env python3
"""Run a deterministic corpus-memory eval suite."""

from __future__ import annotations

import argparse
import json
import sys

from app.memory_eval import (
    MemoryEvalRunner,
    build_memory_eval_suite_report,
    load_memory_eval_baseline_scores,
    memory_eval_regressions,
    memory_eval_report_to_json,
    memory_eval_suite_report_to_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a SmolClaw memory/knowledge-graph eval suite")
    parser.add_argument("suite", nargs="+", help="One or more memory eval YAML files")
    parser.add_argument(
        "--mode",
        choices=["deterministic", "rag", "answer"],
        default="deterministic",
        help="Eval mode. deterministic is offline; rag ingests the corpus into SmolRAG; answer asks a model to cite retrieved sources.",
    )
    parser.add_argument("--output", help="Directory for eval report JSON")
    parser.add_argument("--top-k", type=int, default=5, help="Number of corpus sources to retrieve per question")
    parser.add_argument("--model", help="Completion model for --mode answer")
    parser.add_argument("--baseline", help="Optional prior report/suite JSON for score deltas")
    parser.add_argument("--write-baseline", help="Optional path to write the current suite JSON")
    parser.add_argument(
        "--max-score-drop",
        type=float,
        default=None,
        help="Fail when any baseline score delta is below -N. Use 0 to fail on any regression.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = MemoryEvalRunner(
        mode=args.mode,
        output_dir=args.output,
        top_k=args.top_k,
        answer_model=args.model,
    )
    reports = []
    try:
        for suite in args.suite:
            reports.append(runner.run(suite))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if len(reports) == 1 and not args.baseline and not args.write_baseline:
        print(memory_eval_report_to_json(reports[0]))
        return 0 if reports[0].status == "passed" else 2
    baseline = load_memory_eval_baseline_scores(args.baseline) if args.baseline else {}
    suite_report = build_memory_eval_suite_report(reports, baseline=baseline)
    regressions = (
        memory_eval_regressions(suite_report, max_score_drop=args.max_score_drop)
        if args.max_score_drop is not None
        else []
    )
    if regressions:
        suite_report["status"] = "failed"
        suite_report["regressions"] = regressions
    if args.write_baseline:
        with open(args.write_baseline, "w", encoding="utf-8") as handle:
            json.dump(suite_report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(memory_eval_suite_report_to_json(suite_report))
    return 0 if suite_report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
