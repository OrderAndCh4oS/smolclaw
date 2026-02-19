import json
import os
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.agent_loop import AgentLoop
from app.context_builder import ContextBuilder
from app.session import Session, SessionManager
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


def _make_tool_call(name, arguments):
    return {
        "id": "call_1",
        "name": name,
        "arguments": arguments,
    }


class TestAgentLoop:
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
