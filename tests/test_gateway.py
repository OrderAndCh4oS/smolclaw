import asyncio
import json
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.gateway import Gateway
from app.session import SessionManager
from tests.conftest import FakeWebSocket


@pytest.fixture
def gateway():
    return Gateway(
        port=0,
        token_issuer_url="http://localhost:9999/mcp-tokens",
        gateway_url="http://localhost:9999/mcp",
        validate_token=lambda t: t == "valid-token",
    )


@pytest.fixture
def wired_gateway(gateway, mock_smol_rag, temp_dir):
    """Gateway with smol_rag and session manager wired up."""
    gateway._smol_rag = mock_smol_rag
    gateway._session_manager = SessionManager(temp_dir)
    return gateway


def _auth_connect_msg(token="valid-token", req_id="1"):
    return json.dumps({
        "type": "req",
        "id": req_id,
        "method": "connect",
        "params": {"auth": {"token": token}},
    })


def _chat_send_msg(message="Hello", session_key="test", req_id="2"):
    return json.dumps({
        "type": "req",
        "id": req_id,
        "method": "chat.send",
        "params": {"message": message, "sessionKey": session_key},
    })


class TestGatewayProtocol:
    def test_gateway_init(self, gateway):
        assert gateway.token_issuer_url == "http://localhost:9999/mcp-tokens"
        assert gateway.gateway_url == "http://localhost:9999/mcp"

    @pytest.mark.asyncio
    async def test_challenge_response_flow(self, wired_gateway, fake_ws):
        fake_ws._inbox.put_nowait(_auth_connect_msg())
        await wired_gateway._handle_connection(fake_ws)

        assert fake_ws._messages[0]["event"] == "connect.challenge"
        assert "nonce" in fake_ws._messages[0]["payload"]
        assert fake_ws._messages[1]["type"] == "res"
        assert fake_ws._messages[1]["ok"] is True
        assert fake_ws._messages[1]["payload"]["type"] == "hello-ok"

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, wired_gateway, fake_ws):
        fake_ws._inbox.put_nowait(_auth_connect_msg(token="bad-token"))
        await wired_gateway._handle_connection(fake_ws)

        assert fake_ws._messages[1]["ok"] is False
        assert fake_ws._closed is True

    @pytest.mark.asyncio
    async def test_chat_send_emits_lifecycle_events(self, wired_gateway, fake_ws):
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="Hello back!")

        with patch.object(wired_gateway, "_get_or_create_agent", return_value=mock_agent):
            fake_ws._inbox.put_nowait(_auth_connect_msg())
            fake_ws._inbox.put_nowait(_chat_send_msg())
            await wired_gateway._handle_connection(fake_ws)

        lifecycle_events = [m for m in fake_ws._messages if m.get("event") == "agent"]
        assert any(e["payload"]["data"]["phase"] == "start" for e in lifecycle_events)
        assert any(e["payload"]["data"]["phase"] == "end" for e in lifecycle_events)

    @pytest.mark.asyncio
    async def test_chat_abort(self, wired_gateway, fake_ws):
        await wired_gateway._handle_chat_abort(fake_ws, "1", {"runId": "non-existent"})
        assert fake_ws._messages[0]["ok"] is True
        assert fake_ws._messages[0]["payload"]["aborted"] == "non-existent"

    # --- New protocol coverage tests ---

    @pytest.mark.asyncio
    async def test_unknown_method_returns_error(self, wired_gateway, fake_ws):
        fake_ws._inbox.put_nowait(_auth_connect_msg())
        fake_ws._inbox.put_nowait(json.dumps({
            "type": "req",
            "id": "99",
            "method": "foo.bar",
            "params": {},
        }))
        await wired_gateway._handle_connection(fake_ws)

        # Find the response to the unknown method
        error_res = [m for m in fake_ws._messages if m.get("id") == "99"]
        assert len(error_res) == 1
        assert error_res[0]["ok"] is False
        assert "Unknown method: foo.bar" in error_res[0]["payload"]["error"]

    @pytest.mark.asyncio
    async def test_malformed_json_ignored(self, wired_gateway, fake_ws):
        """Connection stays alive after receiving garbage bytes."""
        fake_ws._inbox.put_nowait(_auth_connect_msg())
        fake_ws._inbox.put_nowait("not valid json {{{")
        fake_ws._inbox.put_nowait(json.dumps({
            "type": "req",
            "id": "99",
            "method": "foo.bar",
            "params": {},
        }))
        await wired_gateway._handle_connection(fake_ws)

        # Should still have processed the valid unknown method request
        error_res = [m for m in fake_ws._messages if m.get("id") == "99"]
        assert len(error_res) == 1
        assert error_res[0]["ok"] is False

    @pytest.mark.asyncio
    async def test_auth_timeout(self, wired_gateway, fake_ws):
        """Gateway closes with 1008 if no connect request within timeout."""
        # Patch the timeout to be very short
        with patch("app.gateway.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            await wired_gateway._handle_connection(fake_ws)

        assert fake_ws._closed is True

    @pytest.mark.asyncio
    async def test_chat_send_agent_error_emits_error_phase(self, wired_gateway, fake_ws):
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=RuntimeError("LLM exploded"))

        with patch.object(wired_gateway, "_get_or_create_agent", return_value=mock_agent):
            fake_ws._inbox.put_nowait(_auth_connect_msg())
            fake_ws._inbox.put_nowait(_chat_send_msg())
            await wired_gateway._handle_connection(fake_ws)

        lifecycle_events = [m for m in fake_ws._messages if m.get("event") == "agent"]
        phases = [e["payload"]["data"]["phase"] for e in lifecycle_events]
        assert "start" in phases
        assert "error" in phases

    @pytest.mark.asyncio
    async def test_chat_send_on_output_streams_messages(self, wired_gateway, fake_ws):
        """Mock agent calling on_output twice -> two agent.message events before lifecycle end."""
        async def fake_process(message, on_output=None):
            if on_output:
                await on_output("chunk 1")
                await on_output("chunk 2")
            return "final response"

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=fake_process)

        with patch.object(wired_gateway, "_get_or_create_agent", return_value=mock_agent):
            fake_ws._inbox.put_nowait(_auth_connect_msg())
            fake_ws._inbox.put_nowait(_chat_send_msg())
            await wired_gateway._handle_connection(fake_ws)

        agent_msgs = [m for m in fake_ws._messages if m.get("event") == "agent.message"]
        # on_output called twice + final response = 3 agent.message events
        assert len(agent_msgs) == 3
        assert agent_msgs[0]["payload"]["content"] == "chunk 1"
        assert agent_msgs[1]["payload"]["content"] == "chunk 2"
        assert agent_msgs[2]["payload"]["content"] == "final response"
        assert agent_msgs[2]["payload"]["final"] is True

    @pytest.mark.asyncio
    async def test_chat_abort_stops_active_loop(self, wired_gateway, fake_ws):
        mock_agent = MagicMock()
        mock_agent.request_stop = MagicMock()

        wired_gateway._active_loops["run-123"] = mock_agent
        await wired_gateway._handle_chat_abort(fake_ws, "1", {"runId": "run-123"})

        mock_agent.request_stop.assert_called_once()
        assert fake_ws._messages[0]["ok"] is True

    @pytest.mark.asyncio
    async def test_multiple_chat_sends_sequential(self, wired_gateway, fake_ws):
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=["Reply 1", "Reply 2"])

        with patch.object(wired_gateway, "_get_or_create_agent", return_value=mock_agent):
            fake_ws._inbox.put_nowait(_auth_connect_msg())
            fake_ws._inbox.put_nowait(_chat_send_msg(message="msg1", req_id="2"))
            fake_ws._inbox.put_nowait(_chat_send_msg(message="msg2", req_id="3"))
            await wired_gateway._handle_connection(fake_ws)

        lifecycle_events = [m for m in fake_ws._messages if m.get("event") == "agent"]
        phases = [e["payload"]["data"]["phase"] for e in lifecycle_events]
        assert phases.count("start") == 2
        assert phases.count("end") == 2

    @pytest.mark.asyncio
    async def test_chat_send_includes_run_id(self, wired_gateway, fake_ws):
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="ok")

        with patch.object(wired_gateway, "_get_or_create_agent", return_value=mock_agent):
            fake_ws._inbox.put_nowait(_auth_connect_msg())
            fake_ws._inbox.put_nowait(_chat_send_msg())
            await wired_gateway._handle_connection(fake_ws)

        # Collect all runIds from agent-related events
        run_ids = set()
        for m in fake_ws._messages:
            if m.get("event") in ("agent", "agent.message"):
                rid = m.get("payload", {}).get("runId")
                if rid:
                    run_ids.add(rid)
        # All events should share the same runId
        assert len(run_ids) == 1

    @pytest.mark.asyncio
    async def test_chat_send_includes_session_key(self, wired_gateway, fake_ws):
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="ok")

        with patch.object(wired_gateway, "_get_or_create_agent", return_value=mock_agent):
            fake_ws._inbox.put_nowait(_auth_connect_msg())
            fake_ws._inbox.put_nowait(_chat_send_msg(session_key="my-session"))
            await wired_gateway._handle_connection(fake_ws)

        lifecycle_events = [m for m in fake_ws._messages if m.get("event") == "agent"]
        for e in lifecycle_events:
            assert e["payload"]["sessionKey"] == "my-session"
