import json
import os
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.agent_loop import AgentLoop
from app.context_builder import ContextBuilder
from app.goal import GoalStore
from app.session import Session, SessionManager
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry
from app.tools.base import Tool


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo input"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, **kwargs) -> str:
        return f"echo: {kwargs['text']}"


class MemoryLookupTool(Tool):
    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Lookup memory excerpts."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            status="ok",
            content="remembered summary",
            metadata={"accessed_excerpt_ids": ["exc-1", "exc-2", "exc-1"]},
        )


def _make_tool_call(name, arguments):
    return {
        "id": "call_1",
        "name": name,
        "arguments": arguments,
    }


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_process_uses_build_messages_async(self, temp_dir):
        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(return_value={
            "content": "ok",
            "tool_calls": None,
            "has_tool_calls": False,
        })

        registry = ToolRegistry()
        builder = MagicMock()
        builder.build_messages_async = AsyncMock(return_value=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ])
        session = Session(key="async-builder-test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=llm,
            tool_registry=registry,
            context_builder=builder,
            session=session,
            session_manager=sm,
        )
        await loop.process("hello")

        builder.build_messages_async.assert_awaited_once_with(
            history=[],
            user_content="hello",
        )

    @pytest.mark.asyncio
    async def test_process_injects_active_goal_context(self, temp_dir):
        llm = MagicMock()
        captured_messages = []

        async def capture_call(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return {
                "content": "ok",
                "tool_calls": None,
                "has_tool_calls": False,
            }

        llm.get_tool_completion = AsyncMock(side_effect=capture_call)

        registry = ToolRegistry()
        builder = ContextBuilder()
        session = Session(key="goal-context")
        sm = SessionManager(temp_dir)
        goal_store = GoalStore(temp_dir)
        goal_store.start(session.key, "Ship goal loop")

        loop = AgentLoop(
            llm=llm,
            tool_registry=registry,
            context_builder=builder,
            session=session,
            session_manager=sm,
            goal_store=goal_store,
        )
        await loop.process("continue")

        goal_messages = [
            message for message in captured_messages
            if message["role"] == "system" and "Current session goal:" in message["content"]
        ]
        assert len(goal_messages) == 1
        assert "Ship goal loop" in goal_messages[0]["content"]
        assert "Goal turns: 1" in goal_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_process_returns_response(self, mock_tool_llm, temp_dir):
        registry = ToolRegistry()
        builder = ContextBuilder()
        session = Session(key="test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=mock_tool_llm,
            tool_registry=registry,
            context_builder=builder,
            session=session,
            session_manager=sm,
        )
        result = await loop.process("hello")
        assert result == "Mock response"

    @pytest.mark.asyncio
    async def test_process_executes_tool_calls(self, temp_dir):
        llm = MagicMock()
        # First call returns tool_calls, second returns content
        llm.get_tool_completion = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": [_make_tool_call("echo", {"text": "hi"})],
                "has_tool_calls": True,
            },
            {
                "content": "Done echoing",
                "tool_calls": None,
                "has_tool_calls": False,
            },
        ])

        registry = ToolRegistry()
        registry.register(EchoTool())
        builder = ContextBuilder()
        session = Session(key="test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
        )
        result = await loop.process("do echo")
        assert result == "Done echoing"
        assert llm.get_tool_completion.call_count == 2

    @pytest.mark.asyncio
    async def test_process_max_iterations(self, temp_dir):
        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(return_value={
            "content": None,
            "tool_calls": [_make_tool_call("echo", {"text": "loop"})],
            "has_tool_calls": True,
        })

        registry = ToolRegistry()
        registry.register(EchoTool())
        builder = ContextBuilder()
        session = Session(key="test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
            max_iterations=3,
        )
        result = await loop.process("forever")
        assert "max iterations" in result.lower()

    @pytest.mark.asyncio
    async def test_process_saves_session(self, mock_tool_llm, temp_dir):
        registry = ToolRegistry()
        builder = ContextBuilder()
        session = Session(key="save-test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=mock_tool_llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
        )
        await loop.process("hello")
        assert len(session.messages) >= 2  # user + assistant
        assert session.messages[0]["role"] == "user"
        assert session.messages[-1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_process_adds_reflection_prompt(self, temp_dir):
        llm = MagicMock()
        call_messages = []

        async def capture_call(**kwargs):
            call_messages.append(kwargs.get("messages", []))
            if len(call_messages) == 1:
                return {
                    "content": None,
                    "tool_calls": [_make_tool_call("echo", {"text": "x"})],
                    "has_tool_calls": True,
                }
            return {
                "content": "reflected",
                "tool_calls": None,
                "has_tool_calls": False,
            }

        llm.get_tool_completion = AsyncMock(side_effect=capture_call)

        registry = ToolRegistry()
        registry.register(EchoTool())
        builder = ContextBuilder()
        session = Session(key="reflect-test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
        )
        await loop.process("do it")
        # Second call should have tool result + reflection prompt in messages
        second_msgs = call_messages[1]
        roles = [m["role"] for m in second_msgs]
        assert "tool" in roles

    @pytest.mark.asyncio
    async def test_process_surfaces_excerpt_ids_in_tool_messages(self, temp_dir):
        llm = MagicMock()
        call_messages = []

        async def capture_call(**kwargs):
            call_messages.append(kwargs.get("messages", []))
            if len(call_messages) == 1:
                return {
                    "content": None,
                    "tool_calls": [_make_tool_call("memory_search", {"query": "pricing"})],
                    "has_tool_calls": True,
                }
            return {
                "content": "done",
                "tool_calls": None,
                "has_tool_calls": False,
            }

        llm.get_tool_completion = AsyncMock(side_effect=capture_call)

        registry = ToolRegistry()
        registry.register(MemoryLookupTool())
        builder = ContextBuilder()
        session = Session(key="memory-ids-test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=llm,
            tool_registry=registry,
            context_builder=builder,
            session=session,
            session_manager=sm,
        )

        await loop.process("use memory")

        tool_messages = [m for m in call_messages[1] if m["role"] == "tool"]
        assert len(tool_messages) == 1
        assert "remembered summary" in tool_messages[0]["content"]
        assert "Excerpt IDs you can use with memory_get:" in tool_messages[0]["content"]
        assert "- exc-1" in tool_messages[0]["content"]
        assert "- exc-2" in tool_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_consolidate_memory(self, temp_dir):
        mock_rag = MagicMock()
        mock_rag.ingest_text = AsyncMock()

        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(return_value={
            "content": "ok",
            "tool_calls": None,
            "has_tool_calls": False,
        })

        registry = ToolRegistry()
        builder = ContextBuilder()
        session = Session(key="consolidate-test")
        # Add many messages to exceed memory_window
        for i in range(25):
            session.add_message({"role": "user", "content": f"msg {i}"})
            session.add_message({"role": "assistant", "content": f"reply {i}"})
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
            memory_window=20, smol_rag=mock_rag,
        )
        await loop.process("new message")
        mock_rag.ingest_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_consolidate_updates_last_consolidated(self, temp_dir):
        mock_rag = MagicMock()
        mock_rag.ingest_text = AsyncMock()

        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(return_value={
            "content": "ok",
            "tool_calls": None,
            "has_tool_calls": False,
        })

        registry = ToolRegistry()
        builder = ContextBuilder()
        session = Session(key="consol-update-test")
        for i in range(25):
            session.add_message({"role": "user", "content": f"msg {i}"})
            session.add_message({"role": "assistant", "content": f"reply {i}"})
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
            memory_window=20, smol_rag=mock_rag,
        )
        old_consolidated = session.last_consolidated
        await loop.process("trigger consolidation")
        assert session.last_consolidated > old_consolidated

    @pytest.mark.asyncio
    async def test_on_output_called_with_response(self, mock_tool_llm, temp_dir):
        """on_output callback receives the agent's final response text."""
        registry = ToolRegistry()
        builder = ContextBuilder()
        session = Session(key="output-test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=mock_tool_llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
        )

        received = []
        async def capture(content):
            received.append(content)

        await loop.process("hello", on_output=capture)
        assert received == ["Mock response"]

    @pytest.mark.asyncio
    async def test_hooks_fire_before_and_after_turn(self, mock_tool_llm, temp_dir):
        """HookRunner fires ON_BEFORE_TURN and ON_AFTER_TURN with correct context."""
        from app.hooks import HookRunner, ON_BEFORE_TURN, ON_AFTER_TURN

        fired_events = []

        async def capture_hook(context):
            fired_events.append(context)

        hook_runner = HookRunner()
        hook_runner.on(ON_BEFORE_TURN, capture_hook)
        hook_runner.on(ON_AFTER_TURN, capture_hook)

        registry = ToolRegistry()
        builder = ContextBuilder()
        session = Session(key="hooks-test")
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=mock_tool_llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
            hook_runner=hook_runner,
        )
        await loop.process("test hooks")

        assert len(fired_events) == 2
        # First event is ON_BEFORE_TURN
        assert fired_events[0]["iteration"] == 0
        assert fired_events[0]["session_key"] == "hooks-test"
        assert fired_events[0]["user_content"] == "test hooks"
        # Second event is ON_AFTER_TURN
        assert fired_events[1]["iteration"] == 0
        assert fired_events[1]["response"] == "Mock response"
        assert fired_events[1]["had_tool_calls"] is False

    @pytest.mark.asyncio
    async def test_compaction_ingests_into_rag(self, temp_dir):
        """Consolidation ingests text into SmolRAG when session exceeds memory_window."""
        mock_rag = MagicMock()
        mock_rag.ingest_text = AsyncMock()

        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(return_value={
            "content": "ok",
            "tool_calls": None,
            "has_tool_calls": False,
        })

        registry = ToolRegistry()
        builder = ContextBuilder()
        session = Session(key="compact-test")
        for i in range(25):
            session.add_message({"role": "user", "content": f"msg {i}"})
            session.add_message({"role": "assistant", "content": f"reply {i}"})
        sm = SessionManager(temp_dir)

        loop = AgentLoop(
            llm=llm, tool_registry=registry,
            context_builder=builder, session=session, session_manager=sm,
            memory_window=20, smol_rag=mock_rag,
        )
        await loop.process("trigger compaction")

        mock_rag.ingest_text.assert_called_once()
        assert session.last_consolidated > 0

    @pytest.mark.asyncio
    async def test_close_closes_llm_and_owned_resources(self, temp_dir):
        from app.hooks import HookRunner, ON_SESSION_END

        llm = MagicMock()
        llm.close = AsyncMock()
        resource = MagicMock()
        resource.close = AsyncMock()
        fired = []

        async def capture_hook(context):
            fired.append(context["session_key"])

        hook_runner = HookRunner()
        hook_runner.on(ON_SESSION_END, capture_hook)

        loop = AgentLoop(
            llm=llm,
            tool_registry=ToolRegistry(),
            context_builder=ContextBuilder(),
            session=Session(key="close-test"),
            session_manager=SessionManager(temp_dir),
            hook_runner=hook_runner,
        )
        loop.add_owned_resource(resource)

        await loop.close()

        assert fired == ["close-test"]
        llm.close.assert_awaited_once()
        resource.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, temp_dir):
        llm = MagicMock()
        llm.close = AsyncMock()

        loop = AgentLoop(
            llm=llm,
            tool_registry=ToolRegistry(),
            context_builder=ContextBuilder(),
            session=Session(key="idempotent-close-test"),
            session_manager=SessionManager(temp_dir),
        )

        await loop.close()
        await loop.close()

        llm.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_emits_tool_events(self, temp_dir):
        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": [_make_tool_call("echo", {"text": "hi"})],
                "has_tool_calls": True,
            },
            {
                "content": "done",
                "tool_calls": None,
                "has_tool_calls": False,
            },
        ])

        registry = ToolRegistry()
        registry.register(EchoTool())
        loop = AgentLoop(
            llm=llm,
            tool_registry=registry,
            context_builder=ContextBuilder(),
            session=Session(key="tool-events-test"),
            session_manager=SessionManager(temp_dir),
        )

        events = []

        async def capture_event(event):
            events.append(event)

        result = await loop.process("do echo", on_event=capture_event)

        assert result == "done"
        tool_events = [e for e in events if e.get("type") == "tool"]
        llm_events = [e for e in events if e.get("type") == "llm"]
        assert len(tool_events) == 2
        assert tool_events[0]["phase"] == "start"
        assert tool_events[0]["name"] == "echo"
        assert "text=hi" in tool_events[0]["summary"]
        assert tool_events[1]["phase"] == "end"
        assert tool_events[1]["ok"] is True
        assert tool_events[1]["duration_ms"] >= 0
        # LLM events should also be emitted (start + end per iteration)
        assert len(llm_events) >= 2
        assert llm_events[0]["phase"] == "start"
        assert llm_events[1]["phase"] == "end"
        assert "total_tokens" in llm_events[1]
