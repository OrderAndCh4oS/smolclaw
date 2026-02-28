import os

COMPLETION_MODEL = os.getenv('COMPLETION_MODEL', 'gpt-4.1-mini')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small')

# app/ package dir (for legacy references only)
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Project root — everything hangs off this
PROJECT_ROOT = os.path.dirname(ROOT_DIR)

# Core data stores at project root
DATA_DIR = os.path.join(PROJECT_ROOT, "store")
CACHE_DIR = os.path.join(PROJECT_ROOT, "cache")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
INPUT_DOCS_DIR = os.path.join(PROJECT_ROOT, "input_docs")

SQLITE_DB_PATH = os.path.join(DATA_DIR, "smolclaw.db")

EMBEDDINGS_DB = os.path.join(DATA_DIR, "embeddings_db.json")
ENTITIES_DB = os.path.join(DATA_DIR, "entities_db.json")
RELATIONSHIPS_DB = os.path.join(DATA_DIR, "relationships_db.json")

KG_DB = os.path.join(DATA_DIR, "kg_db.graphml")

KG_SEP = ":|:"
TUPLE_SEP = "<|>"
REC_SEP = "+|+"
COMPLETE_TAG = "<|COMPLETE|>"

# SmolClaw agent settings
SESSIONS_DIR = os.path.join(PROJECT_ROOT, "sessions")
MEMORY_DOCS_DIR = os.path.join(PROJECT_ROOT, "memory")
WORKSPACE_DIR = os.getenv('SMOLCLAW_WORKSPACE', os.path.expanduser('~'))
AGENT_MODEL = os.getenv('AGENT_MODEL', 'gpt-4.1-mini')
MAX_ITERATIONS = int(os.getenv('MAX_ITERATIONS', '15'))
MEMORY_WINDOW = int(os.getenv('MEMORY_WINDOW', '20'))
