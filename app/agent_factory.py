import os
from typing import Optional

from app.agent_config import AgentConfig
from app.agent_loop import AgentLoop
from app.context_builder import ContextBuilder
from app.definitions import PROJECT_ROOT
from app.llm import create_llm
from app.session import SessionManager
from app.tools.registry import ToolRegistry

_SHARED_BOOTSTRAP_PATH = os.path.join(PROJECT_ROOT, "AGENT.md")


def build_agent_loop(
    config: AgentConfig,
    master_registry: ToolRegistry,
    smol_rag,
    session_manager: SessionManager,
    session_key_prefix: str = "default",
    session_key: Optional[str] = None,
) -> AgentLoop:
    llm = create_llm(completion_model=config.model)
    filtered_registry = master_registry.filter_by_names(config.tools)

    if smol_rag:
        from app.context_assembly import ContextAssembler
        context_builder = ContextAssembler(
            smol_rag=smol_rag,
            token_budget=config.context_budget,
            bootstrap_path=config.bootstrap_path,
            persona=config.persona,
            shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
        )
    else:
        context_builder = ContextBuilder(
            bootstrap_path=config.bootstrap_path,
            persona=config.persona,
            shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
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
        reflection=config.reflection,
    )
