import asyncio
import json
import os

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent_config import AgentConfig
from app.definitions import build_workspace_paths
from app.gateway import Gateway
from app.hooks import ON_SESSION_END, HookRunner
from app.session import SessionManager


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


def _install_session_agent(gateway: Gateway, agent, session_key: str = "test"):
    agent.close = AsyncMock()
    gateway._session_agents[session_key] = agent


class TestGatewayProtocol:
    def test_gateway_init(self, gateway):
        assert gateway.token_issuer_url == "http://localhost:9999/mcp-tokens"
        assert gateway.gateway_url == "http://localhost:9999/mcp"

    def test_default_validator_requires_configured_token(self):
        gateway = Gateway(port=0)

        with pytest.raises(RuntimeError, match="Gateway token is required"):
            gateway._validate_startup_security()

    def test_default_validator_uses_shared_token(self):
        gateway = Gateway(port=0, auth_token="secret")

        assert gateway._default_validate_token("secret") is True
        assert gateway._default_validate_token("wrong") is False

    def test_remote_bind_requires_explicit_opt_in(self):
        gateway = Gateway(port=0, host="0.0.0.0", auth_token="secret")

        with pytest.raises(RuntimeError, match="--allow-remote"):
            gateway._validate_startup_security()

    def test_remote_bind_can_be_explicitly_allowed(self):
        gateway = Gateway(port=0, host="0.0.0.0", auth_token="secret", allow_remote=True)

        gateway._validate_startup_security()

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
        _install_session_agent(wired_gateway, mock_agent)

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
        fake_ws.recv = AsyncMock(side_effect=asyncio.TimeoutError)
        await wired_gateway._handle_connection(fake_ws)

        assert fake_ws._closed is True

    @pytest.mark.asyncio
    async def test_chat_send_agent_error_emits_error_phase(self, wired_gateway, fake_ws):
        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=RuntimeError("LLM exploded"))
        _install_session_agent(wired_gateway, mock_agent)

        fake_ws._inbox.put_nowait(_auth_connect_msg())
        fake_ws._inbox.put_nowait(_chat_send_msg())
        await wired_gateway._handle_connection(fake_ws)

        lifecycle_events = [m for m in fake_ws._messages if m.get("event") == "agent"]
        phases = [e["payload"]["data"]["phase"] for e in lifecycle_events]
        assert "start" in phases
        assert "error" in phases
        error_event = next(e for e in lifecycle_events if e["payload"]["data"]["phase"] == "error")
        assert error_event["payload"]["data"]["incidentId"].startswith("inc-")
        assert "Error: incident inc-" in error_event["payload"]["data"]["message"]

    @pytest.mark.asyncio
    async def test_chat_send_on_output_streams_messages(self, wired_gateway, fake_ws):
        """Mock agent calling on_output twice -> two agent.message events before lifecycle end."""
        async def fake_process(message, on_output=None, on_event=None):
            if on_output:
                await on_output("chunk 1")
                await on_output("chunk 2")
            return "final response"

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=fake_process)
        _install_session_agent(wired_gateway, mock_agent)

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
        _install_session_agent(wired_gateway, mock_agent)

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
        _install_session_agent(wired_gateway, mock_agent)

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
        _install_session_agent(wired_gateway, mock_agent, session_key="my-session")

        fake_ws._inbox.put_nowait(_auth_connect_msg())
        fake_ws._inbox.put_nowait(_chat_send_msg(session_key="my-session"))
        await wired_gateway._handle_connection(fake_ws)

        lifecycle_events = [m for m in fake_ws._messages if m.get("event") == "agent"]
        for e in lifecycle_events:
            assert e["payload"]["sessionKey"] == "my-session"

    def test_get_or_create_agent_skips_export_hooks_for_memoryless_agent(self, wired_gateway):
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.smol_rag = None

        config = AgentConfig(
            name="default",
            model="gpt-test",
            persona="You are Default.",
            tools=["read_file"],
            capabilities=["filesystem"],
        )

        wired_gateway.config_loader = lambda _path: {"default": config}
        wired_gateway.agent_builder = lambda **_kwargs: fake_agent

        agent = wired_gateway._get_or_create_agent("memoryless-session")

        assert agent is fake_agent
        assert ON_SESSION_END in fake_agent.hook_runner.events
        assert len(fake_agent.hook_runner._hooks[ON_SESSION_END]) == 1

    def test_get_or_create_agent_enables_subagents_in_runtime_env(self, wired_gateway):
        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.smol_rag = None

        config = AgentConfig(
            name="default",
            model="gpt-test",
            persona="You are Default.",
            tools=["spawn_agent"],
        )

        build_calls = []

        def agent_builder(**kwargs):
            build_calls.append(kwargs)
            return fake_agent

        wired_gateway.config_loader = lambda _path: {"default": config}
        wired_gateway.agent_builder = agent_builder
        wired_gateway._get_or_create_agent("subagent-session")

        assert build_calls[0]["env"].enable_subagents is True

    def test_get_or_create_agent_uses_workspace_scoped_runtime_env(self, mock_smol_rag, temp_dir):
        workspace_root = os.path.join(temp_dir, "topic-a")
        gateway = Gateway(
            port=0,
            token_issuer_url="http://localhost:9999/mcp-tokens",
            gateway_url="http://localhost:9999/mcp",
            validate_token=lambda t: t == "valid-token",
            workspace=workspace_root,
        )
        gateway._smol_rag = mock_smol_rag
        gateway._session_manager = SessionManager(temp_dir)

        fake_agent = MagicMock()
        fake_agent.llm = MagicMock()
        fake_agent.hook_runner = HookRunner()
        fake_agent.smol_rag = None
        config = AgentConfig(
            name="default",
            model="gpt-test",
            persona="You are Default.",
            tools=["read_file"],
        )

        build_calls = []

        def agent_builder(**kwargs):
            build_calls.append(kwargs)
            return fake_agent

        gateway.config_loader = lambda _path: {"default": config}
        gateway.agent_builder = agent_builder
        gateway._get_or_create_agent("workspace-session")

        expected = build_workspace_paths(workspace_root)
        env = build_calls[0]["env"]
        assert env.memory_docs_dir == expected.memory_docs_dir
        assert env.workspace.root_dir == os.path.realpath(expected.root_dir)
        assert env.llm_db_path == expected.sqlite_db_path
