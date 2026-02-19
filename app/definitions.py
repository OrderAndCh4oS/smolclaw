import os

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
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
TEST_SET_DIR = os.path.join(PROJECT_ROOT, "evaluation", "test_sets")

SOURCE_TO_DOC_ID_KV_PATH = os.path.join(DATA_DIR, "source_to_doc_id_map.json")
DOC_ID_TO_SOURCE_KV_PATH = os.path.join(DATA_DIR, "doc_id_to_source_map.json")
DOC_ID_TO_EXCERPT_KV_PATH = os.path.join(DATA_DIR, "doc_id_to_excerpt_ids.json")
DOC_ID_TO_ENTITY_IDS_KV_PATH = os.path.join(DATA_DIR, "doc_id_to_entity_ids.json")
DOC_ID_TO_RELATIONSHIP_IDS_KV_PATH = os.path.join(DATA_DIR, "doc_id_to_relationship_ids.json")
ENTITY_ID_TO_DOC_IDS_KV_PATH = os.path.join(DATA_DIR, "entity_id_to_doc_ids.json")
RELATIONSHIP_ID_TO_DOC_IDS_KV_PATH = os.path.join(DATA_DIR, "relationship_id_to_doc_ids.json")

EXCERPT_KV_PATH = os.path.join(DATA_DIR, "excerpt_db.json")
EMBEDDINGS_DB = os.path.join(DATA_DIR, "embeddings_db.json")
ENTITIES_DB = os.path.join(DATA_DIR, "entities_db.json")
RELATIONSHIPS_DB = os.path.join(DATA_DIR, "relationships_db.json")

KG_DB = os.path.join(DATA_DIR, "kg_db.graphml")

EVALUATION_DATA_SET = os.path.join(TEST_SET_DIR, "evaluation_data_set.json")

QUERY_CACHE_KV_PATH = os.path.join(CACHE_DIR, "query_cache.json")
EMBEDDING_CACHE_KV_PATH = os.path.join(CACHE_DIR, "embedding_cache.json")

KG_SEP = ":|:"
TUPLE_SEP = "<|>"
REC_SEP = "+|+"
COMPLETE_TAG = "<|COMPLETE|>"

# SmolClaw agent settings
VAULT_DIR = os.path.join(PROJECT_ROOT, "vault")
SESSIONS_DIR = os.path.join(PROJECT_ROOT, "sessions")
MEMORY_DOCS_DIR = os.path.join(VAULT_DIR, "memory")
WORKSPACE_DIR = os.getenv('SMOLCLAW_WORKSPACE', os.path.expanduser('~'))
AGENT_MODEL = os.getenv('AGENT_MODEL', 'gpt-4.1-mini')
MAX_ITERATIONS = int(os.getenv('MAX_ITERATIONS', '15'))
MEMORY_WINDOW = int(os.getenv('MEMORY_WINDOW', '20'))
