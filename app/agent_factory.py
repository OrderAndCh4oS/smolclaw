import os
from typing import Optional

from app.agent_config import AgentConfig
from app.agent_loop import AgentLoop
from app.context_builder import ContextBuilder
from app.definitions import PROJECT_ROOT
from app.hooks import HookRunner, ON_AFTER_TOOL
from app.llm import create_llm
from app.session import SessionManager
from app.tools.memory_tools import _promote_accessed_excerpts
from app.tools.registry import ToolRegistry

_SHARED_BOOTSTRAP_PATH = os.path.join(PROJECT_ROOT, "AGENT.md")


def _make_promote_hook(smol_rag):
    """Create a hook callback that promotes memory excerpts accessed via search/recall tools."""
    async def _promote_hook(ctx):
        tool_name = ctx.get("tool_name")
        if tool_name in ("memory_search", "memory_recall"):
            query = ctx.get("arguments", {}).get("query")
            if query:
                await _promote_accessed_excerpts(smol_rag, query)
    return _promote_hook


def build_agent_loop(
    config: AgentConfig,
    master_registry: ToolRegistry,
    smol_rag,
    session_manager: SessionManager,
    session_key_prefix: str = "default",
    session_key: Optional[str] = None,
    hook_runner: Optional[HookRunner] = None,
) -> AgentLoop:
    llm = create_llm(completion_model=config.model)
    filtered_registry = master_registry.filter_by_names(config.tools)

    # Apply permission mode restrictions
    if config.permission_mode != "full":
        from app.tools.permissions import PermissionMiddleware
        filtered_registry.use(PermissionMiddleware(config.permission_mode))

    # Shared hook runner for tool hooks + agent lifecycle hooks
    if hook_runner is None:
        hook_runner = HookRunner()

    # Wire promote-on-access hook for memory tools
    if smol_rag:
        hook_runner.on(ON_AFTER_TOOL, _make_promote_hook(smol_rag))

    # Resolve skill paths
    skills_paths = [
        os.path.join(PROJECT_ROOT, "skills", s) for s in config.skills
    ]

    if smol_rag:
        from app.context_assembly import ContextAssembler
        context_builder = ContextAssembler(
            smol_rag=smol_rag,
            token_budget=config.context_budget,
            bootstrap_path=config.bootstrap_path,
            persona=config.persona,
            shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
            skills_paths=skills_paths,
        )
    else:
        context_builder = ContextBuilder(
            bootstrap_path=config.bootstrap_path,
            persona=config.persona,
            shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
            skills_paths=skills_paths,
        )

    resolved_session_key = session_key or f"{config.name}-{session_key_prefix}"
    session = session_manager.get_or_create(resolved_session_key)
    return AgentLoop(
        llm=llm,
        tool_registry=filtered_registry,
        context_builder=context_builder,
        session=session,
        session_manager=session_manager,
        max_iterations=config.max_iterations,
        memory_window=config.memory_window,
        smol_rag=smol_rag,
        hook_runner=hook_runner,
        reflection=config.reflection,
        planning=config.planning,
    )
