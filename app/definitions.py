import os
from dataclasses import dataclass

from app.model_defaults import (
    DEFAULT_AGENT_MODEL,
    DEFAULT_APP_COMPLETION_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MEMORY_EXTRACT_MODEL,
    DEFAULT_MEMORY_QUERY_MODEL,
)

# OpenAI/Codex completion default kept for quick rollback:
# COMPLETION_MODEL = os.getenv('COMPLETION_MODEL', DEFAULT_OPENAI_CHAT_MODEL)
COMPLETION_MODEL = os.getenv('COMPLETION_MODEL', DEFAULT_APP_COMPLETION_MODEL)
# OpenAI/Codex memory defaults kept for quick rollback:
# MEMORY_EXTRACT_MODEL = os.getenv('MEMORY_EXTRACT_MODEL', DEFAULT_OPENAI_MEMORY_EXTRACT_MODEL)
# MEMORY_QUERY_MODEL = os.getenv('MEMORY_QUERY_MODEL', DEFAULT_OPENAI_MEMORY_QUERY_MODEL)
# EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', DEFAULT_OPENAI_EMBEDDING_MODEL)
MEMORY_EXTRACT_MODEL = os.getenv('MEMORY_EXTRACT_MODEL', DEFAULT_MEMORY_EXTRACT_MODEL)
MEMORY_QUERY_MODEL = os.getenv('MEMORY_QUERY_MODEL', DEFAULT_MEMORY_QUERY_MODEL)
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', DEFAULT_EMBEDDING_MODEL)

# app/ package dir
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Project root — everything hangs off this
PROJECT_ROOT = os.path.dirname(ROOT_DIR)

DEFAULT_WORKSPACE_ROOT = os.getenv("SMOLCLAW_WORKSPACE") or os.getcwd()


@dataclass(frozen=True)
class WorkspacePaths:
    root_dir: str
    state_root_dir: str
    data_dir: str
    sqlite_db_path: str
    kg_db_path: str
    sessions_dir: str
    checkpoints_dir: str
    traces_dir: str
    ledgers_dir: str
    approvals_dir: str
    evals_dir: str
    memory_docs_dir: str
    log_dir: str
    cache_dir: str
    work_loop_dir: str
    research_dir: str
    input_docs_dir: str
    prompt_history_path: str


def resolve_workspace_root(workspace_root: str | None = None) -> str:
    return os.path.abspath(os.path.expanduser(workspace_root or DEFAULT_WORKSPACE_ROOT))


def build_workspace_paths(
    workspace_root: str | None = None,
    *,
    state_root: str | None = None,
) -> WorkspacePaths:
    root_dir = resolve_workspace_root(workspace_root)
    state_root_dir = (
        resolve_workspace_root(state_root)
        if state_root is not None
        else os.path.join(root_dir, ".smolclaw")
    )
    data_dir = os.path.join(state_root_dir, "stores")
    sessions_dir = os.path.join(data_dir, "sessions")
    research_dir = os.path.join(state_root_dir, "research")
    work_loop_dir = os.path.join(state_root_dir, "work-loop")
    return WorkspacePaths(
        root_dir=root_dir,
        state_root_dir=state_root_dir,
        data_dir=data_dir,
        sqlite_db_path=os.path.join(data_dir, "smolclaw.db"),
        kg_db_path=os.path.join(data_dir, "kg_db.graphml"),
        sessions_dir=sessions_dir,
        checkpoints_dir=os.path.join(data_dir, "checkpoints"),
        traces_dir=os.path.join(data_dir, "traces"),
        ledgers_dir=os.path.join(data_dir, "ledgers"),
        approvals_dir=os.path.join(data_dir, "approvals"),
        evals_dir=os.path.join(data_dir, "evals"),
        memory_docs_dir=os.path.join(state_root_dir, "memory"),
        log_dir=os.path.join(data_dir, "logs"),
        cache_dir=os.path.join(data_dir, "cache"),
        work_loop_dir=work_loop_dir,
        research_dir=research_dir,
        input_docs_dir=research_dir,
        prompt_history_path=os.path.join(sessions_dir, "prompt_history.txt"),
    )


def ensure_workspace_dirs(paths: WorkspacePaths) -> WorkspacePaths:
    for dir_path in (
        paths.root_dir,
        paths.state_root_dir,
        paths.data_dir,
        paths.sessions_dir,
        paths.checkpoints_dir,
        paths.traces_dir,
        paths.ledgers_dir,
        paths.approvals_dir,
        paths.evals_dir,
        paths.memory_docs_dir,
        paths.log_dir,
        paths.cache_dir,
        paths.work_loop_dir,
        paths.research_dir,
    ):
        os.makedirs(dir_path, exist_ok=True)
    return paths


_DEFAULT_WORKSPACE_PATHS = build_workspace_paths()

DATA_DIR = _DEFAULT_WORKSPACE_PATHS.data_dir

SQLITE_DB_PATH = _DEFAULT_WORKSPACE_PATHS.sqlite_db_path
EMBEDDINGS_TABLE = "embeddings"
ENTITIES_TABLE = "entities"
RELATIONSHIPS_TABLE = "relationships"
KG_DB = _DEFAULT_WORKSPACE_PATHS.kg_db_path

KG_SEP = ":|:"
TUPLE_SEP = "<|>"
REC_SEP = "+|+"
COMPLETE_TAG = "<|COMPLETE|>"

SESSIONS_DIR = _DEFAULT_WORKSPACE_PATHS.sessions_dir
MEMORY_DOCS_DIR = _DEFAULT_WORKSPACE_PATHS.memory_docs_dir
LOG_DIR = _DEFAULT_WORKSPACE_PATHS.log_dir
RESEARCH_DOCS_DIR = _DEFAULT_WORKSPACE_PATHS.research_dir
INPUT_DOCS_DIR = _DEFAULT_WORKSPACE_PATHS.input_docs_dir
WORKSPACE_DIR = _DEFAULT_WORKSPACE_PATHS.root_dir
# OpenAI/Codex agent default kept for quick rollback:
# AGENT_MODEL = os.getenv('AGENT_MODEL', DEFAULT_OPENAI_CHAT_MODEL)
AGENT_MODEL = os.getenv('AGENT_MODEL', DEFAULT_AGENT_MODEL)
MAX_ITERATIONS = int(os.getenv('MAX_ITERATIONS', '15'))
MEMORY_WINDOW = int(os.getenv('MEMORY_WINDOW', '20'))
