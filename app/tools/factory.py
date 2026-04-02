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

            registry.register(ReadFileTool(allowed_dir=workspace), module_name=module_name)
            registry.register(WriteFileTool(allowed_dir=workspace), module_name=module_name)
            registry.register(EditFileTool(allowed_dir=workspace), module_name=module_name)
            registry.register(ListDirTool(allowed_dir=workspace), module_name=module_name)
            registry.register(ExecTool(allowed_dir=workspace), module_name=module_name)
            registry.register(WebSearchTool(), module_name=module_name)
            registry.register(WebFetchTool(), module_name=module_name)
        elif module_name == "transport.mcp":
            from app.tools.mcp_tools import (
                McpFileReadTool, McpFileWriteTool, McpShellExecTool,
                McpHttpFetchTool, McpWebSearchTool,
            )

            registry.register(McpFileReadTool(token_issuer_url, gateway_url), module_name=module_name)
            registry.register(McpFileWriteTool(token_issuer_url, gateway_url), module_name=module_name)
            registry.register(McpShellExecTool(token_issuer_url, gateway_url), module_name=module_name)
            registry.register(McpHttpFetchTool(token_issuer_url, gateway_url), module_name=module_name)
            registry.register(McpWebSearchTool(token_issuer_url, gateway_url), module_name=module_name)
        elif module_name == "memory" and smol_rag is not None:
            from app.tools.memory_tools import (
                MemorySearchTool, MemoryGraphQueryTool, MemoryStoreTool,
                MemoryRelateTool, MemoryRecallTool, MemoryGetTool,
                ContradictionReviewTool,
            )

            docs_dir = ensure_dir(memory_docs_dir)
            registry.register(MemorySearchTool(smol_rag), module_name=module_name)
            registry.register(MemoryGraphQueryTool(smol_rag), module_name=module_name)
            registry.register(MemoryStoreTool(smol_rag, docs_dir, llm=llm), module_name=module_name)
            registry.register(MemoryRelateTool(smol_rag), module_name=module_name)
            registry.register(MemoryRecallTool(smol_rag), module_name=module_name)
            registry.register(MemoryGetTool(smol_rag), module_name=module_name)
            if hasattr(smol_rag, "contradiction_detector") and smol_rag.contradiction_detector:
                registry.register(ContradictionReviewTool(smol_rag.contradiction_detector), module_name=module_name)
        elif module_name == "orchestration" and agent_configs and session_manager:
            from app.tools.orchestration_tools import (
                SequentialPipelineTool, FanoutPipelineTool, RouteTool,
            )

            registry.register(SequentialPipelineTool(agent_configs, registry, smol_rag, session_manager), module_name=module_name)
            registry.register(FanoutPipelineTool(agent_configs, registry, smol_rag, session_manager), module_name=module_name)
            registry.register(RouteTool(agent_configs, registry, smol_rag, session_manager), module_name=module_name)
        elif module_name == "subagents" and agent_configs:
            from app.tools.spawn import SpawnTool, GetResultTool, AwaitResultTool

            registry.register(SpawnTool(configs=agent_configs), module_name=module_name)
            registry.register(GetResultTool(configs=agent_configs), module_name=module_name)
            registry.register(AwaitResultTool(configs=agent_configs), module_name=module_name)
        elif module_name == "tool_discovery":
            # Backward-compatible no-op alias. Deferred tools are always searchable.
            continue

    if registry.has_deferred_tools() and not any(
        tool.name == "tool_search" for tool in registry.values()
    ):
        from app.tools.tool_search import ToolSearchTool

        registry.register(ToolSearchTool(registry), module_name="tool_discovery")

    # Register catalog-wide middleware. Runtime-bound middleware is installed per agent loop.
    registry.use(logging_middleware)
    registry.use(TracingMiddleware())
    for mw in (middleware or []):
        registry.use(mw)

    return registry
