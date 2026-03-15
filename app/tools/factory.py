"""Unified tool registry factory for CLI and Gateway."""

from app.tools.memory_tools import (
    MemorySearchTool, MemoryGraphQueryTool, MemoryStoreTool,
    MemoryRelateTool, MemoryRecallTool, MemoryGetTool,
    ContradictionReviewTool,
)
from app.tools.registry import ToolRegistry
from app.utilities import ensure_dir


def build_tool_registry(
    smol_rag,
    memory_docs_dir: str,
    workspace: str = None,
    llm=None,
    mode: str = "direct",
    token_issuer_url: str = None,
    gateway_url: str = None,
) -> ToolRegistry:
    """Build a tool registry with appropriate tools based on mode.

    mode="direct": CLI tools (filesystem, shell, web)
    mode="mcp": MCP-delegating wrappers for gateway
    """
    registry = ToolRegistry()

    if mode == "direct":
        from app.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
        from app.tools.shell import ExecTool
        from app.tools.web import WebSearchTool, WebFetchTool

        registry.register(ReadFileTool(allowed_dir=workspace))
        registry.register(WriteFileTool(allowed_dir=workspace))
        registry.register(EditFileTool(allowed_dir=workspace))
        registry.register(ListDirTool(allowed_dir=workspace))
        registry.register(ExecTool())
        registry.register(WebSearchTool())
        registry.register(WebFetchTool())
    elif mode == "mcp":
        from app.tools.mcp_tools import (
            McpFileReadTool, McpFileWriteTool, McpShellExecTool,
            McpHttpFetchTool, McpWebSearchTool,
        )

        registry.register(McpFileReadTool(token_issuer_url, gateway_url))
        registry.register(McpFileWriteTool(token_issuer_url, gateway_url))
        registry.register(McpShellExecTool(token_issuer_url, gateway_url))
        registry.register(McpHttpFetchTool(token_issuer_url, gateway_url))
        registry.register(McpWebSearchTool(token_issuer_url, gateway_url))

    # Memory tools are shared across both modes
    docs_dir = ensure_dir(memory_docs_dir)
    registry.register(MemorySearchTool(smol_rag))
    registry.register(MemoryGraphQueryTool(smol_rag))
    registry.register(MemoryStoreTool(smol_rag, docs_dir, llm=llm))
    registry.register(MemoryRelateTool(smol_rag))
    registry.register(MemoryRecallTool(smol_rag))
    registry.register(MemoryGetTool(smol_rag))

    # Contradiction review tool (only when detector is wired up)
    if hasattr(smol_rag, 'contradiction_detector') and smol_rag.contradiction_detector:
        registry.register(ContradictionReviewTool(smol_rag.contradiction_detector))

    return registry
