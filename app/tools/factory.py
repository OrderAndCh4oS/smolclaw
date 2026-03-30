"""Unified tool registry factory for CLI and Gateway."""

from typing import Dict, List, Optional

from app.tools.middleware import (
    MiddlewareFn, TracingMiddleware, logging_middleware,
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
    middleware: List[MiddlewareFn] | None = None,
    agent_configs: Optional[Dict] = None,
    session_manager=None,
    hook_runner=None,
    module_names: Optional[List[str]] = None,
    enable_subagents: bool = False,
) -> ToolRegistry:
    """Build a tool registry with appropriate tools based on mode.

    mode="direct": CLI tools (filesystem, shell, web)
    mode="mcp": MCP-delegating wrappers for gateway
    """
    registry = ToolRegistry()
    tool_discovery_requested = False

    if module_names is None:
        module_names = [f"transport.{mode}"]
        if smol_rag is not None:
            module_names.append("memory")
        if agent_configs and session_manager:
            module_names.append("orchestration")
            if enable_subagents:
                module_names.append("subagents")
        module_names.append("tool_discovery")

    for module_name in module_names:
        if module_name == "transport.direct":
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
        elif module_name == "transport.mcp":
            from app.tools.mcp_tools import (
                McpFileReadTool, McpFileWriteTool, McpShellExecTool,
                McpHttpFetchTool, McpWebSearchTool,
            )

            registry.register(McpFileReadTool(token_issuer_url, gateway_url))
            registry.register(McpFileWriteTool(token_issuer_url, gateway_url))
            registry.register(McpShellExecTool(token_issuer_url, gateway_url))
            registry.register(McpHttpFetchTool(token_issuer_url, gateway_url))
            registry.register(McpWebSearchTool(token_issuer_url, gateway_url))
        elif module_name == "memory" and smol_rag is not None:
            from app.tools.memory_tools import (
                MemorySearchTool, MemoryGraphQueryTool, MemoryStoreTool,
                MemoryRelateTool, MemoryRecallTool, MemoryGetTool,
                ContradictionReviewTool,
            )

            docs_dir = ensure_dir(memory_docs_dir)
            registry.register(MemorySearchTool(smol_rag))
            registry.register(MemoryGraphQueryTool(smol_rag))
            registry.register(MemoryStoreTool(smol_rag, docs_dir, llm=llm))
            registry.register(MemoryRelateTool(smol_rag))
            registry.register(MemoryRecallTool(smol_rag))
            registry.register(MemoryGetTool(smol_rag))
            if hasattr(smol_rag, "contradiction_detector") and smol_rag.contradiction_detector:
                registry.register(ContradictionReviewTool(smol_rag.contradiction_detector))
        elif module_name == "orchestration" and agent_configs and session_manager:
            from app.tools.orchestration_tools import (
                SequentialPipelineTool, FanoutPipelineTool, RouteTool,
            )

            registry.register(SequentialPipelineTool(agent_configs, registry, smol_rag, session_manager))
            registry.register(FanoutPipelineTool(agent_configs, registry, smol_rag, session_manager))
            registry.register(RouteTool(agent_configs, registry, smol_rag, session_manager))
        elif module_name == "subagents" and agent_configs:
            from app.tools.spawn import SpawnTool, GetResultTool, AwaitResultTool

            registry.register(SpawnTool(configs=agent_configs))
            registry.register(GetResultTool(configs=agent_configs))
            registry.register(AwaitResultTool(configs=agent_configs))
        elif module_name == "tool_discovery":
            tool_discovery_requested = True

    if tool_discovery_requested and registry.has_deferred_tools():
        from app.tools.tool_search import ToolSearchTool

        registry.register(ToolSearchTool(registry))

    # Register catalog-wide middleware. Runtime-bound middleware is installed per agent loop.
    registry.use(logging_middleware)
    registry.use(TracingMiddleware())
    for mw in (middleware or []):
        registry.use(mw)

    return registry
