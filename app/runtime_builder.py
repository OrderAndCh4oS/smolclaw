from dataclasses import dataclass
from typing import Dict, Optional

from app.agent_config import AgentConfig
from app import diagnostics
from app.command_adapters import build_command_adapter_bundle
from app.model_registry import MODEL_REGISTRY
from app.model_settings import ModelSelection, RuntimeModelSettings
from app.runtime import RuntimeEnvironment
from app.runtime_capabilities import Transport
from app.runtime_config import RuntimeAdapterConfig, load_runtime_config
from app.session import SessionManager
from app.smol_rag import SmolRag, create_smol_rag
from app.workspace import WorkspaceContext


@dataclass(frozen=True)
class RuntimeServices:
    workspace: WorkspaceContext
    smol_rag: SmolRag | None
    session_manager: SessionManager
    env: RuntimeEnvironment


def build_runtime_services(
    workspace_root: str | WorkspaceContext | None = None,
    *,
    transport: Transport = "direct",
    agent_configs: Optional[Dict[str, AgentConfig]] = None,
    enable_subagents: bool = False,
    token_issuer_url: str | None = None,
    gateway_url: str | None = None,
    llm=None,
    smol_rag: SmolRag | None = None,
    session_manager: SessionManager | None = None,
    adapter_config: RuntimeAdapterConfig | None = None,
) -> RuntimeServices:
    workspace = (
        workspace_root
        if isinstance(workspace_root, WorkspaceContext)
        else WorkspaceContext.from_root(workspace_root)
    ).ensure_dirs()
    diagnostics.configure(workspace.paths.log_dir)
    adapter_config = adapter_config or load_runtime_config(workspace)
    command_adapters = build_command_adapter_bundle(adapter_config.command)

    rag = smol_rag or create_smol_rag(
        db_path=workspace.paths.sqlite_db_path,
        graph_path=workspace.paths.kg_db_path,
        input_docs_dir=workspace.paths.research_dir,
        log_dir=workspace.paths.log_dir,
        memory_extract_model=adapter_config.llm.memory_extract.model,
        memory_query_model=adapter_config.llm.memory_query.model,
        embedding_model=adapter_config.llm.embeddings.model,
        llm_provider=adapter_config.llm.memory_extract.provider,
        embedding_provider=adapter_config.llm.embeddings.provider,
    )
    sessions = session_manager or SessionManager(workspace.paths.sessions_dir)
    subagent_model = adapter_config.llm.subagents.model
    model_settings = RuntimeModelSettings(
        subagent_selection=(
            ModelSelection(subagent_model, MODEL_REGISTRY.default_effort(subagent_model))
            if subagent_model else None
        ),
    )
    env = RuntimeEnvironment(
        smol_rag=rag,
        session_manager=sessions,
        workspace=workspace,
        transport=transport,
        token_issuer_url=token_issuer_url,
        gateway_url=gateway_url,
        agent_configs=agent_configs,
        enable_subagents=enable_subagents,
        llm=llm,
        command_runner=command_adapters.infrastructure_runner,
        agent_command_runner=command_adapters.agent_runner,
        model_settings=model_settings,
        adapter_config=adapter_config,
    )
    return RuntimeServices(
        workspace=workspace,
        smol_rag=rag,
        session_manager=sessions,
        env=env,
    )
