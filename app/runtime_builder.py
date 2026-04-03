from dataclasses import dataclass
from typing import Dict, Optional

from app.agent_config import AgentConfig
from app.runtime import RuntimeEnvironment
from app.runtime_capabilities import Transport
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
) -> RuntimeServices:
    workspace = (
        workspace_root
        if isinstance(workspace_root, WorkspaceContext)
        else WorkspaceContext.from_root(workspace_root)
    ).ensure_dirs()

    rag = smol_rag or create_smol_rag(
        db_path=workspace.paths.sqlite_db_path,
        graph_path=workspace.paths.kg_db_path,
        input_docs_dir=workspace.paths.research_dir,
        log_dir=workspace.paths.log_dir,
    )
    sessions = session_manager or SessionManager(workspace.paths.sessions_dir)
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
    )
    return RuntimeServices(
        workspace=workspace,
        smol_rag=rag,
        session_manager=sessions,
        env=env,
    )
