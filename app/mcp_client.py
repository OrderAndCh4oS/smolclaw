import logging
from collections.abc import Callable
from typing import Any, Dict

import httpx

logger = logging.getLogger("smolclaw.mcp_client")


class McpDeniedException(Exception):
    """Raised when the MCP gateway denies a tool call."""
    pass


class McpClient:
    """Client for MCP auth issuers.

    Supports both legacy one-hop proxy execution and token+gateway flows.
    """

    def __init__(
        self,
        token_issuer_url: str,
        gateway_url: str | None = None,
        timeout: float = 30.0,
        http_client_factory: Callable[..., object] | None = None,
    ):
        self.token_issuer_url = token_issuer_url
        self.gateway_url = gateway_url
        self.timeout = timeout
        self.http_client_factory = http_client_factory or httpx.AsyncClient

    async def _request_execution(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "request_token",
            "params": {"tool": tool, "arguments": params},
        }
        async with self.http_client_factory(timeout=self.timeout) as client:
            response = await client.post(
                self.token_issuer_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()

        if "error" in result:
            error_msg = result["error"].get("message", "Tool execution denied")
            raise McpDeniedException(error_msg)

        return result.get("result", {})

    async def request_token(self, tool: str, params: Dict[str, Any]) -> str:
        result = await self._request_execution(tool, params)
        token = result.get("token")
        if not token:
            raise RuntimeError(
                "Token issuer returned a direct tool result instead of a token."
            )
        return token

    async def call_tool(self, tool: str, params: Dict[str, Any], token: str) -> Dict[str, Any]:
        if not self.gateway_url:
            raise RuntimeError("gateway_url is required to call MCP tools")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": params},
        }
        async with self.http_client_factory(timeout=self.timeout) as client:
            response = await client.post(
                self.gateway_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            response.raise_for_status()
            result = response.json()

        if "error" in result:
            error_msg = result["error"].get("message", "Tool execution denied")
            raise McpDeniedException(error_msg)

        return result.get("result", {})

    async def execute(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool via the issuer, optionally following with a gateway call."""
        result = await self._request_execution(tool, params)
        token = result.get("token")
        if token:
            return await self.call_tool(tool, params, token)
        return result
