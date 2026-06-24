#!/usr/bin/env python3
"""CI entrypoint for deterministic SmolClaw memory evals."""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.run_memory_eval import main as run_memory_eval_main


DEFAULT_SUITES = [
    "tests/fixtures/memory_eval/agentic_coding/memory-eval.yaml",
    "docs/smolclaw-memory-eval.yaml",
]


def main(argv: list[str] | None = None) -> int:
    if argv:
        suites = argv
    else:
        suites = os.environ.get("SMOLCLAW_MEMORY_EVAL_SUITES", "").split()
        if not suites:
            suites = DEFAULT_SUITES

    args = [*suites]
    output_dir = os.environ.get("SMOLCLAW_MEMORY_EVAL_OUTPUT", ".smolclaw/stores/evals/memory-ci")
    if output_dir:
        args.extend(["--output", output_dir])

    baseline = os.environ.get("SMOLCLAW_MEMORY_EVAL_BASELINE")
    if baseline:
        args.extend(["--baseline", baseline])
        args.extend(["--max-score-drop", os.environ.get("SMOLCLAW_MEMORY_EVAL_MAX_DROP", "0")])

    write_baseline = os.environ.get("SMOLCLAW_MEMORY_EVAL_WRITE_BASELINE")
    if write_baseline:
        args.extend(["--write-baseline", write_baseline])

    return run_memory_eval_main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
