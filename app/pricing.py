"""Model pricing helpers for live session cost estimates."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from app.model_defaults import (
    DEFAULT_OPENAI_CHAT_MODEL,
    DEFAULT_OPENAI_EMBEDDING_MODEL,
    DEFAULT_OPENAI_MEMORY_EXTRACT_MODEL,
    DEFAULT_OPENAI_MEMORY_QUERY_MODEL,
)


PRICING_TABLE_VERSION = "2026-06-23"


@dataclass(frozen=True)
class ModelPrice:
    unit: str
    input_per_1m: Decimal
    output_per_1m: Decimal = Decimal("0")
    cached_input_per_1m: Decimal | None = None
    source: str = ""
    effective_date: str = PRICING_TABLE_VERSION


@dataclass(frozen=True)
class CostEstimate:
    unit: str
    amount: Decimal
    known: bool = True

    def to_dict(self) -> dict:
        return {
            "unit": self.unit,
            "amount": float(self.amount),
            "known": self.known,
        }


CODEX_PRICING_SOURCE = "https://developers.openai.com/codex/pricing#how-do-credits-work"
EMBEDDING_PRICING_SOURCE = "https://developers.openai.com/api/docs/guides/embeddings#embedding-models"

# Update this map when published pricing changes. Values are per 1M tokens.
MODEL_PRICING: dict[str, ModelPrice] = {
    DEFAULT_OPENAI_CHAT_MODEL: ModelPrice(
        unit="credits",
        input_per_1m=Decimal("125"),
        cached_input_per_1m=Decimal("12.50"),
        output_per_1m=Decimal("750"),
        source=CODEX_PRICING_SOURCE,
    ),
    DEFAULT_OPENAI_MEMORY_QUERY_MODEL: ModelPrice(
        unit="credits",
        input_per_1m=Decimal("62.50"),
        cached_input_per_1m=Decimal("6.250"),
        output_per_1m=Decimal("375"),
        source=CODEX_PRICING_SOURCE,
    ),
    DEFAULT_OPENAI_MEMORY_EXTRACT_MODEL: ModelPrice(
        unit="credits",
        input_per_1m=Decimal("18.75"),
        cached_input_per_1m=Decimal("1.875"),
        output_per_1m=Decimal("113"),
        source=CODEX_PRICING_SOURCE,
    ),
    DEFAULT_OPENAI_EMBEDDING_MODEL: ModelPrice(
        unit="usd",
        input_per_1m=Decimal("0.02"),
        source=EMBEDDING_PRICING_SOURCE,
    ),
    "text-embedding-3-large": ModelPrice(
        unit="usd",
        input_per_1m=Decimal("0.13"),
        source=EMBEDDING_PRICING_SOURCE,
    ),
    "text-embedding-ada-002": ModelPrice(
        unit="usd",
        input_per_1m=Decimal("0.10"),
        source=EMBEDDING_PRICING_SOURCE,
    ),
}


def pricing_for_model(model: str | None) -> ModelPrice | None:
    if not model:
        return None
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    matches = [
        (prefix, price)
        for prefix, price in MODEL_PRICING.items()
        if model.startswith(prefix)
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item[0]))[1]


def estimate_record_cost(record) -> CostEstimate:
    price = pricing_for_model(getattr(record, "model", None))
    if price is None:
        return CostEstimate(unit="unknown", amount=Decimal("0"), known=False)
    if getattr(record, "cached", False) and getattr(record, "total_tokens", 0) == 0:
        return CostEstimate(unit=price.unit, amount=Decimal("0"))

    prompt_tokens = Decimal(str(max(0, int(getattr(record, "prompt_tokens", 0) or 0))))
    completion_tokens = Decimal(str(max(0, int(getattr(record, "completion_tokens", 0) or 0))))
    input_rate = price.input_per_1m
    amount = (prompt_tokens * input_rate + completion_tokens * price.output_per_1m) / Decimal("1000000")
    return CostEstimate(unit=price.unit, amount=amount)


def aggregate_cost(records: Iterable) -> dict:
    totals: dict[str, Decimal] = {}
    unknown_models: set[str] = set()
    unknown_calls = 0
    for record in records:
        estimate = estimate_record_cost(record)
        if not estimate.known:
            unknown_calls += 1
            model = str(getattr(record, "model", "") or "unknown")
            unknown_models.add(model)
            continue
        totals[estimate.unit] = totals.get(estimate.unit, Decimal("0")) + estimate.amount
    return {
        "pricing_table_version": PRICING_TABLE_VERSION,
        "totals": {unit: float(value) for unit, value in sorted(totals.items())},
        "unknown_calls": unknown_calls,
        "unknown_models": sorted(unknown_models),
    }


def format_costs(costs: dict, *, compact: bool = False) -> str:
    totals = costs.get("totals") or {}
    parts = []
    credits = totals.get("credits")
    if credits is not None:
        parts.append(f"cost:{_format_decimal(Decimal(str(credits)), 3)}cr")
    usd = totals.get("usd")
    if usd is not None:
        parts.append(f"usd:${_format_decimal(Decimal(str(usd)), 4)}")
    unknown_calls = int(costs.get("unknown_calls") or 0)
    if unknown_calls:
        parts.append(f"unpriced:{unknown_calls}" if compact else f"unpriced:{unknown_calls} call(s)")
    return " ".join(parts) if parts else "cost:0"


def _format_decimal(value: Decimal, places: int) -> str:
    quant = Decimal("1").scaleb(-places)
    rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    text = f"{rounded:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
