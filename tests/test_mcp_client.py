import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.mcp_client import McpClient, McpDeniedException


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = responses
        self._index = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False

    async def post(self, *args, **kwargs):
        response = self._responses[self._index]
        self._index += 1
        return response


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.raise_for_status = MagicMock()

    def json(self):
        return self._payload


@pytest.fixture
def mcp_client():
    return McpClient(
        token_issuer_url="http://localhost:9999/mcp-tokens",
        gateway_url="http://localhost:9999/mcp",
    )


class TestMcpClient:
    @pytest.mark.asyncio
    async def test_request_token_success(self, mcp_client):
        mock_response = _FakeResponse({"result": {"token": "jwt-token-123"}})

        with patch("app.mcp_client.httpx.AsyncClient", return_value=_FakeAsyncClient([mock_response])):

            token = await mcp_client.request_token("file-read", {"path": "/tmp/test"})
            assert token == "jwt-token-123"

    @pytest.mark.asyncio
    async def test_request_token_denied(self, mcp_client):
        mock_response = _FakeResponse({
            "error": {"code": -32000, "message": "User denied the request"}
        })

        with patch("app.mcp_client.httpx.AsyncClient", return_value=_FakeAsyncClient([mock_response])):

            with pytest.raises(McpDeniedException, match="User denied"):
                await mcp_client.request_token("file-read", {"path": "/tmp/secret"})

    @pytest.mark.asyncio
    async def test_call_tool_success(self, mcp_client):
        mock_response = _FakeResponse({
            "result": {
                "content": [{"type": "text", "text": "file contents here"}]
            }
        })

        with patch("app.mcp_client.httpx.AsyncClient", return_value=_FakeAsyncClient([mock_response])):

            result = await mcp_client.call_tool("file-read", {"path": "/tmp/test"}, "jwt-token")
            assert "content" in result

    @pytest.mark.asyncio
    async def test_call_tool_error(self, mcp_client):
        mock_response = _FakeResponse({
            "error": {"code": -32001, "message": "Tool execution failed"}
        })

        with patch("app.mcp_client.httpx.AsyncClient", return_value=_FakeAsyncClient([mock_response])):

            with pytest.raises(McpDeniedException, match="Tool execution failed"):
                await mcp_client.call_tool("file-read", {"path": "/tmp/test"}, "jwt-token")

    @pytest.mark.asyncio
    async def test_execute_full_flow(self, mcp_client):
        """Test the full request_token -> call_tool flow."""
        token_response = _FakeResponse({"result": {"token": "jwt-123"}})
        tool_response = _FakeResponse({
            "result": {"content": [{"type": "text", "text": "output"}]}
        })

        with patch("app.mcp_client.httpx.AsyncClient", return_value=_FakeAsyncClient([token_response, tool_response])):

            result = await mcp_client.execute("file-read", {"path": "/tmp/test"})
            assert "content" in result
