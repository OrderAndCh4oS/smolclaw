"""Tests for token usage tracking, audit trail, and persistence."""
import json
import os
import time

import pytest

from app.usage import LlmUsageRecord, TurnUsage, SessionUsage, UsageCollector, UsagePersistHook


def _make_record(category="agent_turn", prompt=100, completion=50, total=150, duration=500, cached=False):
    return LlmUsageRecord(
        timestamp=time.time(),
        category=category,
        operation="tool_completion",
        model="gpt-4.1-mini",
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        duration_ms=duration,
        cached=cached,
    )


class TestLlmUsageRecord:
    def test_fields(self):
        rec = _make_record()
        assert rec.prompt_tokens == 100
        assert rec.completion_tokens == 50
        assert rec.total_tokens == 150
        assert rec.duration_ms == 500
        assert rec.cached is False

    def test_cached_record(self):
        rec = _make_record(cached=True, prompt=0, completion=0, total=0, duration=0)
        assert rec.cached is True
        assert rec.total_tokens == 0


class TestTurnUsage:
    def test_empty_turn(self):
        turn = TurnUsage(iteration=0)
        assert turn.prompt_tokens == 0
        assert turn.completion_tokens == 0
        assert turn.total_tokens == 0
        assert turn.llm_duration_ms == 0

    def test_aggregates_calls(self):
        turn = TurnUsage(iteration=1)
        turn.llm_calls.append(_make_record(prompt=100, completion=50, total=150, duration=500))
        turn.llm_calls.append(_make_record(prompt=200, completion=80, total=280, duration=700))
        assert turn.prompt_tokens == 300
        assert turn.completion_tokens == 130
        assert turn.total_tokens == 430
        assert turn.llm_duration_ms == 1200

    def test_to_dict(self):
        turn = TurnUsage(iteration=0, tool_duration_ms=300)
        turn.llm_calls.append(_make_record(prompt=100, completion=50, total=150, duration=500))
        d = turn.to_dict()
        assert d["iteration"] == 0
        assert d["total_tokens"] == 150
        assert d["tool_duration_ms"] == 300
        assert d["llm_calls"] == 1


class TestSessionUsage:
    def test_empty_session(self):
        su = SessionUsage(session_key="test")
        assert su.total_tokens == 0
        assert su.total_duration_ms == 0

    def test_aggregates_turns_and_background(self):
        su = SessionUsage(session_key="test")
        turn = TurnUsage(iteration=0)
        turn.llm_calls.append(_make_record(prompt=100, completion=50, total=150, duration=500))
        su.turns.append(turn)
        su.background_calls.append(_make_record(category="consolidation", prompt=200, completion=30, total=230, duration=1000))
        assert su.total_prompt_tokens == 300
        assert su.total_completion_tokens == 80
        assert su.total_tokens == 380
        assert su.total_duration_ms == 1500

    def test_by_category(self):
        su = SessionUsage(session_key="test")
        turn = TurnUsage(iteration=0)
        turn.llm_calls.append(_make_record(category="agent_turn", total=100))
        turn.llm_calls.append(_make_record(category="agent_turn", total=200))
        su.turns.append(turn)
        su.background_calls.append(_make_record(category="consolidation", total=50))

        cats = su.by_category()
        assert "agent_turn" in cats
        assert "consolidation" in cats
        assert cats["agent_turn"]["total_tokens"] == 300
        assert cats["agent_turn"]["count"] == 2
        assert cats["consolidation"]["total_tokens"] == 50
        assert cats["consolidation"]["count"] == 1

    def test_summary_dict(self):
        su = SessionUsage(session_key="test")
        turn = TurnUsage(iteration=0)
        turn.llm_calls.append(_make_record(total=100, prompt=60, completion=40, duration=500))
        su.turns.append(turn)
        d = su.summary_dict()
        assert d["session_key"] == "test"
        assert d["totals"]["total_tokens"] == 100
        assert d["totals"]["llm_calls"] == 1
        assert len(d["turns"]) == 1
        assert "by_category" in d


class TestUsageCollector:
    def test_record_and_drain(self):
        collector = UsageCollector()
        rec = _make_record()
        collector.record(rec)
        drained = collector.drain()
        assert len(drained) == 1
        assert drained[0] is rec
        assert collector.drain() == []

    def test_category_context_manager(self):
        collector = UsageCollector()
        with collector.category("agent_turn"):
            rec = _make_record(category="unknown")
            collector.record(rec)
        assert rec.category == "agent_turn"

    def test_nested_categories(self):
        collector = UsageCollector()
        with collector.category("agent_turn"):
            with collector.category("context_retrieval"):
                rec = _make_record(category="unknown")
                collector.record(rec)
        assert rec.category == "context_retrieval"

    def test_category_restores_after_exit(self):
        collector = UsageCollector()
        with collector.category("agent_turn"):
            pass
        assert collector.current_category == "unknown"

    def test_explicit_category_not_overridden(self):
        collector = UsageCollector()
        with collector.category("agent_turn"):
            rec = _make_record(category="consolidation")
            collector.record(rec)
        assert rec.category == "consolidation"


class TestUsagePersistHook:
    @pytest.mark.asyncio
    async def test_saves_usage_json(self, temp_dir):
        hook = UsagePersistHook(temp_dir)
        su = SessionUsage(session_key="test-session")
        turn = TurnUsage(iteration=0)
        turn.llm_calls.append(_make_record(prompt=300, completion=200, total=500))
        su.turns.append(turn)

        await hook({"session_key": "test-session", "usage": su})

        path = os.path.join(temp_dir, "test-session.usage.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["session_key"] == "test-session"
        assert data["totals"]["total_tokens"] == 500

    @pytest.mark.asyncio
    async def test_noop_without_usage(self, temp_dir):
        hook = UsagePersistHook(temp_dir)
        await hook({"session_key": "test"})
        assert not os.path.exists(os.path.join(temp_dir, "test.usage.json"))
