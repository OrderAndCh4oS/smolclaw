import os
import re
from dataclasses import dataclass, field
from itertools import count
from typing import Callable, Optional
from urllib.parse import quote

from app.agent_config import AgentConfig
from app.agent_loop import AgentLoop
from app.behaviors import load_behaviors, resolve_behavior_names
from app.context_builder import ContextBuilder
from app.definitions import PROJECT_ROOT
from app.hooks import HookRunner, ON_AFTER_TOOL
from app.llm import create_llm
from app.session import SessionManager
from app.tools.base import ToolRuntimeContext, normalize_tool_result
from app.tools.middleware import HookFiringMiddleware
from app.tools.memory_tools import _promote_accessed_excerpts
from app.tools.registry import ToolRegistry

_SHARED_BOOTSTRAP_PATH = os.path.join(PROJECT_ROOT, "AGENT.md")
HookRunnerConfigurer = Callable[[HookRunner], None]
HookRunnerConfigurers = tuple[HookRunnerConfigurer, ...]
SmolRagResolver = Callable[[AgentConfig], object | None]
HookRunnerConfigurersResolver = Callable[[AgentConfig], HookRunnerConfigurers]


def _make_promote_hook(smol_rag):
    async def _promote_hook(ctx):
        if not ctx.get("success"):
            return
        tool_name = ctx.get("tool_name")
        arguments = ctx.get("arguments", {})
        result = normalize_tool_result(ctx.get("result"))
        excerpt_ids = result.metadata.get("accessed_excerpt_ids") or []
        if not excerpt_ids:
            return
        if tool_name == "memory_search":
            await _promote_accessed_excerpts(smol_rag, excerpt_ids)
            return
        if tool_name == "memory_recall" and arguments.get("mode") == "topic":
            await _promote_accessed_excerpts(smol_rag, excerpt_ids)

    return _promote_hook


@dataclass
class ChildAgentFactory:
    master_registry: ToolRegistry
    smol_rag: object
    session_manager: SessionManager
    parent_session_key: str
    registry_factory: Optional[Callable[[AgentConfig], ToolRegistry]] = None
    loop_registrar: Optional[Callable[[AgentLoop], None]] = None
    context_builder_factory: Optional[Callable[[AgentConfig], ContextBuilder]] = None
    hook_runner_configurers: HookRunnerConfigurers = ()
    smol_rag_resolver: Optional[SmolRagResolver] = None
    hook_runner_configurers_resolver: Optional[HookRunnerConfigurersResolver] = None
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
        master_registry = (
            self.registry_factory(config)
            if self.registry_factory is not None
            else self.master_registry
        )
        smol_rag = (
            self.smol_rag_resolver(config)
            if self.smol_rag_resolver is not None
            else self.smol_rag
        )
        hook_runner_configurers = (
            self.hook_runner_configurers_resolver(config)
            if self.hook_runner_configurers_resolver is not None
            else self.hook_runner_configurers
        )
        loop = build_agent_loop(
            config=config,
            master_registry=master_registry,
            smol_rag=smol_rag,
            session_manager=self.session_manager,
            session_key=self.make_session_key(config.name, purpose),
            child_loop_registrar=self.loop_registrar,
            context_builder=(
                self.context_builder_factory(config)
                if self.context_builder_factory is not None
                else None
            ),
            hook_runner_configurers=hook_runner_configurers,
            child_smol_rag_resolver=self.smol_rag_resolver,
            child_hook_runner_configurers_resolver=self.hook_runner_configurers_resolver,
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
    context_builder: Optional[ContextBuilder] = None,
    context_builder_factory: Optional[Callable[[AgentConfig], ContextBuilder]] = None,
    registry_factory: Optional[Callable[[AgentConfig], ToolRegistry]] = None,
    hook_runner_configurers: HookRunnerConfigurers = (),
    child_smol_rag_resolver: Optional[SmolRagResolver] = None,
    child_hook_runner_configurers_resolver: Optional[HookRunnerConfigurersResolver] = None,
) -> AgentLoop:
    llm = create_llm(completion_model=config.model)
    agent_smol_rag = smol_rag
    if config.modules and "memory" not in config.modules:
        agent_smol_rag = None

    # Shared hook runner for tool hooks + agent lifecycle hooks
    if hook_runner is None:
        hook_runner = HookRunner()
    if not hook_runner_configurers and agent_smol_rag:
        hook_runner.on(ON_AFTER_TOOL, _make_promote_hook(agent_smol_rag))
    for configure_hook_runner in hook_runner_configurers:
        configure_hook_runner(hook_runner)

    resolved_session_key = session_key or f"{config.name}-{session_key_prefix}"
    runtime_ctx = ToolRuntimeContext(
        llm=llm,
        hook_runner=hook_runner,
        session_manager=session_manager,
        smol_rag=agent_smol_rag,
        session_key=resolved_session_key,
        loop_registrar=child_loop_registrar,
    )
    runtime_ctx.child_agent_factory = ChildAgentFactory(
        master_registry=master_registry,
        registry_factory=registry_factory,
        smol_rag=agent_smol_rag,
        session_manager=session_manager,
        parent_session_key=resolved_session_key,
        loop_registrar=child_loop_registrar,
        context_builder_factory=context_builder_factory,
        hook_runner_configurers=hook_runner_configurers,
        smol_rag_resolver=child_smol_rag_resolver,
        hook_runner_configurers_resolver=child_hook_runner_configurers_resolver,
    )
    filtered_registry = master_registry.project_for_agent(
        config.tools,
        runtime_ctx=runtime_ctx,
    )
    filtered_registry.use(HookFiringMiddleware(hook_runner))

    # Apply permission mode restrictions
    if config.permission_mode != "full":
        from app.tools.permissions import PermissionMiddleware
        filtered_registry.use(PermissionMiddleware(config.permission_mode))

    # Resolve skill paths
    skills_paths = [
        os.path.join(PROJECT_ROOT, "skills", s) for s in config.skills
    ]

    if context_builder is None and agent_smol_rag:
        from app.context_assembly import ContextAssembler
        context_builder = ContextAssembler(
            smol_rag=agent_smol_rag,
            token_budget=config.context_budget,
            bootstrap_path=config.bootstrap_path,
            persona=config.persona,
            shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
            skills_paths=skills_paths,
        )
    elif context_builder is None:
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
        smol_rag=agent_smol_rag,
        hook_runner=hook_runner,
        reflection=config.reflection,
        planning=config.planning,
        behaviors=load_behaviors(resolve_behavior_names(config)),
    )
    for resource in runtime_ctx.owned_resources:
        loop.add_owned_resource(resource)
    return loop
