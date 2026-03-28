import logging
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger("smolclaw.hooks")

HookFn = Callable[[Dict[str, Any]], Awaitable[None]]


class HookRunner:
    """Lifecycle hook system for firing events at key agent loop points."""

    def __init__(self):
        self._hooks: Dict[str, List[HookFn]] = {}

    def on(self, event: str, fn: HookFn):
        """Register a hook for the given event."""
        self._hooks.setdefault(event, []).append(fn)

    def off(self, event: str, fn: HookFn):
        """Unregister a hook."""
        if event in self._hooks:
            self._hooks[event] = [f for f in self._hooks[event] if f is not fn]

    async def fire(self, event: str, context: Dict[str, Any] = None):
        """Fire all hooks registered for the given event."""
        context = context or {}
        for fn in self._hooks.get(event, []):
            try:
                await fn(context)
            except Exception as e:
                logger.warning(f"Hook error on {event}: {e}")

    @property
    def events(self) -> List[str]:
        """List all registered event names."""
        return list(self._hooks.keys())


# Standard event names
ON_SESSION_START = "on_session_start"
ON_BEFORE_TURN = "on_before_turn"
ON_AFTER_TURN = "on_after_turn"
ON_SESSION_END = "on_session_end"
ON_CONTRADICTION = "on_contradiction"
ON_BEFORE_TOOL = "on_before_tool"
ON_AFTER_TOOL = "on_after_tool"
