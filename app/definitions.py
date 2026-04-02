import os
from dataclasses import dataclass

COMPLETION_MODEL = os.getenv('COMPLETION_MODEL', 'gpt-5.4-mini')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small')

# app/ package dir
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Project root — everything hangs off this
PROJECT_ROOT = os.path.dirname(ROOT_DIR)

DEFAULT_WORKSPACE_ROOT = os.getenv("SMOLCLAW_WORKSPACE", os.path.join(PROJECT_ROOT, "workspace"))


@dataclass(frozen=True)
class WorkspacePaths:
    root_dir: str
    data_dir: str
    sqlite_db_path: str
    kg_db_path: str
    sessions_dir: str
    memory_docs_dir: str
    log_dir: str
    cache_dir: str
    research_dir: str
    input_docs_dir: str
    prompt_history_path: str


def resolve_workspace_root(workspace_root: str | None = None) -> str:
    return os.path.abspath(os.path.expanduser(workspace_root or DEFAULT_WORKSPACE_ROOT))


def build_workspace_paths(workspace_root: str | None = None) -> WorkspacePaths:
    root_dir = resolve_workspace_root(workspace_root)
    data_dir = os.path.join(root_dir, "store")
    sessions_dir = os.path.join(data_dir, "sessions")
    research_dir = os.path.join(root_dir, "research")
    return WorkspacePaths(
        root_dir=root_dir,
        data_dir=data_dir,
        sqlite_db_path=os.path.join(data_dir, "smolclaw.db"),
        kg_db_path=os.path.join(data_dir, "kg_db.graphml"),
        sessions_dir=sessions_dir,
        memory_docs_dir=os.path.join(root_dir, "memory"),
        log_dir=os.path.join(data_dir, "logs"),
        cache_dir=os.path.join(data_dir, "cache"),
        research_dir=research_dir,
        input_docs_dir=research_dir,
        prompt_history_path=os.path.join(sessions_dir, "prompt_history.txt"),
    )


def ensure_workspace_dirs(paths: WorkspacePaths) -> WorkspacePaths:
    for dir_path in (
        paths.root_dir,
        paths.data_dir,
        paths.sessions_dir,
        paths.memory_docs_dir,
        paths.log_dir,
        paths.cache_dir,
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
AGENT_MODEL = os.getenv('AGENT_MODEL', 'gpt-4.1-mini')
MAX_ITERATIONS = int(os.getenv('MAX_ITERATIONS', '15'))
MEMORY_WINDOW = int(os.getenv('MEMORY_WINDOW', '20'))
