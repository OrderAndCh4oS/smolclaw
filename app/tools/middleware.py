"""Composable middleware for tool execution."""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List

from app.tools.base import Tool

logger = logging.getLogger(__name__)

# next_fn: given (tool, kwargs), returns the tool result string
NextFn = Callable[[Tool, Dict[str, Any]], Awaitable[str]]

# middleware: given (tool, kwargs, next_fn), returns result string
MiddlewareFn = Callable[[Tool, Dict[str, Any], NextFn], Awaitable[str]]


class MiddlewareChain:
    """Builds an onion-model execution chain around tool.execute()."""

    def __init__(self, middlewares: List[MiddlewareFn] | None = None):
        self._middlewares: List[MiddlewareFn] = list(middlewares or [])

    def use(self, mw: MiddlewareFn):
        self._middlewares.append(mw)

    async def run(self, tool: Tool, kwargs: Dict[str, Any]) -> str:
        if not self._middlewares:
            return await tool.execute(**kwargs)

        async def core(t: Tool, kw: Dict[str, Any]) -> str:
            return await t.execute(**kw)

        handler = core
        for mw in reversed(self._middlewares):
            handler = _wrap(mw, handler)
        return await handler(tool, kwargs)


def _wrap(mw: MiddlewareFn, next_fn: NextFn) -> NextFn:
    async def wrapped(tool: Tool, kwargs: Dict[str, Any]) -> str:
        return await mw(tool, kwargs, next_fn)
    return wrapped


# ---------------------------------------------------------------------------
# Built-in middleware
# ---------------------------------------------------------------------------


async def logging_middleware(tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn) -> str:
    args_summary = ", ".join(f"{k}={repr(v)[:60]}" for k, v in kwargs.items())
    logger.info("tool.start %s(%s)", tool.name, args_summary)
    started = time.perf_counter()
    try:
        result = await next_fn(tool, kwargs)
        duration_ms = int((time.perf_counter() - started) * 1000)
        success = not result.startswith("Error:")
        logger.info(
            "tool.end %s duration=%dms success=%s",
            tool.name, duration_ms, success,
        )
        return result
    except Exception:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.exception("tool.error %s duration=%dms", tool.name, duration_ms)
        raise


class RetryMiddleware:
    """Retries tool execution when the result indicates an error."""

    def __init__(self, max_retries: int = 2, retry_on: tuple[str, ...] = ("Error:",)):
        self.max_retries = max_retries
        self.retry_on = retry_on

    async def __call__(self, tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn) -> str:
        last_result = ""
        for attempt in range(1 + self.max_retries):
            last_result = await next_fn(tool, kwargs)
            if not any(last_result.startswith(prefix) for prefix in self.retry_on):
                return last_result
            if attempt < self.max_retries:
                logger.warning(
                    "tool.retry %s attempt=%d result=%s",
                    tool.name, attempt + 1, last_result[:100],
                )
        return last_result


class TimeoutMiddleware:
    """Wraps tool execution in an asyncio timeout."""

    def __init__(self, timeout_seconds: float = 30):
        self.timeout_seconds = timeout_seconds

    async def __call__(self, tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn) -> str:
        try:
            return await asyncio.wait_for(
                next_fn(tool, kwargs), timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return f"Error: tool '{tool.name}' timed out after {self.timeout_seconds}s"


class CacheMiddleware:
    """In-memory cache for tool results keyed on (tool.name, kwargs)."""

    def __init__(self, ttl_seconds: float = 300):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[tuple, tuple[float, str]] = {}

    def _make_key(self, tool: Tool, kwargs: Dict[str, Any]) -> tuple:
        try:
            return (tool.name, tuple(sorted(kwargs.items())))
        except TypeError:
            return None  # unhashable kwargs — skip cache

    async def __call__(self, tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn) -> str:
        key = self._make_key(tool, kwargs)
        if key is not None:
            cached = self._cache.get(key)
            if cached:
                ts, value = cached
                if (time.time() - ts) < self.ttl_seconds:
                    logger.debug("tool.cache_hit %s", tool.name)
                    return value

        result = await next_fn(tool, kwargs)

        if key is not None and not result.startswith("Error:"):
            self._cache[key] = (time.time(), result)

        return result


class TracingMiddleware:
    """Creates OTEL spans for tool execution. No-op when tracing is disabled."""

    async def __call__(self, tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn) -> str:
        from app.tracing import get_tracer

        tracer = get_tracer()
        with tracer.start_as_current_span(f"tool.{tool.name}") as span:
            args_summary = ", ".join(f"{k}={repr(v)[:50]}" for k, v in kwargs.items())
            span.set_attribute("tool.name", tool.name)
            span.set_attribute("tool.arguments", args_summary[:200])
            started = time.perf_counter()
            try:
                result = await next_fn(tool, kwargs)
                duration_ms = int((time.perf_counter() - started) * 1000)
                span.set_attribute("tool.success", not result.startswith("Error:"))
                span.set_attribute("tool.duration_ms", duration_ms)
                return result
            except Exception as e:
                span.record_exception(e)
                raise
