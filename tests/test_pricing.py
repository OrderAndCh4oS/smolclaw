import time

from app.pricing import aggregate_cost, estimate_record_cost, format_costs, pricing_for_model
from app.usage import LlmUsageRecord


def _record(model="gpt-5.4-mini", prompt=1000, completion=500, total=1500, cached=False):
    return LlmUsageRecord(
        timestamp=time.time(),
        category="agent_turn",
        operation="tool_completion",
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        duration_ms=100,
        cached=cached,
    )


def test_pricing_resolves_exact_and_prefixed_models():
    assert pricing_for_model("gpt-5.4-mini").input_per_1m == pricing_for_model("gpt-5.4-mini-preview").input_per_1m
    assert pricing_for_model("gpt-5.4-pro").input_per_1m == pricing_for_model("gpt-5.4").input_per_1m


def test_estimates_codex_credit_cost_per_million_tokens():
    estimate = estimate_record_cost(_record())

    assert estimate.unit == "credits"
    assert float(estimate.amount) == 0.07525


def test_estimates_embedding_usd_cost_from_input_tokens():
    estimate = estimate_record_cost(_record(model="text-embedding-3-small", prompt=1000000, completion=0))

    assert estimate.unit == "usd"
    assert float(estimate.amount) == 0.02


def test_aggregate_tracks_unknown_models_without_costing_them():
    costs = aggregate_cost([
        _record(model="gpt-5.4", prompt=1000, completion=0),
        _record(model="custom-model", prompt=1000, completion=1000),
    ])

    assert costs["pricing_table_version"] == "2026-06-23"
    assert costs["totals"]["credits"] == 0.0625
    assert costs["unknown_calls"] == 1
    assert costs["unknown_models"] == ["custom-model"]


def test_format_costs_renders_compact_known_and_unknown_costs():
    text = format_costs({
        "totals": {"credits": 1.23456, "usd": 0.00234},
        "unknown_calls": 2,
        "unknown_models": ["custom"],
    }, compact=True)

    assert text == "cost:1.235cr usd:$0.0023 unpriced:2"
