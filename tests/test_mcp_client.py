import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.mcp_client import McpClient, McpDeniedException


@pytest.fixture
def mcp_client():
    return McpClient(
        token_issuer_url="http://localhost:9999/mcp-tokens",
        gateway_url="http://localhost:9999/mcp",
    )


class TestMcpClient:
    @pytest.mark.asyncio
    async def test_request_token_success(self, mcp_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"token": "jwt-token-123"}}
        mock_response.raise_for_status = MagicMock()

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            token = await mcp_client.request_token("file-read", {"path": "/tmp/test"})
            assert token == "jwt-token-123"

    @pytest.mark.asyncio
    async def test_request_token_denied(self, mcp_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "error": {"code": -32000, "message": "User denied the request"}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            with pytest.raises(McpDeniedException, match="User denied"):
                await mcp_client.request_token("file-read", {"path": "/tmp/secret"})

    @pytest.mark.asyncio
    async def test_call_tool_success(self, mcp_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "content": [{"type": "text", "text": "file contents here"}]
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            result = await mcp_client.call_tool("file-read", {"path": "/tmp/test"}, "jwt-token")
            assert "content" in result

    @pytest.mark.asyncio
    async def test_call_tool_error(self, mcp_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "error": {"code": -32001, "message": "Tool execution failed"}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            with pytest.raises(McpDeniedException, match="Tool execution failed"):
                await mcp_client.call_tool("file-read", {"path": "/tmp/test"}, "jwt-token")

    @pytest.mark.asyncio
    async def test_execute_full_flow(self, mcp_client):
        """Test the full request_token -> call_tool flow."""
        token_response = MagicMock()
        token_response.json.return_value = {"result": {"token": "jwt-123"}}
        token_response.raise_for_status = MagicMock()

        tool_response = MagicMock()
        tool_response.json.return_value = {
            "result": {"content": [{"type": "text", "text": "output"}]}
        }
        tool_response.raise_for_status = MagicMock()

        with patch("app.mcp_client.httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(side_effect=[token_response, tool_response])
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            result = await mcp_client.execute("file-read", {"path": "/tmp/test"})
            assert "content" in result
