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
    DEFAULT_CAPABILITIES,
    unsupported_capabilities_for_transport,
)
from app.tool_providers import ToolProviderContext, register_capability_tools
from app.tools.middleware import (
    MiddlewareFn, TracingMiddleware, logging_middleware,
)
from app.tools.registry import ToolRegistry
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
    command_runner=None,
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
        CAPABILITY_SHELL,
    }
    if transport == "direct" and any(
        capability_name in requires_local_workspace for capability_name in capability_names
    ) and workspace is None:
        raise ValueError(
            "A workspace is required for direct filesystem and memory capabilities."
        )

    register_capability_tools(
        registry,
        capability_names=capability_names,
        context=ToolProviderContext(
            smol_rag=smol_rag,
            workspace=workspace,
            llm=llm,
            transport=transport,
            token_issuer_url=token_issuer_url,
            gateway_url=gateway_url,
            agent_configs=agent_configs,
            session_manager=session_manager,
            hook_runner=hook_runner,
            enable_subagents=enable_subagents,
            command_runner=command_runner,
        ),
    )

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
