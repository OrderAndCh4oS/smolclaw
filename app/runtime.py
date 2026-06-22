import os
from dataclasses import dataclass, replace
from typing import Callable, Dict, Optional, Sequence

from app.agent_config import AgentConfig
from app.agent_factory import _make_promote_hook, build_agent_loop
from app.context_assembly import ContextAssembler
from app.context_builder import ContextBuilder
from app.definitions import PROJECT_ROOT
from app.hooks import HookRunner, ON_AFTER_TOOL
from app.runtime_capabilities import (
    CAPABILITY_GOAL,
    CAPABILITY_MEMORY,
    CAPABILITY_ORCHESTRATION,
    CAPABILITY_SUBAGENTS,
    DEFAULT_CAPABILITIES,
    Transport,
)
from app.session import SessionManager
from app.tools.factory import build_tool_registry
from app.workspace import WorkspaceContext

_SHARED_BOOTSTRAP_PATH = f"{PROJECT_ROOT}/AGENT.md"


def _instruction_paths_for_workspace(workspace: WorkspaceContext) -> list[str]:
    paths = []
    global_agents = "~/.config/smolclaw/AGENTS.md"
    paths.append(global_agents)

    project_agents = workspace.resolve_path("AGENTS.md")
    project_claude = workspace.resolve_path("CLAUDE.md")
    if os.path.exists(project_agents):
        paths.append(project_agents)
    elif os.path.exists(project_claude):
        paths.append(project_claude)

    local_instructions = workspace.resolve_path(".smolclaw/instructions.md")
    paths.append(local_instructions)
    return paths


@dataclass(frozen=True)
class RuntimeEnvironment:
    smol_rag: object
    session_manager: SessionManager
    workspace: WorkspaceContext
    transport: Transport = "direct"
    token_issuer_url: Optional[str] = None
    gateway_url: Optional[str] = None
    agent_configs: Optional[Dict[str, AgentConfig]] = None
    enable_subagents: bool = False
    llm: object = None

    @property
    def memory_docs_dir(self) -> str:
        return self.workspace.paths.memory_docs_dir

    @property
    def llm_db_path(self) -> str:
        return self.workspace.paths.sqlite_db_path


def configure_memory_hooks(env: RuntimeEnvironment) -> tuple[Callable[[HookRunner], None], ...]:
    if not env.smol_rag:
        return ()

    def _configure(hook_runner: HookRunner):
        hook_runner.on(ON_AFTER_TOOL, _make_promote_hook(env.smol_rag))

    return (_configure,)


def resolve_capability_names(config: AgentConfig, env: RuntimeEnvironment) -> list[str]:
    if config.capabilities:
        return list(dict.fromkeys(config.capabilities))

    capability_names = list(DEFAULT_CAPABILITIES)
    if env.session_manager:
        capability_names.append(CAPABILITY_GOAL)
    if env.smol_rag is not None:
        capability_names.append(CAPABILITY_MEMORY)
    if env.agent_configs and env.session_manager:
        capability_names.append(CAPABILITY_ORCHESTRATION)
        if env.enable_subagents:
            capability_names.append(CAPABILITY_SUBAGENTS)
    return capability_names


def memory_enabled_for_config(
    config: AgentConfig,
    env: RuntimeEnvironment,
    capability_names: Optional[Sequence[str]] = None,
) -> bool:
    names = list(capability_names) if capability_names is not None else resolve_capability_names(config, env)
    return env.smol_rag is not None and CAPABILITY_MEMORY in names


def resolve_agent_smol_rag(
    config: AgentConfig,
    env: RuntimeEnvironment,
    capability_names: Optional[Sequence[str]] = None,
):
    if not memory_enabled_for_config(config, env, capability_names=capability_names):
        return None
    return env.smol_rag


def resolve_hook_runner_configurers(
    config: AgentConfig,
    env: RuntimeEnvironment,
    capability_names: Optional[Sequence[str]] = None,
) -> tuple[Callable[[HookRunner], None], ...]:
    if not memory_enabled_for_config(config, env, capability_names=capability_names):
        return ()
    return configure_memory_hooks(env)


def build_context_builder_factory(env: RuntimeEnvironment):
    def _build(config: AgentConfig) -> ContextBuilder:
        skills_paths = [f"{PROJECT_ROOT}/skills/{skill}" for skill in config.skills]
        instruction_paths = _instruction_paths_for_workspace(env.workspace)
        agent_smol_rag = resolve_agent_smol_rag(config, env)
        if agent_smol_rag is not None:
            return ContextAssembler(
                smol_rag=agent_smol_rag,
                token_budget=config.context_budget,
                bootstrap_path=config.bootstrap_path,
                persona=config.persona,
                shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
                skills_paths=skills_paths,
                instruction_paths=instruction_paths,
            )
        return ContextBuilder(
            bootstrap_path=config.bootstrap_path,
            persona=config.persona,
            shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
            skills_paths=skills_paths,
            instruction_paths=instruction_paths,
        )

    return _build


def build_master_registry(
    env: RuntimeEnvironment,
    capability_names: Optional[Sequence[str]] = None,
):
    return build_tool_registry(
        smol_rag=env.smol_rag,
        workspace=env.workspace,
        llm=env.llm,
        transport=env.transport,
        token_issuer_url=env.token_issuer_url,
        gateway_url=env.gateway_url,
        agent_configs=env.agent_configs,
        session_manager=env.session_manager,
        capability_names=list(capability_names) if capability_names is not None else None,
        enable_subagents=env.enable_subagents,
    )


def _validate_requested_tools(config: AgentConfig, registry, env: RuntimeEnvironment) -> None:
    available = registry.tool_names()
    missing = sorted(set(config.tools) - available)
    if missing:
        names = ", ".join(missing)
        raise ValueError(
            f"Agent '{config.name}' requests tools unavailable for transport '{env.transport}': {names}."
        )


def build_configured_agent(
    config: AgentConfig,
    env: RuntimeEnvironment,
    session_key_prefix: str = "default",
    session_key: Optional[str] = None,
    hook_runner: Optional[HookRunner] = None,
    child_loop_registrar=None,
    model_override: Optional[str] = None,
):
    if model_override:
        config = replace(config, model=model_override)

    capability_names = resolve_capability_names(config, env)
    agent_smol_rag = resolve_agent_smol_rag(config, env, capability_names=capability_names)
    registry = build_master_registry(env, capability_names=capability_names)
    _validate_requested_tools(config, registry, env)
    context_builder_factory = build_context_builder_factory(env)
    context_builder = context_builder_factory(config)
    hook_runner_configurers = resolve_hook_runner_configurers(
        config,
        env,
        capability_names=capability_names,
    )
    llm_factory_kwargs = {"db_path": env.llm_db_path}
    registry_factory = lambda agent_config: build_master_registry(
        env,
        capability_names=resolve_capability_names(agent_config, env),
    )

    return build_agent_loop(
        config=config,
        master_registry=registry,
        smol_rag=agent_smol_rag,
        workspace=env.workspace,
        session_manager=env.session_manager,
        session_key_prefix=session_key_prefix,
        session_key=session_key,
        hook_runner=hook_runner,
        child_loop_registrar=child_loop_registrar,
        context_builder=context_builder,
        context_builder_factory=context_builder_factory,
        registry_factory=registry_factory,
        hook_runner_configurers=hook_runner_configurers,
        child_smol_rag_resolver=lambda agent_config: resolve_agent_smol_rag(agent_config, env),
        child_hook_runner_configurers_resolver=lambda agent_config: resolve_hook_runner_configurers(agent_config, env),
        llm_factory_kwargs=llm_factory_kwargs,
    )
