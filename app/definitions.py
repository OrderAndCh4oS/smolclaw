import os

COMPLETION_MODEL = os.getenv('COMPLETION_MODEL', 'gpt-5.4-mini')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small')

# app/ package dir
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Project root — everything hangs off this
PROJECT_ROOT = os.path.dirname(ROOT_DIR)

# Everything lives under store/
DATA_DIR = os.path.join(PROJECT_ROOT, "store")

SQLITE_DB_PATH = os.path.join(DATA_DIR, "smolclaw.db")
EMBEDDINGS_TABLE = "embeddings"
ENTITIES_TABLE = "entities"
RELATIONSHIPS_TABLE = "relationships"
KG_DB = os.path.join(DATA_DIR, "kg_db.graphml")

KG_SEP = ":|:"
TUPLE_SEP = "<|>"
REC_SEP = "+|+"
COMPLETE_TAG = "<|COMPLETE|>"

SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
MEMORY_DOCS_DIR = os.path.join(DATA_DIR, "memory")
LOG_DIR = os.path.join(DATA_DIR, "logs")
INPUT_DOCS_DIR = os.path.join(DATA_DIR, "input_docs")
WORKSPACE_DIR = os.getenv('SMOLCLAW_WORKSPACE', os.path.expanduser('~'))
AGENT_MODEL = os.getenv('AGENT_MODEL', 'gpt-4.1-mini')
MAX_ITERATIONS = int(os.getenv('MAX_ITERATIONS', '15'))
MEMORY_WINDOW = int(os.getenv('MEMORY_WINDOW', '20'))
