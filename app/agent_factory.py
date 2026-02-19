import os

from app.agent_config import AgentConfig
from app.agent_loop import AgentLoop
from app.context_builder import ContextBuilder
from app.llm import create_llm
from app.session import SessionManager
from app.tools.registry import ToolRegistry

_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_SHARED_BOOTSTRAP_PATH = os.path.join(_PROJECT_ROOT, "AGENT.md")


def build_agent_loop(
    config: AgentConfig,
    master_registry: ToolRegistry,
    smol_rag,
    session_manager: SessionManager,
    session_key_prefix: str = "default",
) -> AgentLoop:
    llm = create_llm(completion_model=config.model)
    filtered_registry = master_registry.filter_by_names(config.tools)
    context_builder = ContextBuilder(
        bootstrap_path=config.bootstrap_path,
        persona=config.persona,
        shared_bootstrap_path=_SHARED_BOOTSTRAP_PATH,
    )
    session_key = f"{config.name}-{session_key_prefix}"
    session = session_manager.get_or_create(session_key)
    return AgentLoop(
        llm=llm,
        tool_registry=filtered_registry,
        context_builder=context_builder,
        session=session,
        session_manager=session_manager,
        max_iterations=config.max_iterations,
        memory_window=config.memory_window,
        smol_rag=smol_rag,
    )
