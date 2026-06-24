import pytest
from unittest.mock import AsyncMock

from app.hooks import HookRunner, ON_BEFORE_TURN, ON_AFTER_TURN, ON_SESSION_START


class TestHookRunner:
    @pytest.mark.asyncio
    async def test_fire_calls_registered_hook(self):
        runner = HookRunner()
        hook = AsyncMock()
        runner.on("test_event", hook)
        await runner.fire("test_event", {"key": "value"})
        hook.assert_awaited_once_with({"key": "value"})

    @pytest.mark.asyncio
    async def test_fire_multiple_hooks(self):
        runner = HookRunner()
        hook1 = AsyncMock()
        hook2 = AsyncMock()
        runner.on("test_event", hook1)
        runner.on("test_event", hook2)
        await runner.fire("test_event", {"data": 1})
        hook1.assert_awaited_once()
        hook2.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fire_no_hooks_registered(self):
        runner = HookRunner()
        # Should not raise
        await runner.fire("nonexistent_event", {})

    @pytest.mark.asyncio
    async def test_fire_with_no_context(self):
        runner = HookRunner()
        hook = AsyncMock()
        runner.on("test", hook)
        await runner.fire("test")
        hook.assert_awaited_once_with({})

    @pytest.mark.asyncio
    async def test_off_unregisters_hook(self):
        runner = HookRunner()
        hook = AsyncMock()
        runner.on("test", hook)
        runner.off("test", hook)
        await runner.fire("test", {})
        hook.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hook_error_does_not_propagate(self):
        runner = HookRunner()
        bad_hook = AsyncMock(side_effect=ValueError("boom"))
        good_hook = AsyncMock()
        runner.on("test", bad_hook)
        runner.on("test", good_hook)
        # Should not raise, and good_hook should still be called
        await runner.fire("test", {})
        good_hook.assert_awaited_once()

    def test_events_property(self):
        runner = HookRunner()
        runner.on("a", AsyncMock())
        runner.on("b", AsyncMock())
        assert set(runner.events) == {"a", "b"}


class TestHookConstants:
    def test_event_names_exist(self):
        assert ON_BEFORE_TURN == "on_before_turn"
        assert ON_AFTER_TURN == "on_after_turn"
        assert ON_SESSION_START == "on_session_start"


class TestAgentLoopHookIntegration:
    @pytest.mark.asyncio
    async def test_hooks_fire_during_process(self, mock_tool_llm, sessions_dir):
        from app.agent_loop import AgentLoop
        from app.context_builder import ContextBuilder
        from app.session import Session, SessionManager
        from app.tools.registry import ToolRegistry

        before_hook = AsyncMock()
        after_hook = AsyncMock()

        runner = HookRunner()
        runner.on(ON_BEFORE_TURN, before_hook)
        runner.on(ON_AFTER_TURN, after_hook)

        session = Session(key="test")
        sm = SessionManager(sessions_dir)

        agent = AgentLoop(
            llm=mock_tool_llm,
            tool_registry=ToolRegistry(),
            context_builder=ContextBuilder(),
            session=session,
            session_manager=sm,
            hook_runner=runner,
        )

        await agent.process("hello")

        before_hook.assert_awaited_once()
        after_hook.assert_awaited_once()

        # Check context contents
        before_ctx = before_hook.call_args[0][0]
        assert before_ctx["iteration"] == 0
        assert before_ctx["session_key"] == "test"

        after_ctx = after_hook.call_args[0][0]
        assert after_ctx["had_tool_calls"] is False
        assert "response" in after_ctx
