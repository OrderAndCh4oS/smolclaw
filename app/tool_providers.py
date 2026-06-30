"""Capability-specific tool provider composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol

from app.runtime_capabilities import (
    CAPABILITY_COMMAND,
    CAPABILITY_FILESYSTEM,
    CAPABILITY_GOAL,
    CAPABILITY_MEMORY,
    CAPABILITY_ORCHESTRATION,
    CAPABILITY_SHELL,
    CAPABILITY_SUBAGENTS,
    CAPABILITY_WEB,
)
from app.shell_sessions import DockerShellSessionService
from app.tools.registry import ToolRegistry
from app.utilities import ensure_dir
from app.workspace import WorkspaceContext


@dataclass(frozen=True)
class ToolProviderContext:
    smol_rag: object | None
    workspace: WorkspaceContext | None
    llm: object = None
    transport: str = "direct"
    token_issuer_url: str | None = None
    gateway_url: str | None = None
    agent_configs: Optional[Dict] = None
    session_manager: object = None
    hook_runner: object = None
    enable_subagents: bool = False
    command_runner: object = None


class ToolProvider(Protocol):
    capability_name: str

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        ...


class FilesystemToolProvider:
    capability_name = CAPABILITY_FILESYSTEM

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        if context.transport == "direct":
            from app.tools.filesystem import (
                ApplyPatchTool,
                EditFileTool,
                FindFilesTool,
                GrepSearchTool,
                ListDirTool,
                ReadFileTool,
                WriteFileTool,
            )

            registry.register(ReadFileTool(workspace=context.workspace), capability_name=self.capability_name)
            registry.register(WriteFileTool(workspace=context.workspace), capability_name=self.capability_name)
            registry.register(EditFileTool(workspace=context.workspace), capability_name=self.capability_name)
            registry.register(ListDirTool(workspace=context.workspace), capability_name=self.capability_name)
            registry.register(FindFilesTool(workspace=context.workspace), capability_name=self.capability_name)
            registry.register(ApplyPatchTool(workspace=context.workspace), capability_name=self.capability_name)
            registry.register(GrepSearchTool(workspace=context.workspace), capability_name=self.capability_name)
            return

        from app.tools.mcp_tools import McpEditFileTool, McpFileReadTool, McpFileWriteTool

        registry.register(McpFileReadTool(context.token_issuer_url, context.gateway_url), capability_name=self.capability_name)
        registry.register(McpFileWriteTool(context.token_issuer_url, context.gateway_url), capability_name=self.capability_name)
        registry.register(McpEditFileTool(context.token_issuer_url, context.gateway_url), capability_name=self.capability_name)


class WebToolProvider:
    capability_name = CAPABILITY_WEB

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        if context.transport == "direct":
            from app.tools.web import WebFetchTool, WebSearchTool

            registry.register(WebSearchTool(), capability_name=self.capability_name)
            registry.register(WebFetchTool(), capability_name=self.capability_name)
            return

        from app.tools.mcp_tools import McpHttpFetchTool, McpWebSearchTool

        registry.register(McpHttpFetchTool(context.token_issuer_url, context.gateway_url), capability_name=self.capability_name)
        registry.register(McpWebSearchTool(context.token_issuer_url, context.gateway_url), capability_name=self.capability_name)


class ShellToolProvider:
    capability_name = CAPABILITY_SHELL

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        if context.transport == "direct":
            from app.tools.command import ShellSessionTool

            if not bool(getattr(context.command_runner, "supports_shell_sessions", False)):
                raise ValueError(
                    "Direct shell sessions require adapters.command.provider: docker."
                )
            registry.register(
                ShellSessionTool(
                    context.workspace,
                    service_factory=lambda ws, shared_state: DockerShellSessionService(
                        workspace=ws,
                        shared_state=shared_state,
                        command_runner=context.command_runner,
                    ),
                ),
                capability_name=self.capability_name,
            )
            return

        from app.tools.mcp_tools import McpShellExecTool

        registry.register(McpShellExecTool(context.token_issuer_url, context.gateway_url), capability_name=self.capability_name)


class CommandToolProvider:
    capability_name = CAPABILITY_COMMAND

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        if context.transport != "direct":
            return
        from app.tools.command import (
            GitAddTool,
            GitBranchTool,
            GitCheckoutTool,
            GitCommitTool,
            GitDiffTool,
            GitPullTool,
            GitPushTool,
            GitStatusTool,
            RunCommandTool,
        )
        from app.tools.work_loop import (
            WorkLoopCloseTaskTool,
            WorkLoopCommentTaskTool,
            WorkLoopCreateTaskTool,
            WorkLoopListTasksTool,
            WorkLoopMoveTaskTool,
            WorkLoopViewTaskTool,
        )

        registry.register(GitStatusTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(GitDiffTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(GitBranchTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(GitCheckoutTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(GitPullTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(GitAddTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(GitCommitTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(GitPushTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(RunCommandTool(context.workspace, command_runner=context.command_runner), capability_name=self.capability_name)
        registry.register(WorkLoopListTasksTool(workspace=context.workspace), capability_name=self.capability_name)
        registry.register(WorkLoopViewTaskTool(workspace=context.workspace), capability_name=self.capability_name)
        registry.register(WorkLoopCreateTaskTool(workspace=context.workspace), capability_name=self.capability_name)
        registry.register(WorkLoopMoveTaskTool(workspace=context.workspace), capability_name=self.capability_name)
        registry.register(WorkLoopCommentTaskTool(workspace=context.workspace), capability_name=self.capability_name)
        registry.register(WorkLoopCloseTaskTool(workspace=context.workspace), capability_name=self.capability_name)


class GoalToolProvider:
    capability_name = CAPABILITY_GOAL

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        if not context.session_manager:
            return
        from app.tools.goal import GoalRecordEvidenceTool, GoalStartTool, GoalStatusTool, GoalUpdateTool

        registry.register(GoalStartTool(), capability_name=self.capability_name)
        registry.register(GoalStatusTool(), capability_name=self.capability_name)
        registry.register(GoalUpdateTool(), capability_name=self.capability_name)
        registry.register(GoalRecordEvidenceTool(), capability_name=self.capability_name)


class MemoryToolProvider:
    capability_name = CAPABILITY_MEMORY

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        if context.smol_rag is None:
            return
        from app.tools.memory_tools import (
            ContradictionReviewTool,
            MemoryGetTool,
            MemoryGraphQueryTool,
            MemoryRecallTool,
            MemoryRelateTool,
            MemorySearchTool,
            MemoryStoreTool,
        )
        from app.tools.research_sources import ResearchSourceStoreTool

        docs_dir = ensure_dir(context.workspace.paths.memory_docs_dir)
        research_dir = ensure_dir(context.workspace.paths.research_dir)
        registry.register(MemorySearchTool(context.smol_rag), capability_name=self.capability_name)
        registry.register(MemoryGraphQueryTool(context.smol_rag), capability_name=self.capability_name)
        registry.register(MemoryStoreTool(context.smol_rag, docs_dir, llm=context.llm), capability_name=self.capability_name)
        registry.register(ResearchSourceStoreTool(research_dir, smol_rag=context.smol_rag), capability_name=self.capability_name)
        registry.register(MemoryRelateTool(context.smol_rag), capability_name=self.capability_name)
        registry.register(MemoryRecallTool(context.smol_rag), capability_name=self.capability_name)
        registry.register(MemoryGetTool(context.smol_rag), capability_name=self.capability_name)
        if hasattr(context.smol_rag, "contradiction_detector") and context.smol_rag.contradiction_detector:
            registry.register(ContradictionReviewTool(context.smol_rag.contradiction_detector), capability_name=self.capability_name)


class OrchestrationToolProvider:
    capability_name = CAPABILITY_ORCHESTRATION

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        if not (context.agent_configs and context.session_manager):
            return
        from app.tools.orchestration_tools import FanoutPipelineTool, RouteTool, SequentialPipelineTool

        registry.register(
            SequentialPipelineTool(context.agent_configs, registry, context.smol_rag, context.session_manager),
            capability_name=self.capability_name,
        )
        registry.register(
            FanoutPipelineTool(context.agent_configs, registry, context.smol_rag, context.session_manager),
            capability_name=self.capability_name,
        )
        registry.register(
            RouteTool(context.agent_configs, registry, context.smol_rag, context.session_manager),
            capability_name=self.capability_name,
        )


class SubagentToolProvider:
    capability_name = CAPABILITY_SUBAGENTS

    def register(self, registry: ToolRegistry, context: ToolProviderContext) -> None:
        if not context.agent_configs:
            return
        from app.tools.spawn import AwaitResultTool, GetResultTool, SpawnTool

        registry.register(SpawnTool(configs=context.agent_configs), capability_name=self.capability_name)
        registry.register(GetResultTool(configs=context.agent_configs), capability_name=self.capability_name)
        registry.register(AwaitResultTool(configs=context.agent_configs), capability_name=self.capability_name)


TOOL_PROVIDERS: dict[str, ToolProvider] = {
    CAPABILITY_FILESYSTEM: FilesystemToolProvider(),
    CAPABILITY_WEB: WebToolProvider(),
    CAPABILITY_SHELL: ShellToolProvider(),
    CAPABILITY_COMMAND: CommandToolProvider(),
    CAPABILITY_GOAL: GoalToolProvider(),
    CAPABILITY_MEMORY: MemoryToolProvider(),
    CAPABILITY_ORCHESTRATION: OrchestrationToolProvider(),
    CAPABILITY_SUBAGENTS: SubagentToolProvider(),
}


def register_capability_tools(
    registry: ToolRegistry,
    *,
    capability_names: List[str],
    context: ToolProviderContext,
) -> None:
    for capability_name in capability_names:
        provider = TOOL_PROVIDERS.get(capability_name)
        if provider is not None:
            provider.register(registry, context)
