"""End-to-end tests: message -> gateway -> agent loop -> tool -> response.

All LLM calls and tools are mocked — no container or credentials required.
Equivalent to OpenClaw's gateway.test.ts mock-tool-call flow.
"""
import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.gateway import Gateway
from app.session import SessionManager
from tests.conftest import FakeWebSocket


def _auth_msg(token="valid-token"):
    return json.dumps({
        "type": "req",
        "id": "1",
        "method": "connect",
        "params": {"auth": {"token": token}},
    })


def _chat_msg(message, session_key="test-session", req_id="2"):
    return json.dumps({
        "type": "req",
        "id": req_id,
        "method": "chat.send",
        "params": {"message": message, "sessionKey": session_key},
    })


def _make_tool_call(name, arguments, call_id="call_1"):
    return {
        "id": call_id,
        "name": name,
        "arguments": arguments,
    }


@pytest.fixture
def mock_tool_registry():
    """A registry that resolves any tool execute to a canned string."""
    registry = MagicMock()
    registry.get_definitions = MagicMock(return_value=[
        {"type": "function", "function": {"name": "echo", "parameters": {}}},
    ])
    registry.execute = AsyncMock(return_value="tool-output-123")
    return registry


@pytest.fixture
def flow_gateway(mock_smol_rag, temp_dir):
    """A real Gateway with mocked internals for flow testing."""
    gw = Gateway(
        port=0,
        token_issuer_url="http://localhost:9999/mcp-tokens",
        gateway_url="http://localhost:9999/mcp",
        validate_token=lambda t: t == "valid-token",
    )
    gw._smol_rag = mock_smol_rag
    gw._session_manager = SessionManager(temp_dir)
    return gw


async def _run_chat(gw, ws, message, session_key="test-session", req_id="2"):
    """Queue auth + chat.send and run the connection."""
    ws._inbox.put_nowait(_auth_msg())
    ws._inbox.put_nowait(_chat_msg(message, session_key=session_key, req_id=req_id))
    await gw._handle_connection(ws)
    return ws._messages


def _get_lifecycle_phases(messages):
    return [
        m["payload"]["data"]["phase"]
        for m in messages
        if m.get("event") == "agent"
    ]


def _get_agent_texts(messages):
    return [
        m["payload"]["content"]
        for m in messages
        if m.get("event") == "agent.message"
    ]


class TestGatewayAgentFlow:
    @pytest.mark.asyncio
    async def test_gateway_chat_invokes_agent_with_correct_message(self, flow_gateway):
        """chat.send('hello') -> agent.process called with 'hello'."""
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="Hi there!")

        ws = FakeWebSocket()
        with patch.object(flow_gateway, "_get_or_create_agent", return_value=mock_agent):
            await _run_chat(flow_gateway, ws, "hello")

        mock_agent.process.assert_called_once()
        call_args = mock_agent.process.call_args
        assert call_args[0][0] == "hello"

    @pytest.mark.asyncio
    async def test_gateway_chat_tool_call_round_trip(self, flow_gateway, mock_tool_registry):
        """LLM returns tool_call -> tool executes -> LLM returns text -> lifecycle end."""
        call_count = 0

        async def mock_tool_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "content": None,
                    "tool_calls": [_make_tool_call("echo", {"text": "hi"})],
                    "has_tool_calls": True,
                }
            return {
                "content": "Done: tool-output-123",
                "tool_calls": None,
                "has_tool_calls": False,
            }

        mock_llm = MagicMock()
        mock_llm.get_tool_completion = AsyncMock(side_effect=mock_tool_completion)

        # Patch _get_or_create_agent to return a real AgentLoop with mocked LLM
        from app.agent_loop import AgentLoop
        from app.context_builder import ContextBuilder
        from app.session import Session

        def make_agent(session_key):
            session = flow_gateway._session_manager.get_or_create(session_key)
            return AgentLoop(
                llm=mock_llm,
                tool_registry=mock_tool_registry,
                context_builder=ContextBuilder(),
                session=session,
                session_manager=flow_gateway._session_manager,
            )

        ws = FakeWebSocket()
        with patch.object(flow_gateway, "_get_or_create_agent", side_effect=make_agent):
            msgs = await _run_chat(flow_gateway, ws, "do echo")

        phases = _get_lifecycle_phases(msgs)
        assert "start" in phases
        assert "end" in phases
        mock_tool_registry.execute.assert_called_once_with("echo", {"text": "hi"})
        texts = _get_agent_texts(msgs)
        assert any("tool-output-123" in t for t in texts)

    @pytest.mark.asyncio
    async def test_gateway_chat_memory_search_round_trip(self, flow_gateway, mock_smol_rag):
        """LLM calls memory_search -> SmolRAG returns results -> LLM summarizes."""
        from app.agent_loop import AgentLoop
        from app.context_builder import ContextBuilder
        from app.tools.registry import ToolRegistry
        from app.tools.memory_tools import MemorySearchTool

        call_count = 0

        async def mock_tool_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "content": None,
                    "tool_calls": [_make_tool_call("memory_search", {"query": "test"})],
                    "has_tool_calls": True,
                }
            return {
                "content": "Found: Mock query result",
                "tool_calls": None,
                "has_tool_calls": False,
            }

        mock_llm = MagicMock()
        mock_llm.get_tool_completion = AsyncMock(side_effect=mock_tool_completion)

        registry = ToolRegistry()
        registry.register(MemorySearchTool(mock_smol_rag))

        def make_agent(session_key):
            session = flow_gateway._session_manager.get_or_create(session_key)
            return AgentLoop(
                llm=mock_llm,
                tool_registry=registry,
                context_builder=ContextBuilder(),
                session=session,
                session_manager=flow_gateway._session_manager,
            )

        ws = FakeWebSocket()
        with patch.object(flow_gateway, "_get_or_create_agent", side_effect=make_agent):
            msgs = await _run_chat(flow_gateway, ws, "search memory for test")

        phases = _get_lifecycle_phases(msgs)
        assert "start" in phases
        assert "end" in phases
        mock_smol_rag.mix_query.assert_called_once()
        texts = _get_agent_texts(msgs)
        assert any("Mock query result" in t for t in texts)

    @pytest.mark.asyncio
    async def test_gateway_session_persists_across_chats(self, flow_gateway):
        """Two chat.sends on the same sessionKey -> second call's context includes first conversation."""
        from app.agent_loop import AgentLoop
        from app.context_builder import ContextBuilder
        from app.tools.registry import ToolRegistry

        captured_messages = []

        async def mock_tool_completion(**kwargs):
            captured_messages.append(kwargs.get("messages", []))
            return {
                "content": "ok",
                "tool_calls": None,
                "has_tool_calls": False,
            }

        mock_llm = MagicMock()
        mock_llm.get_tool_completion = AsyncMock(side_effect=mock_tool_completion)

        def make_agent(session_key):
            session = flow_gateway._session_manager.get_or_create(session_key)
            return AgentLoop(
                llm=mock_llm,
                tool_registry=ToolRegistry(),
                context_builder=ContextBuilder(),
                session=session,
                session_manager=flow_gateway._session_manager,
            )

        # First chat
        ws1 = FakeWebSocket()
        with patch.object(flow_gateway, "_get_or_create_agent", side_effect=make_agent):
            await _run_chat(flow_gateway, ws1, "first message", session_key="persist-key")

        # Second chat — same session
        ws2 = FakeWebSocket()
        with patch.object(flow_gateway, "_get_or_create_agent", side_effect=make_agent):
            await _run_chat(flow_gateway, ws2, "second message", session_key="persist-key")

        # The second LLM call should include history from the first conversation
        second_call_msgs = captured_messages[1]
        contents = [m.get("content", "") for m in second_call_msgs]
        assert any("first message" in c for c in contents)

    @pytest.mark.asyncio
    async def test_gateway_different_sessions_isolated(self, flow_gateway):
        """chat.send on session-a then session-b -> session-b doesn't see session-a history."""
        from app.agent_loop import AgentLoop
        from app.context_builder import ContextBuilder
        from app.tools.registry import ToolRegistry

        captured_messages = []

        async def mock_tool_completion(**kwargs):
            captured_messages.append(kwargs.get("messages", []))
            return {
                "content": "ok",
                "tool_calls": None,
                "has_tool_calls": False,
            }

        mock_llm = MagicMock()
        mock_llm.get_tool_completion = AsyncMock(side_effect=mock_tool_completion)

        def make_agent(session_key):
            session = flow_gateway._session_manager.get_or_create(session_key)
            return AgentLoop(
                llm=mock_llm,
                tool_registry=ToolRegistry(),
                context_builder=ContextBuilder(),
                session=session,
                session_manager=flow_gateway._session_manager,
            )

        # Chat on session-a
        ws1 = FakeWebSocket()
        with patch.object(flow_gateway, "_get_or_create_agent", side_effect=make_agent):
            await _run_chat(flow_gateway, ws1, "secret from session-a", session_key="session-a")

        # Chat on session-b
        ws2 = FakeWebSocket()
        with patch.object(flow_gateway, "_get_or_create_agent", side_effect=make_agent):
            await _run_chat(flow_gateway, ws2, "hello session-b", session_key="session-b")

        # Session-b's LLM call should NOT include session-a's content
        session_b_msgs = captured_messages[1]
        contents = " ".join(m.get("content", "") or "" for m in session_b_msgs)
        assert "secret from session-a" not in contents

    @pytest.mark.asyncio
    async def test_gateway_max_iterations_stops_loop(self, flow_gateway):
        """LLM always returns tool calls -> agent stops at MAX_ITERATIONS -> error phase."""
        from app.agent_loop import AgentLoop
        from app.context_builder import ContextBuilder
        from app.tools.registry import ToolRegistry
        from app.tools.base import Tool

        class AlwaysTool(Tool):
            @property
            def name(self): return "always"

            @property
            def description(self): return "Always tool"

            @property
            def parameters(self):
                return {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}

            async def execute(self, **kwargs): return "done"

        mock_llm = MagicMock()
        mock_llm.get_tool_completion = AsyncMock(return_value={
            "content": None,
            "tool_calls": [_make_tool_call("always", {"x": "loop"})],
            "has_tool_calls": True,
        })

        registry = ToolRegistry()
        registry.register(AlwaysTool())

        def make_agent(session_key):
            session = flow_gateway._session_manager.get_or_create(session_key)
            return AgentLoop(
                llm=mock_llm,
                tool_registry=registry,
                context_builder=ContextBuilder(),
                session=session,
                session_manager=flow_gateway._session_manager,
                max_iterations=3,
            )

        ws = FakeWebSocket()
        with patch.object(flow_gateway, "_get_or_create_agent", side_effect=make_agent):
            msgs = await _run_chat(flow_gateway, ws, "forever loop")

        phases = _get_lifecycle_phases(msgs)
        assert "start" in phases
        assert "end" in phases
        texts = _get_agent_texts(msgs)
        assert any("max iterations" in t.lower() for t in texts)
