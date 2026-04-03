import asyncio
from dataclasses import dataclass, field

from app.bm25_store import BM25Store
from app.graph_store import NetworkXGraphStore
from app.sqlite_store import SqliteKvStore
from app.sqlite_mapping_store import SqliteMappingStore
from app.vector_store import SqliteVectorStore


@dataclass
class StoreBundle:
    """Container for all stores used by the RAG pipeline."""
    embeddings_db: SqliteVectorStore
    entities_db: SqliteVectorStore
    relationships_db: SqliteVectorStore
    source_doc_map: SqliteMappingStore
    doc_excerpt_map: SqliteMappingStore
    doc_entity_map: SqliteMappingStore
    doc_relationship_map: SqliteMappingStore
    excerpt_kv: SqliteKvStore
    bm25_store: BM25Store
    graph: NetworkXGraphStore
    contradiction_detector: object = None
    provenance_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
