import json
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("smolclaw.mcp_client")


class McpDeniedException(Exception):
    """Raised when the MCP gateway denies a tool call."""
    pass


class McpClient:
    def __init__(
        self,
        token_issuer_url: str,
        gateway_url: str,
        timeout: float = 30.0,
    ):
        self.token_issuer_url = token_issuer_url
        self.gateway_url = gateway_url
        self.timeout = timeout

    async def request_token(self, tool: str, params: Dict[str, Any]) -> str:
        """Request a JWT from the token issuer for the given tool call."""
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
            error_msg = result["error"].get("message", "Token request denied")
            raise McpDeniedException(error_msg)

        token = result.get("result", {}).get("token")
        if not token:
            raise McpDeniedException("No token in response")
        return token

    async def call_tool(
        self,
        tool: str,
        params: Dict[str, Any],
        token: str,
    ) -> Dict[str, Any]:
        """Call a tool via the MCP gateway using the provided JWT."""
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
            error_msg = result["error"].get("message", "Tool call failed")
            raise McpDeniedException(error_msg)

        return result.get("result", {})

    async def execute(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Full flow: request token, then call tool."""
        token = await self.request_token(tool, params)
        return await self.call_tool(tool, params, token)
