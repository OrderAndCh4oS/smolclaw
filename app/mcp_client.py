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
        timeout: float = 30.0,
    ):
        self.token_issuer_url = token_issuer_url
        self.timeout = timeout

    async def execute(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool via the auth proxy.

        Single round-trip: sends tool + params to the proxy, which handles
        approval, JWT minting, and gateway execution. Returns the tool result
        directly — the agent never sees the token.
        """
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
