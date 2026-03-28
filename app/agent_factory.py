import os
import re
from dataclasses import dataclass, field
from itertools import count
from typing import Callable, Optional
from urllib.parse import quote

from app.agent_config import AgentConfig
from app.agent_loop import AgentLoop
from app.context_builder import ContextBuilder
from app.definitions import PROJECT_ROOT
from app.hooks import HookRunner, ON_AFTER_TOOL
from app.llm import create_llm
from app.session import SessionManager
from app.tools.base import ToolRuntimeContext
from app.tools.middleware import HookFiringMiddleware
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


@dataclass
class ChildAgentFactory:
    master_registry: ToolRegistry
    smol_rag: object
    session_manager: SessionManager
    parent_session_key: str
    loop_registrar: Optional[Callable[[AgentLoop], None]] = None
    _counter: count = field(default_factory=lambda: count(1), init=False, repr=False)

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", value or "")
        return slug.strip("_") or "child"

    @staticmethod
    def _encode_session_segment(value: str) -> str:
        encoded = quote(value or "", safe="")
        return encoded or "child"

    def make_session_key(self, agent_name: str, purpose: str) -> str:
        invocation_id = next(self._counter)
        return (
            f"{self._encode_session_segment(self.parent_session_key)}__"
            f"{self._slugify(agent_name)}__"
            f"{self._slugify(purpose)}__"
            f"{invocation_id}"
        )

    def build(self, config: AgentConfig, purpose: str) -> AgentLoop:
        loop = build_agent_loop(
            config=config,
            master_registry=self.master_registry,
            smol_rag=self.smol_rag,
            session_manager=self.session_manager,
            session_key=self.make_session_key(config.name, purpose),
            child_loop_registrar=self.loop_registrar,
        )
        if self.loop_registrar:
            self.loop_registrar(loop)
        return loop


def build_agent_loop(
    config: AgentConfig,
    master_registry: ToolRegistry,
    smol_rag,
    session_manager: SessionManager,
    session_key_prefix: str = "default",
    session_key: Optional[str] = None,
    hook_runner: Optional[HookRunner] = None,
    child_loop_registrar: Optional[Callable[[AgentLoop], None]] = None,
) -> AgentLoop:
    llm = create_llm(completion_model=config.model)

    # Shared hook runner for tool hooks + agent lifecycle hooks
    if hook_runner is None:
        hook_runner = HookRunner()

    # Wire promote-on-access hook for memory tools
    if smol_rag:
        hook_runner.on(ON_AFTER_TOOL, _make_promote_hook(smol_rag))

    resolved_session_key = session_key or f"{config.name}-{session_key_prefix}"
    runtime_ctx = ToolRuntimeContext(
        llm=llm,
        hook_runner=hook_runner,
        session_manager=session_manager,
        smol_rag=smol_rag,
        session_key=resolved_session_key,
        loop_registrar=child_loop_registrar,
    )
    runtime_ctx.child_agent_factory = ChildAgentFactory(
        master_registry=master_registry,
        smol_rag=smol_rag,
        session_manager=session_manager,
        parent_session_key=resolved_session_key,
        loop_registrar=child_loop_registrar,
    )
    filtered_registry = master_registry.filter_by_names(config.tools, runtime_ctx=runtime_ctx)
    filtered_registry.use(HookFiringMiddleware(hook_runner))

    # Apply permission mode restrictions
    if config.permission_mode != "full":
        from app.tools.permissions import PermissionMiddleware
        filtered_registry.use(PermissionMiddleware(config.permission_mode))

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

    session = session_manager.get_or_create(resolved_session_key)
    loop = AgentLoop(
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
    for resource in runtime_ctx.owned_resources:
        loop.add_owned_resource(resource)
    return loop
