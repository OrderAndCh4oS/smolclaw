from dataclasses import dataclass, replace
from typing import Callable, Dict, Optional, Sequence

from app.agent_config import AgentConfig
from app.agent_factory import _make_promote_hook, build_agent_loop
from app.context_assembly import ContextAssembler
from app.context_builder import ContextBuilder
from app.definitions import MEMORY_DOCS_DIR, PROJECT_ROOT
from app.hooks import HookRunner, ON_AFTER_TOOL
from app.session import SessionManager
from app.tools.factory import build_tool_registry

_SHARED_BOOTSTRAP_PATH = f"{PROJECT_ROOT}/AGENT.md"


@dataclass(frozen=True)
class RuntimeEnvironment:
    smol_rag: object
    session_manager: SessionManager
    memory_docs_dir: str = MEMORY_DOCS_DIR
    workspace: Optional[str] = None
    transport: str = "direct"
    token_issuer_url: Optional[str] = None
    gateway_url: Optional[str] = None
    agent_configs: Optional[Dict[str, AgentConfig]] = None
    enable_subagents: bool = False
    llm: object = None

def configure_memory_hooks(env: RuntimeEnvironment) -> tuple[Callable[[HookRunner], None], ...]:
    if not env.smol_rag:
        return ()

    def _configure(hook_runner: HookRunner):
        hook_runner.on(ON_AFTER_TOOL, _make_promote_hook(env.smol_rag))

    return (_configure,)


def resolve_module_names(config: AgentConfig, env: RuntimeEnvironment) -> list[str]:
    if config.modules:
        return list(config.modules)

    module_names = [f"transport.{env.transport}"]
    if env.smol_rag is not None:
        module_names.append("memory")
    if env.agent_configs and env.session_manager:
        module_names.append("orchestration")
        if env.enable_subagents:
            module_names.append("subagents")
    module_names.append("tool_discovery")
    return module_names


def memory_enabled_for_config(
    config: AgentConfig,
    env: RuntimeEnvironment,
    module_names: Optional[Sequence[str]] = None,
) -> bool:
    names = list(module_names) if module_names is not None else resolve_module_names(config, env)
    return env.smol_rag is not None and "memory" in names


def resolve_agent_smol_rag(
    config: AgentConfig,
    env: RuntimeEnvironment,
    module_names: Optional[Sequence[str]] = None,
):
    if not memory_enabled_for_config(config, env, module_names=module_names):
        return None
    return env.smol_rag


def resolve_hook_runner_configurers(
    config: AgentConfig,
    env: RuntimeEnvironment,
    module_names: Optional[Sequence[str]] = None,
) -> tuple[Callable[[HookRunner], None], ...]:
    if not memory_enabled_for_config(config, env, module_names=module_names):
        return ()
    return configure_memory_hooks(env)


def build_context_builder_factory(env: RuntimeEnvironment):
    def _build(config: AgentConfig) -> ContextBuilder:
        skills_paths = [f"{PROJECT_ROOT}/skills/{skill}" for skill in config.skills]
        agent_smol_rag = resolve_agent_smol_rag(config, env)
        if agent_smol_rag is not None:
            return ContextAssembler(
                smol_rag=agent_smol_rag,
                token_budget=config.context_budget,
                bootstrap_path=config.bootstrap_path,
                persona=config.persona,
                shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
                skills_paths=skills_paths,
            )
        return ContextBuilder(
            bootstrap_path=config.bootstrap_path,
            persona=config.persona,
            shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
            skills_paths=skills_paths,
        )

    return _build


def build_master_registry(
    env: RuntimeEnvironment,
    module_names: Optional[Sequence[str]] = None,
):
    return build_tool_registry(
        smol_rag=env.smol_rag,
        memory_docs_dir=env.memory_docs_dir,
        workspace=env.workspace,
        llm=env.llm,
        mode=env.transport,
        token_issuer_url=env.token_issuer_url,
        gateway_url=env.gateway_url,
        agent_configs=env.agent_configs,
        session_manager=env.session_manager,
        module_names=list(module_names) if module_names is not None else None,
        enable_subagents=env.enable_subagents,
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

    module_names = resolve_module_names(config, env)
    agent_smol_rag = resolve_agent_smol_rag(config, env, module_names=module_names)
    registry = build_master_registry(env, module_names=module_names)
    context_builder_factory = build_context_builder_factory(env)
    context_builder = context_builder_factory(config)
    hook_runner_configurers = resolve_hook_runner_configurers(
        config,
        env,
        module_names=module_names,
    )
    registry_factory = lambda agent_config: build_master_registry(
        env,
        module_names=resolve_module_names(agent_config, env),
    )

    return build_agent_loop(
        config=config,
        master_registry=registry,
        smol_rag=agent_smol_rag,
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
    )
