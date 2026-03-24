import json
from typing import Any, Dict

from app.mcp_client import McpClient, McpDeniedException
from app.tools.base import Tool


class McpToolBase(Tool):
    """Base class for MCP-delegating tools."""

    def __init__(self, token_issuer_url: str):
        self._client = McpClient(token_issuer_url)

    @property
    def _mcp_tool_name(self) -> str:
        raise NotImplementedError

    async def _call_mcp(self, params: Dict[str, Any]) -> str:
        try:
            result = await self._client.execute(self._mcp_tool_name, params)
            content = result.get("content", [])
            if isinstance(content, list):
                return "\n".join(
                    item.get("text", json.dumps(item))
                    for item in content
                    if isinstance(item, dict)
                ) or json.dumps(result)
            return str(content)
        except McpDeniedException as e:
            return f"Denied: {e}"
        except Exception as e:
            return f"Error: {e}"


class McpFileReadTool(McpToolBase):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read a file's contents via MCP."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
            },
            "required": ["path"],
        }

    @property
    def _mcp_tool_name(self) -> str:
        return "file-read"

    async def execute(self, **kwargs) -> str:
        return await self._call_mcp({"path": kwargs["path"]})


class McpFileWriteTool(McpToolBase):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file via MCP."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        }

    @property
    def _mcp_tool_name(self) -> str:
        return "file-write"

    async def execute(self, **kwargs) -> str:
        return await self._call_mcp({"path": kwargs["path"], "content": kwargs["content"]})


class McpShellExecTool(McpToolBase):
    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command via MCP."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute"},
            },
            "required": ["command"],
        }

    @property
    def _mcp_tool_name(self) -> str:
        return "shell-exec"

    async def execute(self, **kwargs) -> str:
        return await self._call_mcp({"command": kwargs["command"]})


class McpHttpFetchTool(McpToolBase):
    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch a URL via MCP."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        }

    @property
    def _mcp_tool_name(self) -> str:
        return "http-fetch"

    async def execute(self, **kwargs) -> str:
        return await self._call_mcp({"url": kwargs["url"]})


class McpWebSearchTool(McpToolBase):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web via MCP."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        }

    @property
    def _mcp_tool_name(self) -> str:
        return "web-search"

    async def execute(self, **kwargs) -> str:
        return await self._call_mcp({"query": kwargs["query"]})
