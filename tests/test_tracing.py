"""Tests for the tracing module."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.tracing import (
    NoOpSpan,
    NoOpTracer,
    get_tracer,
    trace_agent_turn,
    trace_llm_call,
    trace_retrieval,
)
from app.tools.middleware import TracingMiddleware


class TestNoOpSpan:
    def test_set_attribute(self):
        span = NoOpSpan()
        span.set_attribute("key", "value")  # should not raise

    def test_record_exception(self):
        span = NoOpSpan()
        span.record_exception(RuntimeError("test"))

    def test_context_manager(self):
        with NoOpSpan() as span:
            span.set_attribute("x", 1)


class TestNoOpTracer:
    def test_start_span(self):
        tracer = NoOpTracer()
        span = tracer.start_span("test")
        assert isinstance(span, NoOpSpan)

    def test_start_as_current_span(self):
        tracer = NoOpTracer()
        with tracer.start_as_current_span("test") as span:
            span.set_attribute("key", "value")
            assert isinstance(span, NoOpSpan)


class TestGetTracer:
    def test_returns_noop_without_init(self):
        """Before init, get_tracer returns a no-op tracer."""
        tracer = get_tracer()
        assert isinstance(tracer, NoOpTracer)


class TestTraceContextManagers:
    def test_trace_agent_turn(self):
        with trace_agent_turn("session-1", 0, "gpt-4") as span:
            assert span is not None

    def test_trace_retrieval(self):
        with trace_retrieval("test query") as span:
            span.set_attribute("retrieval.included_count", 5)

    def test_trace_llm_call(self):
        with trace_llm_call("completion", "gpt-4") as span:
            span.set_attribute("llm.prompt_tokens", 100)


class TestTracingMiddleware:
    @pytest.mark.asyncio
    async def test_creates_span_and_passes_through(self):
        mw = TracingMiddleware()
        tool = MagicMock()
        tool.name = "test_tool"
        tool.execute = AsyncMock(return_value="ok")

        async def next_fn(t, kw):
            return await t.execute(**kw)

        result = await mw(tool, {"q": "test"}, next_fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_propagates_exception(self):
        mw = TracingMiddleware()
        tool = MagicMock()
        tool.name = "boom"

        async def next_fn(t, kw):
            raise ValueError("tool error")

        with pytest.raises(ValueError, match="tool error"):
            await mw(tool, {}, next_fn)
