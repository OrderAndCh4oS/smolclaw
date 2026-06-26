import pytest
from unittest.mock import AsyncMock, MagicMock

from app.tools.mcp_tools import (
    McpFileReadTool, McpFileWriteTool, McpShellExecTool,
    McpHttpFetchTool, McpWebSearchTool,
)


@pytest.fixture
def mock_mcp_execute():
    mock_instance = MagicMock()
    mock_instance.execute = AsyncMock(return_value={
        "content": [{"type": "text", "text": "mock result"}]
    })
    return mock_instance


class TestMcpFileReadTool:
    @pytest.mark.asyncio
    async def test_execute(self, mock_mcp_execute):
        tool = McpFileReadTool("http://issuer", "http://gw", client=mock_mcp_execute)
        result = await tool.execute(path="/tmp/test.txt")
        assert "mock result" in result
        mock_mcp_execute.execute.assert_awaited_once_with("file-read", {"path": "/tmp/test.txt"})

    def test_schema(self):
        tool = McpFileReadTool("http://issuer", "http://gw")
        assert tool.name == "read_file"
        assert "path" in tool.parameters["properties"]


class TestMcpFileWriteTool:
    @pytest.mark.asyncio
    async def test_execute(self, mock_mcp_execute):
        tool = McpFileWriteTool("http://issuer", "http://gw", client=mock_mcp_execute)
        result = await tool.execute(path="/tmp/out.txt", content="hello")
        assert "mock result" in result
        mock_mcp_execute.execute.assert_awaited_once_with(
            "file-write", {"path": "/tmp/out.txt", "content": "hello"}
        )


class TestMcpShellExecTool:
    @pytest.mark.asyncio
    async def test_execute(self, mock_mcp_execute):
        tool = McpShellExecTool("http://issuer", "http://gw", client=mock_mcp_execute)
        result = await tool.execute(command="ls -la")
        assert "mock result" in result
        mock_mcp_execute.execute.assert_awaited_once_with("shell-exec", {"command": "ls -la"})

    def test_schema(self):
        tool = McpShellExecTool("http://issuer", "http://gw")
        assert tool.name == "exec"


class TestMcpHttpFetchTool:
    @pytest.mark.asyncio
    async def test_execute(self, mock_mcp_execute):
        tool = McpHttpFetchTool("http://issuer", "http://gw", client=mock_mcp_execute)
        result = await tool.execute(url="https://example.com")
        assert "mock result" in result
        mock_mcp_execute.execute.assert_awaited_once_with(
            "http-fetch", {"url": "https://example.com"}
        )


class TestMcpWebSearchTool:
    @pytest.mark.asyncio
    async def test_execute(self, mock_mcp_execute):
        tool = McpWebSearchTool("http://issuer", "http://gw", client=mock_mcp_execute)
        result = await tool.execute(query="python asyncio")
        assert "mock result" in result
        mock_mcp_execute.execute.assert_awaited_once_with(
            "web-search", {"query": "python asyncio"}
        )

    def test_schema(self):
        tool = McpWebSearchTool("http://issuer", "http://gw")
        assert tool.name == "web_search"


class TestMcpToolDenied:
    @pytest.mark.asyncio
    async def test_denied_returns_message(self):
        from app.mcp_client import McpDeniedException
        client = MagicMock()
        client.execute = AsyncMock(side_effect=McpDeniedException("User denied"))
        tool = McpFileReadTool("http://issuer", "http://gw", client=client)
        result = await tool.execute(path="/secret")
        assert "Denied" in result
