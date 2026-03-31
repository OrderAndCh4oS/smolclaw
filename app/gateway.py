import asyncio
import json
import logging
import os
import secrets
import uuid
from typing import Optional

import websockets

from app.agent_config import AgentConfigLoader
from app.definitions import PROJECT_ROOT, SESSIONS_DIR, MEMORY_DOCS_DIR, WORKSPACE_DIR
from app.hooks import ON_SESSION_END
from app.lifecycle_hooks import ContradictionExpiryHook
from app.runtime import RuntimeEnvironment, build_configured_agent
from app.session import SessionManager
from app.session_export_hook import SessionExportHook
from app.smol_rag import SmolRag, create_smol_rag
from app.utilities import ensure_dir

logger = logging.getLogger("smolclaw.gateway")

DEFAULT_AGENTS_CONFIG = os.path.join(PROJECT_ROOT, "agents.yaml")


class Gateway:
    def __init__(
        self,
        port: int = 18789,
        token_issuer_url: str = "http://client:3000/mcp-tokens",
        gateway_url: str = "http://mcp-gateway:3200/mcp",
        validate_token: Optional[callable] = None,
        agents_config: str = DEFAULT_AGENTS_CONFIG,
    ):
        self.port = port
        self.token_issuer_url = token_issuer_url
        self.gateway_url = gateway_url
        self._validate_token = validate_token or self._default_validate_token
        self.agents_config = agents_config
        self._active_loops: dict[str, "AgentLoop"] = {}
        self._session_agents: dict[str, "AgentLoop"] = {}
        self._smol_rag: Optional[SmolRag] = None
        self._session_manager: Optional[SessionManager] = None

    def _default_validate_token(self, token: str) -> bool:
        return bool(token)

    async def _handle_connection(self, websocket):
        # Step 1: Send challenge
        nonce = secrets.token_hex(16)
        await websocket.send(json.dumps({
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": nonce},
        }))

        # Step 2: Wait for connect request
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=30)
        except asyncio.TimeoutError:
            await websocket.close(1008, "Auth timeout")
            return

        msg = json.loads(raw)
        if msg.get("type") != "req" or msg.get("method") != "connect":
            await websocket.close(1002, "Expected connect request")
            return

        token = msg.get("params", {}).get("auth", {}).get("token", "")
        req_id = msg.get("id")

        if not self._validate_token(token):
            await websocket.send(json.dumps({
                "type": "res",
                "id": req_id,
                "ok": False,
                "payload": {"error": "Invalid token"},
            }))
            await websocket.close(1008, "Auth failed")
            return

        # Step 3: Send hello-ok
        await websocket.send(json.dumps({
            "type": "res",
            "id": req_id,
            "ok": True,
            "payload": {"type": "hello-ok"},
        }))

        # Step 4: Message loop with cleanup on disconnect
        try:
            await self._message_loop(websocket)
        finally:
            for agent in self._session_agents.values():
                try:
                    await agent.close()
                except Exception as e:
                    logger.warning(f"Error closing agent: {e}")
            self._session_agents.clear()

    async def _message_loop(self, websocket):
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") != "req":
                continue

            method = msg.get("method")
            req_id = msg.get("id")
            params = msg.get("params", {})

            if method == "chat.send":
                await self._handle_chat_send(websocket, req_id, params)
            elif method == "chat.abort":
                await self._handle_chat_abort(websocket, req_id, params)
            else:
                await websocket.send(json.dumps({
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "payload": {"error": f"Unknown method: {method}"},
                }))

    async def _handle_chat_send(self, websocket, req_id: str, params: dict):
        message = params.get("message", "")
        session_key = params.get("sessionKey", "default")
        run_id = str(uuid.uuid4())

        # Emit lifecycle start
        await websocket.send(json.dumps({
            "type": "event",
            "event": "agent",
            "payload": {
                "stream": "lifecycle",
                "data": {"phase": "start"},
                "runId": run_id,
                "sessionKey": session_key,
            },
        }))

        # Acknowledge the request
        await websocket.send(json.dumps({
            "type": "res",
            "id": req_id,
            "ok": True,
            "payload": {"runId": run_id},
        }))

        try:
            agent = self._get_or_create_agent(session_key)
            self._active_loops[run_id] = agent

            async def on_output(content: str):
                await websocket.send(json.dumps({
                    "type": "event",
                    "event": "agent.message",
                    "payload": {"content": content, "runId": run_id, "streaming": True},
                }))

            async def on_event(event: dict):
                event_type = event.get("type")
                if event_type in ("llm", "tool"):
                    await websocket.send(json.dumps({
                        "type": "event",
                        "event": "agent.activity",
                        "payload": {**event, "runId": run_id, "sessionKey": session_key},
                    }))

            response = await agent.process(message, on_output=on_output, on_event=on_event)

            # Send final response
            await websocket.send(json.dumps({
                "type": "event",
                "event": "agent.message",
                "payload": {"content": response, "runId": run_id, "final": True},
            }))

            # Emit lifecycle end with usage
            usage_summary = None
            from app.usage import SessionUsage
            if isinstance(getattr(agent, "session_usage", None), SessionUsage):
                usage_summary = agent.session_usage.summary_dict()
            await websocket.send(json.dumps({
                "type": "event",
                "event": "agent",
                "payload": {
                    "stream": "lifecycle",
                    "data": {"phase": "end", "usage": usage_summary},
                    "runId": run_id,
                    "sessionKey": session_key,
                },
            }))
        except Exception as e:
            logger.exception("Agent error")
            await websocket.send(json.dumps({
                "type": "event",
                "event": "agent",
                "payload": {
                    "stream": "lifecycle",
                    "data": {"phase": "error", "message": str(e)},
                    "runId": run_id,
                    "sessionKey": session_key,
                },
            }))
        finally:
            self._active_loops.pop(run_id, None)

    async def _handle_chat_abort(self, websocket, req_id: str, params: dict):
        run_id = params.get("runId", "")
        agent = self._active_loops.get(run_id)
        if agent:
            agent.request_stop()
        await websocket.send(json.dumps({
            "type": "res",
            "id": req_id,
            "ok": True,
            "payload": {"aborted": run_id},
        }))

    def _get_or_create_agent(self, session_key: str):
        if session_key in self._session_agents:
            return self._session_agents[session_key]

        configs = AgentConfigLoader.load(self.agents_config)
        config = configs["default"]

        memory_dir = ensure_dir(MEMORY_DOCS_DIR)

        def register_session_end_hooks(loop):
            from app.usage import UsagePersistHook

            loop.hook_runner.on(ON_SESSION_END, UsagePersistHook(SESSIONS_DIR))
            rag = getattr(loop, "smol_rag", None)
            if rag is None:
                return

            loop.hook_runner.on(ON_SESSION_END, SessionExportHook(
                smol_rag=rag,
                llm=loop.llm,
                memory_dir=memory_dir,
            ))
            if getattr(rag, "contradiction_detector", None):
                loop.hook_runner.on(
                    ON_SESSION_END,
                    ContradictionExpiryHook(rag.contradiction_detector),
                )

        env = RuntimeEnvironment(
            smol_rag=self._smol_rag,
            session_manager=self._session_manager,
            memory_docs_dir=MEMORY_DOCS_DIR,
            workspace=WORKSPACE_DIR,
            transport="mcp",
            token_issuer_url=self.token_issuer_url,
            gateway_url=self.gateway_url,
            agent_configs=configs,
        )
        agent = build_configured_agent(
            config=config,
            env=env,
            session_key=session_key,
            child_loop_registrar=register_session_end_hooks,
        )
        register_session_end_hooks(agent)
        self._session_agents[session_key] = agent
        return agent

    async def start(self):
        from app.tracing import init_tracing
        init_tracing()
        ensure_dir(SESSIONS_DIR)
        self._smol_rag = create_smol_rag()
        self._session_manager = SessionManager(SESSIONS_DIR)
        logger.info(f"SmolClaw gateway starting on port {self.port}")
        async with websockets.serve(self._handle_connection, "0.0.0.0", self.port):
            await asyncio.Future()  # Run forever
