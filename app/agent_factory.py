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
from app.approvals import ApprovalRequestStore
from app.goal_ledger import GoalLedgerStore
from app.hooks import HookRunner, ON_AFTER_TOOL
from app.llm import create_llm
from app.checkpoints import CheckpointStore
from app.model_settings import ModelSelection, RuntimeModelSettings, apply_model_selection
from app.run_trace import RunTraceStore
from app.session import SessionManager
from app.tools.base import ToolRuntimeContext, normalize_tool_result
from app.tools.middleware import HookFiringMiddleware
from app.tools.memory_tools import _promote_accessed_excerpts
from app.tools.registry import ToolRegistry
from app.tools.safety import SafetyMiddleware, SafetyState
from app.workspace import WorkspaceContext

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
        result = normalize_tool_result(ctx.get("result"))
        excerpt_ids = result.metadata.get("accessed_excerpt_ids") or []
        if not excerpt_ids:
            return
        if tool_name in {"memory_search", "memory_recall"}:
            await _promote_accessed_excerpts(smol_rag, excerpt_ids)

    return _promote_hook


@dataclass
class ChildAgentFactory:
    master_registry: ToolRegistry
    smol_rag: object
    workspace: WorkspaceContext | None
    session_manager: SessionManager
    parent_session_key: str
    llm_factory_kwargs: Optional[dict] = None
    model_settings: RuntimeModelSettings | None = None
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
            workspace=self.workspace,
            session_key=self.make_session_key(config.name, purpose),
            child_loop_registrar=self.loop_registrar,
            context_builder=(
                self.context_builder_factory(config)
                if self.context_builder_factory is not None
                else None
            ),
            context_builder_factory=self.context_builder_factory,
            registry_factory=self.registry_factory,
            hook_runner_configurers=hook_runner_configurers,
            child_smol_rag_resolver=self.smol_rag_resolver,
            child_hook_runner_configurers_resolver=self.hook_runner_configurers_resolver,
            llm_factory_kwargs=self.llm_factory_kwargs,
            model_settings=self.model_settings,
            is_child_agent=True,
        )
        if self.loop_registrar:
            self.loop_registrar(loop)
        return loop


def build_agent_loop(
    config: AgentConfig,
    master_registry: ToolRegistry,
    smol_rag,
    session_manager: SessionManager,
    workspace: WorkspaceContext | None = None,
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
    llm_factory_kwargs: Optional[dict] = None,
    model_selection: ModelSelection | None = None,
    model_settings: RuntimeModelSettings | None = None,
    is_child_agent: bool = False,
) -> AgentLoop:
    selection = model_selection
    if selection is None and model_settings is not None:
        selection = model_settings.resolve(config.model, subagent=is_child_agent)
    completion_model = selection.model if selection is not None else config.model
    llm = create_llm(completion_model=completion_model, **(llm_factory_kwargs or {}))
    if selection is not None:
        apply_model_selection(llm, selection)
    agent_smol_rag = smol_rag
    if config.capabilities and "memory" not in config.capabilities:
        agent_smol_rag = None

    missing_tools = sorted(set(config.tools) - master_registry.tool_names())
    if missing_tools:
        names = ", ".join(missing_tools)
        raise ValueError(f"Agent '{config.name}' requests unavailable tools: {names}.")

    # Shared hook runner for tool hooks + agent lifecycle hooks
    if hook_runner is None:
        hook_runner = HookRunner()
    if not hook_runner_configurers and agent_smol_rag:
        hook_runner.on(ON_AFTER_TOOL, _make_promote_hook(agent_smol_rag))
    for configure_hook_runner in hook_runner_configurers:
        configure_hook_runner(hook_runner)

    resolved_session_key = session_key or f"{config.name}-{session_key_prefix}"
    goal_store = GoalLedgerStore(workspace.paths.ledgers_dir) if session_manager and workspace is not None else None
    runtime_ctx = ToolRuntimeContext(
        llm=llm,
        hook_runner=hook_runner,
        session_manager=session_manager,
        smol_rag=agent_smol_rag,
        workspace=workspace,
        session_key=resolved_session_key,
        goal_store=goal_store,
        loop_registrar=child_loop_registrar,
    )
    safety_state = SafetyState(workspace=workspace)
    runtime_ctx.shared_state["safety_state"] = safety_state
    runtime_ctx.shared_state["session_key"] = resolved_session_key
    trace_store = RunTraceStore(workspace.paths.traces_dir) if workspace is not None else None
    if trace_store is not None:
        runtime_ctx.shared_state["trace_store"] = trace_store
    if workspace is not None:
        runtime_ctx.shared_state["approval_store"] = ApprovalRequestStore(workspace.paths.approvals_dir)
    runtime_ctx.child_agent_factory = ChildAgentFactory(
        master_registry=master_registry,
        registry_factory=registry_factory,
        smol_rag=agent_smol_rag,
        workspace=workspace,
        session_manager=session_manager,
        parent_session_key=resolved_session_key,
        llm_factory_kwargs=llm_factory_kwargs,
        loop_registrar=child_loop_registrar,
        context_builder_factory=context_builder_factory,
        hook_runner_configurers=hook_runner_configurers,
        smol_rag_resolver=child_smol_rag_resolver,
        hook_runner_configurers_resolver=child_hook_runner_configurers_resolver,
        model_settings=model_settings,
    )
    filtered_registry = master_registry.project_for_agent(
        config.tools,
        runtime_ctx=runtime_ctx,
        allowed_capabilities=config.capabilities or None,
    )
    filtered_registry.use(HookFiringMiddleware(hook_runner))

    # Apply permission mode, loaded policy, and path safety restrictions.
    from app.tools.evidence import EvidenceMiddleware
    from app.tools.policy import PolicyPermissionMiddleware, load_permission_policy

    permission_policy = load_permission_policy(workspace)
    runtime_ctx.shared_state["permission_policy"] = permission_policy
    filtered_registry.use(PolicyPermissionMiddleware(
        config.permission_mode,
        workspace=workspace,
        policy=permission_policy,
        shared_state=runtime_ctx.shared_state,
    ))
    filtered_registry.use(SafetyMiddleware(safety_state))
    filtered_registry.use(EvidenceMiddleware(
        shared_state=runtime_ctx.shared_state,
        goal_store=goal_store,
        session_key=resolved_session_key,
    ))
    if workspace is not None:
        from app.tools.checkpointing import CheckpointMiddleware

        checkpoint_store = CheckpointStore(workspace.paths.checkpoints_dir)
        runtime_ctx.shared_state["checkpoint_store"] = checkpoint_store
        filtered_registry.use(CheckpointMiddleware(
            checkpoint_store,
            workspace=workspace,
            session_key=resolved_session_key,
            shared_state=runtime_ctx.shared_state,
            goal_store=goal_store,
        ))

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
        goal_store=goal_store,
        safety_state=safety_state,
        model_settings=model_settings,
        trace_store=trace_store,
        runtime_shared_state=runtime_ctx.shared_state,
    )
    for resource in runtime_ctx.owned_resources:
        loop.add_owned_resource(resource)
    return loop
