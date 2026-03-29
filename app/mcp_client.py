import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger("smolclaw.mcp_client")


class McpDeniedException(Exception):
    """Raised when the MCP gateway denies a tool call."""
    pass


class McpClient:
    """Client for the JWT auth proxy.

    Uses the proxy-execution model: sends a tool request to the token issuer,
    which handles approval, token minting, and gateway execution internally.
    The agent never sees the JWT token.
    """

    def __init__(
        self,
        token_issuer_url: str,
        gateway_url: str | None = None,
        timeout: float = 30.0,
    ):
        self.token_issuer_url = token_issuer_url
        self.gateway_url = gateway_url
        self.timeout = timeout

    async def request_token(self, tool: str, params: Dict[str, Any]) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "request_token",
            "params": {"tool": tool, "arguments": params},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

        token = result.get("result", {}).get("token")
        if not token:
            raise McpDeniedException("Tool execution denied")
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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
        """Execute a tool via the auth proxy or the token+gateway compatibility flow."""
        if self.gateway_url:
            token = await self.request_token(tool, params)
            return await self.call_tool(tool, params, token)

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "request_token",
            "params": {"tool": tool, "arguments": params},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
