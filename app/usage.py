"""Token usage tracking, audit trail, and persistence for LLM calls."""
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LlmUsageRecord:
    timestamp: float
    category: str  # "agent_turn" | "consolidation" | "context_retrieval" | "ingestion" | "journal" | "session_index"
    operation: str  # "tool_completion" | "completion" | "embedding" | "embeddings"
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int
    cached: bool = False


@dataclass
class TurnUsage:
    iteration: int
    llm_calls: list = field(default_factory=list)
    tool_duration_ms: int = 0

    @property
    def prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.llm_calls)

    @property
    def completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self.llm_calls)

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.llm_calls)

    @property
    def llm_duration_ms(self) -> int:
        return sum(r.duration_ms for r in self.llm_calls)

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_duration_ms": self.llm_duration_ms,
            "tool_duration_ms": self.tool_duration_ms,
            "llm_calls": len(self.llm_calls),
        }


@dataclass
class SessionUsage:
    session_key: str
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    turns: list = field(default_factory=list)
    background_calls: list = field(default_factory=list)

    @property
    def total_prompt_tokens(self) -> int:
        turn_sum = sum(t.prompt_tokens for t in self.turns)
        bg_sum = sum(r.prompt_tokens for r in self.background_calls)
        return turn_sum + bg_sum

    @property
    def total_completion_tokens(self) -> int:
        turn_sum = sum(t.completion_tokens for t in self.turns)
        bg_sum = sum(r.completion_tokens for r in self.background_calls)
        return turn_sum + bg_sum

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    @property
    def total_duration_ms(self) -> int:
        turn_sum = sum(t.llm_duration_ms for t in self.turns)
        bg_sum = sum(r.duration_ms for r in self.background_calls)
        return turn_sum + bg_sum

    def by_category(self) -> dict:
        cats = {}
        all_records = []
        for t in self.turns:
            all_records.extend(t.llm_calls)
        all_records.extend(self.background_calls)
        for r in all_records:
            if r.category not in cats:
                cats[r.category] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "count": 0, "duration_ms": 0}
            c = cats[r.category]
            c["prompt_tokens"] += r.prompt_tokens
            c["completion_tokens"] += r.completion_tokens
            c["total_tokens"] += r.total_tokens
            c["count"] += 1
            c["duration_ms"] += r.duration_ms
        return cats

    def summary_dict(self) -> dict:
        return {
            "session_key": self.session_key,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "totals": {
                "prompt_tokens": self.total_prompt_tokens,
                "completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_tokens,
                "duration_ms": self.total_duration_ms,
                "llm_calls": sum(len(t.llm_calls) for t in self.turns) + len(self.background_calls),
            },
            "by_category": self.by_category(),
            "turns": [t.to_dict() for t in self.turns],
        }


class UsageCollector:
    """Set on LLM instances to capture usage from API responses."""

    def __init__(self):
        self._records: list[LlmUsageRecord] = []
        self._category_stack: list[str] = ["unknown"]

    @contextmanager
    def category(self, cat: str):
        self._category_stack.append(cat)
        try:
            yield
        finally:
            self._category_stack.pop()

    @property
    def current_category(self) -> str:
        return self._category_stack[-1]

    def record(self, rec: LlmUsageRecord):
        if rec.category == "unknown":
            rec.category = self.current_category
        self._records.append(rec)

    def drain(self) -> list:
        records = self._records[:]
        self._records.clear()
        return records


class UsagePersistHook:
    """Hook registered on ON_SESSION_END to persist usage data as a sidecar JSON file."""

    def __init__(self, sessions_dir: str):
        self._sessions_dir = sessions_dir

    async def __call__(self, context: dict):
        usage = context.get("usage")
        session_key = context.get("session_key")
        if not usage or not session_key:
            return
        path = os.path.join(self._sessions_dir, f"{session_key}.usage.json")
        with open(path, "w") as f:
            json.dump(usage.summary_dict(), f, indent=2)
