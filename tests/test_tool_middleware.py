"""Tests for tool middleware system."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.base import Tool
from app.tools.middleware import (
    CacheMiddleware,
    MiddlewareChain,
    RetryMiddleware,
    TimeoutMiddleware,
    logging_middleware,
)
from app.tools.registry import ToolRegistry


class FakeTool(Tool):
    """Minimal tool for testing."""

    def __init__(self, result: str = "ok", delay: float = 0, fail_n: int = 0,
                 tool_name: str = "fake"):
        self._result = result
        self._delay = delay
        self._fail_n = fail_n
        self._call_count = 0
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        self._call_count += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._call_count <= self._fail_n:
            return "Error: transient failure"
        return self._result


# ---------------------------------------------------------------------------
# MiddlewareChain
# ---------------------------------------------------------------------------


class TestMiddlewareChain:
    @pytest.mark.asyncio
    async def test_no_middleware(self):
        chain = MiddlewareChain()
        tool = FakeTool(result="hello")
        result = await chain.run(tool, {})
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_single_middleware(self):
        calls = []

        async def track(tool, kwargs, next_fn):
            calls.append("before")
            result = await next_fn(tool, kwargs)
            calls.append("after")
            return result

        chain = MiddlewareChain([track])
        tool = FakeTool(result="ok")
        result = await chain.run(tool, {})
        assert result == "ok"
        assert calls == ["before", "after"]

    @pytest.mark.asyncio
    async def test_middleware_ordering(self):
        """First registered = outermost (runs first on entry, last on exit)."""
        order = []

        async def outer(tool, kwargs, next_fn):
            order.append("outer_in")
            r = await next_fn(tool, kwargs)
            order.append("outer_out")
            return r

        async def inner(tool, kwargs, next_fn):
            order.append("inner_in")
            r = await next_fn(tool, kwargs)
            order.append("inner_out")
            return r

        chain = MiddlewareChain([outer, inner])
        await chain.run(FakeTool(), {})
        assert order == ["outer_in", "inner_in", "inner_out", "outer_out"]

    @pytest.mark.asyncio
    async def test_middleware_can_short_circuit(self):
        async def blocker(tool, kwargs, next_fn):
            return "blocked"

        chain = MiddlewareChain([blocker])
        tool = FakeTool(result="should not reach")
        result = await chain.run(tool, {})
        assert result == "blocked"
        assert tool._call_count == 0

    @pytest.mark.asyncio
    async def test_middleware_can_modify_kwargs(self):
        async def inject(tool, kwargs, next_fn):
            kwargs["injected"] = True
            return await next_fn(tool, kwargs)

        chain = MiddlewareChain([inject])
        tool = MagicMock(spec=Tool)
        tool.execute = AsyncMock(return_value="ok")
        await chain.run(tool, {"original": True})
        tool.execute.assert_called_once_with(original=True, injected=True)

    @pytest.mark.asyncio
    async def test_use_appends(self):
        chain = MiddlewareChain()
        order = []

        async def first(tool, kw, nxt):
            order.append(1)
            return await nxt(tool, kw)

        async def second(tool, kw, nxt):
            order.append(2)
            return await nxt(tool, kw)

        chain.use(first)
        chain.use(second)
        await chain.run(FakeTool(), {})
        assert order == [1, 2]


# ---------------------------------------------------------------------------
# LoggingMiddleware
# ---------------------------------------------------------------------------


class TestLoggingMiddleware:
    @pytest.mark.asyncio
    async def test_passes_through(self):
        chain = MiddlewareChain([logging_middleware])
        tool = FakeTool(result="data")
        result = await chain.run(tool, {"q": "test"})
        assert result == "data"

    @pytest.mark.asyncio
    async def test_logs_on_exception(self):
        tool = MagicMock(spec=Tool)
        tool.name = "boom"
        tool.execute = AsyncMock(side_effect=RuntimeError("kaboom"))
        chain = MiddlewareChain([logging_middleware])
        with pytest.raises(RuntimeError, match="kaboom"):
            await chain.run(tool, {})


# ---------------------------------------------------------------------------
# RetryMiddleware
# ---------------------------------------------------------------------------


class TestRetryMiddleware:
    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        tool = FakeTool(result="ok")
        chain = MiddlewareChain([RetryMiddleware(max_retries=2)])
        result = await chain.run(tool, {})
        assert result == "ok"
        assert tool._call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_error(self):
        tool = FakeTool(result="ok", fail_n=2)
        chain = MiddlewareChain([RetryMiddleware(max_retries=2)])
        result = await chain.run(tool, {})
        assert result == "ok"
        assert tool._call_count == 3

    @pytest.mark.asyncio
    async def test_returns_last_error_when_exhausted(self):
        tool = FakeTool(result="ok", fail_n=100)
        chain = MiddlewareChain([RetryMiddleware(max_retries=1)])
        result = await chain.run(tool, {})
        assert result.startswith("Error:")
        assert tool._call_count == 2

    @pytest.mark.asyncio
    async def test_custom_retry_prefix(self):
        tool = MagicMock(spec=Tool)
        tool.name = "t"
        call_count = 0

        async def flaky(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "FAIL: something"
            return "ok"

        tool.execute = AsyncMock(side_effect=flaky)
        chain = MiddlewareChain([RetryMiddleware(max_retries=1, retry_on=("FAIL:",))])
        result = await chain.run(tool, {})
        assert result == "ok"


# ---------------------------------------------------------------------------
# TimeoutMiddleware
# ---------------------------------------------------------------------------


class TestTimeoutMiddleware:
    @pytest.mark.asyncio
    async def test_within_timeout(self):
        tool = FakeTool(result="fast", delay=0)
        chain = MiddlewareChain([TimeoutMiddleware(timeout_seconds=5)])
        result = await chain.run(tool, {})
        assert result == "fast"

    @pytest.mark.asyncio
    async def test_exceeds_timeout(self):
        tool = FakeTool(result="slow", delay=10)
        chain = MiddlewareChain([TimeoutMiddleware(timeout_seconds=0.05)])
        result = await chain.run(tool, {})
        assert "timed out" in result


# ---------------------------------------------------------------------------
# CacheMiddleware
# ---------------------------------------------------------------------------


class TestCacheMiddleware:
    @pytest.mark.asyncio
    async def test_caches_result(self):
        tool = FakeTool(result="cached_value")
        cache = CacheMiddleware(ttl_seconds=60)
        chain = MiddlewareChain([cache])
        r1 = await chain.run(tool, {"q": "test"})
        r2 = await chain.run(tool, {"q": "test"})
        assert r1 == r2 == "cached_value"
        assert tool._call_count == 1  # second call was cached

    @pytest.mark.asyncio
    async def test_different_args_not_cached(self):
        tool = FakeTool(result="v")
        cache = CacheMiddleware(ttl_seconds=60)
        chain = MiddlewareChain([cache])
        await chain.run(tool, {"q": "a"})
        await chain.run(tool, {"q": "b"})
        assert tool._call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_cache_errors(self):
        tool = FakeTool(result="ok", fail_n=1)
        cache = CacheMiddleware(ttl_seconds=60)
        chain = MiddlewareChain([cache])
        r1 = await chain.run(tool, {})
        r2 = await chain.run(tool, {})
        assert r1.startswith("Error:")
        assert r2 == "ok"

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        import time

        tool = FakeTool(result="v")
        cache = CacheMiddleware(ttl_seconds=0.01)
        chain = MiddlewareChain([cache])
        await chain.run(tool, {})
        await asyncio.sleep(0.02)
        await chain.run(tool, {})
        assert tool._call_count == 2


# ---------------------------------------------------------------------------
# ToolRegistry middleware integration
# ---------------------------------------------------------------------------


class TestRegistryMiddleware:
    @pytest.mark.asyncio
    async def test_global_middleware_applied(self):
        calls = []

        async def track(tool, kwargs, next_fn):
            calls.append(tool.name)
            return await next_fn(tool, kwargs)

        reg = ToolRegistry()
        reg.register(FakeTool(result="a"))
        reg.use(track)
        await reg.execute("fake", {})
        assert calls == ["fake"]

    @pytest.mark.asyncio
    async def test_per_tool_middleware(self):
        calls = []

        async def track(tool, kwargs, next_fn):
            calls.append(f"per_{tool.name}")
            return await next_fn(tool, kwargs)

        reg = ToolRegistry()
        reg.register(FakeTool(result="a", tool_name="fake"))
        reg.register(FakeTool(result="b", tool_name="other"))

        reg.use_for("fake", track)
        await reg.execute("fake", {})
        await reg.execute("other", {})
        assert calls == ["per_fake"]

    @pytest.mark.asyncio
    async def test_filter_inherits_middleware(self):
        calls = []

        async def track(tool, kwargs, next_fn):
            calls.append(tool.name)
            return await next_fn(tool, kwargs)

        reg = ToolRegistry()
        reg.register(FakeTool(result="ok"))
        reg.use(track)

        filtered = reg.filter_by_names(["fake"])
        await filtered.execute("fake", {})
        assert calls == ["fake"]

    @pytest.mark.asyncio
    async def test_exception_still_caught(self):
        async def bad_middleware(tool, kwargs, next_fn):
            raise ValueError("middleware exploded")

        reg = ToolRegistry()
        reg.register(FakeTool())
        reg.use(bad_middleware)
        result = await reg.execute("fake", {})
        assert result.startswith("Error:")
        assert "middleware exploded" in result
