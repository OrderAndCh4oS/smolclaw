import asyncio
import json
import logging
import os
import secrets
import uuid
from typing import Optional

import websockets

from app.agent_loop import AgentLoop
from app.context_builder import ContextBuilder
from app.definitions import SESSIONS_DIR, MEMORY_DOCS_DIR, WORKSPACE_DIR, AGENT_MODEL, MAX_ITERATIONS, MEMORY_WINDOW
from app.llm import create_llm
from app.session import SessionManager
from app.smol_rag import SmolRag
from app.tools.memory_tools import MemorySearchTool, MemoryGraphQueryTool, MemoryStoreTool, MemoryRelateTool
from app.tools.registry import ToolRegistry
from app.utilities import ensure_dir

logger = logging.getLogger("smolclaw.gateway")

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
BOOTSTRAP_PATH = os.path.join(PROJECT_ROOT, "AGENT.md")


class Gateway:
    def __init__(
        self,
        port: int = 18789,
        token_issuer_url: str = "http://client:3000/mcp-tokens",
        gateway_url: str = "http://mcp-gateway:3200/mcp",
        validate_token: Optional[callable] = None,
    ):
        self.port = port
        self.token_issuer_url = token_issuer_url
        self.gateway_url = gateway_url
        self._validate_token = validate_token or self._default_validate_token
        self._active_loops: dict[str, AgentLoop] = {}
        self._smol_rag: Optional[SmolRag] = None
        self._session_manager: Optional[SessionManager] = None

    def _default_validate_token(self, token: str) -> bool:
        return bool(token)

    def _build_tool_registry(self, workspace: str) -> ToolRegistry:
        from app.tools.mcp_tools import (
            McpFileReadTool, McpFileWriteTool, McpShellExecTool,
            McpHttpFetchTool, McpWebSearchTool,
        )
        registry = ToolRegistry()
        registry.register(McpFileReadTool(self.token_issuer_url, self.gateway_url))
        registry.register(McpFileWriteTool(self.token_issuer_url, self.gateway_url))
        registry.register(McpShellExecTool(self.token_issuer_url, self.gateway_url))
        registry.register(McpHttpFetchTool(self.token_issuer_url, self.gateway_url))
        registry.register(McpWebSearchTool(self.token_issuer_url, self.gateway_url))
        registry.register(MemorySearchTool(self._smol_rag))
        registry.register(MemoryGraphQueryTool(self._smol_rag))
        registry.register(MemoryStoreTool(self._smol_rag, ensure_dir(MEMORY_DOCS_DIR)))
        registry.register(MemoryRelateTool(self._smol_rag))
        return registry

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

        # Step 4: Message loop
        await self._message_loop(websocket)

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
                    "payload": {"content": content, "runId": run_id},
                }))

            response = await agent.process(message, on_output=on_output)

            # Send final response
            await websocket.send(json.dumps({
                "type": "event",
                "event": "agent.message",
                "payload": {"content": response, "runId": run_id, "final": True},
            }))

            # Emit lifecycle end
            await websocket.send(json.dumps({
                "type": "event",
                "event": "agent",
                "payload": {
                    "stream": "lifecycle",
                    "data": {"phase": "end"},
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

    def _get_or_create_agent(self, session_key: str) -> AgentLoop:
        llm = create_llm(completion_model=AGENT_MODEL)
        registry = self._build_tool_registry(WORKSPACE_DIR)
        context_builder = ContextBuilder(shared_bootstrap_path=BOOTSTRAP_PATH)
        session = self._session_manager.get_or_create(session_key)
        return AgentLoop(
            llm=llm,
            tool_registry=registry,
            context_builder=context_builder,
            session=session,
            session_manager=self._session_manager,
            max_iterations=MAX_ITERATIONS,
            memory_window=MEMORY_WINDOW,
            smol_rag=self._smol_rag,
        )

    async def start(self):
        ensure_dir(SESSIONS_DIR)
        self._smol_rag = SmolRag()
        self._session_manager = SessionManager(SESSIONS_DIR)
        logger.info(f"SmolClaw gateway starting on port {self.port}")
        async with websockets.serve(self._handle_connection, "0.0.0.0", self.port):
            await asyncio.Future()  # Run forever
