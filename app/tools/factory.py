"""Unified tool registry factory for CLI and Gateway."""

from typing import Dict, List, Optional

from app.runtime_capabilities import (
    CAPABILITY_COMMAND,
    CAPABILITY_FILESYSTEM,
    CAPABILITY_GOAL,
    CAPABILITY_MEMORY,
    CAPABILITY_ORCHESTRATION,
    CAPABILITY_SHELL,
    CAPABILITY_SUBAGENTS,
    CAPABILITY_WEB,
    DEFAULT_CAPABILITIES,
    unsupported_capabilities_for_transport,
)
from app.tools.middleware import (
    MiddlewareFn, TracingMiddleware, logging_middleware,
)
from app.tools.registry import ToolRegistry
from app.utilities import ensure_dir
from app.workspace import WorkspaceContext


def build_tool_registry(
    smol_rag,
    workspace: WorkspaceContext | None = None,
    llm=None,
    transport: str = "direct",
    token_issuer_url: str = None,
    gateway_url: str = None,
    middleware: List[MiddlewareFn] | None = None,
    agent_configs: Optional[Dict] = None,
    session_manager=None,
    hook_runner=None,
    capability_names: Optional[List[str]] = None,
    enable_subagents: bool = False,
) -> ToolRegistry:
    """Build a tool registry with transport-specific providers for each capability."""
    registry = ToolRegistry()

    if capability_names is None:
        capability_names = list(DEFAULT_CAPABILITIES)
        if session_manager is not None:
            capability_names.append(CAPABILITY_GOAL)
        if smol_rag is not None:
            capability_names.append(CAPABILITY_MEMORY)
        if agent_configs and session_manager:
            capability_names.append(CAPABILITY_ORCHESTRATION)
            if enable_subagents:
                capability_names.append(CAPABILITY_SUBAGENTS)

    unsupported = unsupported_capabilities_for_transport(capability_names, transport)
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(
            f"Transport '{transport}' does not support capabilities: {names}."
        )

    requires_local_workspace = {
        CAPABILITY_COMMAND,
        CAPABILITY_FILESYSTEM,
        CAPABILITY_MEMORY,
    }
    if transport == "direct" and any(
        capability_name in requires_local_workspace for capability_name in capability_names
    ) and workspace is None:
        raise ValueError(
            "A workspace is required for direct filesystem and memory capabilities."
        )

    for capability_name in capability_names:
        if capability_name == CAPABILITY_FILESYSTEM:
            from app.tools.filesystem import (
                ApplyPatchTool,
                EditFileTool,
                FindFilesTool,
                GrepSearchTool,
                ListDirTool,
                ReadFileTool,
                WriteFileTool,
            )

            if transport == "direct":
                registry.register(ReadFileTool(workspace=workspace), capability_name=capability_name)
                registry.register(WriteFileTool(workspace=workspace), capability_name=capability_name)
                registry.register(EditFileTool(workspace=workspace), capability_name=capability_name)
                registry.register(ListDirTool(workspace=workspace), capability_name=capability_name)
                registry.register(FindFilesTool(workspace=workspace), capability_name=capability_name)
                registry.register(ApplyPatchTool(workspace=workspace), capability_name=capability_name)
                registry.register(GrepSearchTool(workspace=workspace), capability_name=capability_name)
            else:
                from app.tools.mcp_tools import (
                    McpEditFileTool, McpFileReadTool, McpFileWriteTool,
                )

                registry.register(McpFileReadTool(token_issuer_url, gateway_url), capability_name=capability_name)
                registry.register(McpFileWriteTool(token_issuer_url, gateway_url), capability_name=capability_name)
                registry.register(McpEditFileTool(token_issuer_url, gateway_url), capability_name=capability_name)
        elif capability_name == CAPABILITY_WEB:
            if transport == "direct":
                from app.tools.web import WebSearchTool, WebFetchTool

                registry.register(WebSearchTool(), capability_name=capability_name)
                registry.register(WebFetchTool(), capability_name=capability_name)
            else:
                from app.tools.mcp_tools import (
                    McpHttpFetchTool, McpWebSearchTool,
                )

                registry.register(McpHttpFetchTool(token_issuer_url, gateway_url), capability_name=capability_name)
                registry.register(McpWebSearchTool(token_issuer_url, gateway_url), capability_name=capability_name)
        elif capability_name == CAPABILITY_SHELL:
            if transport == "direct":
                raise ValueError(
                    "Direct local shell execution is disabled until a real sandbox backend exists."
                )
            from app.tools.mcp_tools import (
                McpShellExecTool,
            )
            registry.register(McpShellExecTool(token_issuer_url, gateway_url), capability_name=capability_name)
        elif capability_name == CAPABILITY_COMMAND:
            if transport == "direct":
                from app.tools.command import GitDiffTool, GitStatusTool, RunCommandTool

                registry.register(GitStatusTool(workspace), capability_name=capability_name)
                registry.register(GitDiffTool(workspace), capability_name=capability_name)
                registry.register(RunCommandTool(workspace), capability_name=capability_name)
        elif capability_name == CAPABILITY_GOAL and session_manager:
            from app.tools.goal import GoalStartTool, GoalStatusTool, GoalUpdateTool

            registry.register(GoalStartTool(), capability_name=capability_name)
            registry.register(GoalStatusTool(), capability_name=capability_name)
            registry.register(GoalUpdateTool(), capability_name=capability_name)
        elif capability_name == CAPABILITY_MEMORY and smol_rag is not None:
            from app.tools.memory_tools import (
                MemorySearchTool, MemoryGraphQueryTool, MemoryStoreTool,
                MemoryRelateTool, MemoryRecallTool, MemoryGetTool,
                ContradictionReviewTool,
            )

            docs_dir = ensure_dir(workspace.paths.memory_docs_dir)
            registry.register(MemorySearchTool(smol_rag), capability_name=capability_name)
            registry.register(MemoryGraphQueryTool(smol_rag), capability_name=capability_name)
            registry.register(MemoryStoreTool(smol_rag, docs_dir, llm=llm), capability_name=capability_name)
            registry.register(MemoryRelateTool(smol_rag), capability_name=capability_name)
            registry.register(MemoryRecallTool(smol_rag), capability_name=capability_name)
            registry.register(MemoryGetTool(smol_rag), capability_name=capability_name)
            if hasattr(smol_rag, "contradiction_detector") and smol_rag.contradiction_detector:
                registry.register(ContradictionReviewTool(smol_rag.contradiction_detector), capability_name=capability_name)
        elif capability_name == CAPABILITY_ORCHESTRATION and agent_configs and session_manager:
            from app.tools.orchestration_tools import (
                SequentialPipelineTool, FanoutPipelineTool, RouteTool,
            )

            registry.register(SequentialPipelineTool(agent_configs, registry, smol_rag, session_manager), capability_name=capability_name)
            registry.register(FanoutPipelineTool(agent_configs, registry, smol_rag, session_manager), capability_name=capability_name)
            registry.register(RouteTool(agent_configs, registry, smol_rag, session_manager), capability_name=capability_name)
        elif capability_name == CAPABILITY_SUBAGENTS and agent_configs:
            from app.tools.spawn import SpawnTool, GetResultTool, AwaitResultTool

            registry.register(SpawnTool(configs=agent_configs), capability_name=capability_name)
            registry.register(GetResultTool(configs=agent_configs), capability_name=capability_name)
            registry.register(AwaitResultTool(configs=agent_configs), capability_name=capability_name)
        elif capability_name not in {
            CAPABILITY_FILESYSTEM,
            CAPABILITY_WEB,
            CAPABILITY_MEMORY,
            CAPABILITY_ORCHESTRATION,
            CAPABILITY_SUBAGENTS,
            CAPABILITY_SHELL,
            CAPABILITY_COMMAND,
            CAPABILITY_GOAL,
        }:
            continue

    if registry.has_deferred_tools() and not any(
        tool.name == "tool_search" for tool in registry.values()
    ):
        from app.tools.tool_search import ToolSearchTool

        registry.register(ToolSearchTool(registry), capability_name="tool_discovery")

    # Register catalog-wide middleware. Runtime-bound middleware is installed per agent loop.
    registry.use(logging_middleware)
    registry.use(TracingMiddleware())
    for mw in (middleware or []):
        registry.use(mw)

    return registry
