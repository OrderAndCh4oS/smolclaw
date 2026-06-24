#!/bin/bash
set -e

echo "=== Tier 1: Unit Tests ==="
pytest

echo ""
echo "=== Tier 1: Memory Eval Suite ==="
python scripts/ci_memory_eval.py

echo ""
echo "=== Tier 2: Smoke Tests ==="
python scripts/smoke_test.py

echo ""
echo "=== Tier 2: Integration Tests ==="
python scripts/integration_test.py

echo ""
echo "=== Tier 2: Regression Tests ==="
python scripts/regression_test.py

echo ""
echo "=== All tiers passed ==="
