import inspect

from aiolimiter import AsyncLimiter

from app.bm25_store import BM25Store
from app.chunking import preserve_markdown_code_excerpts
from app.definitions import INPUT_DOCS_DIR, SQLITE_DB_PATH, EMBEDDINGS_TABLE, \
    KG_DB, ENTITIES_TABLE, RELATIONSHIPS_TABLE, MEMORY_EXTRACT_MODEL, \
    MEMORY_QUERY_MODEL, EMBEDDING_MODEL
from app.graph_store import NetworkXGraphStore
from app.sqlite_store import SqliteKvStore
from app.sqlite_mapping_store import SqliteMappingStore
from app.logger import set_logger
from app.llm import create_llm
from app.document_manager import DocumentManager
from app.ingestion import IngestionPipeline
from app.query_engine import QueryEngine
from app.store_bundle import StoreBundle
from app.vector_store import SqliteVectorStore


def default_embedding_dimensions(model: str | None) -> int:
    return 1536


class SmolRag:
    def __init__(
            self,
            excerpt_fn=None,
            llm=None,
            embeddings_db=None,
            entities_db=None,
            relationships_db=None,
            source_doc_map=None,
            doc_excerpt_map=None,
            doc_entity_map=None,
            doc_relationship_map=None,
            excerpt_kv=None,
            bm25_store=None,
            query_cache_kv=None,
            embedding_cache_kv=None,
            graph_db=None,
            graph_path=None,
            db_path=None,
            dimensions=None,
            excerpt_size=2000,
            overlap=200,
            ingest_concurrency=4,
            contradiction_detector=None,
            input_docs_dir=None,
            log_dir=None,
            memory_extract_model=None,
            memory_query_model=None,
    ):
        _db = db_path or SQLITE_DB_PATH
        set_logger("smolclaw-rag.log", log_dir=log_dir)
        self.llm_limiter = AsyncLimiter(max_rate=100, time_period=1)

        self.excerpt_fn = excerpt_fn or preserve_markdown_code_excerpts
        self.excerpt_size = excerpt_size
        self.overlap = overlap
        self.ingest_concurrency = max(1, ingest_concurrency)
        self.input_docs_dir = input_docs_dir or INPUT_DOCS_DIR
        self.memory_extract_model = memory_extract_model or MEMORY_EXTRACT_MODEL
        self.memory_query_model = memory_query_model or MEMORY_QUERY_MODEL

        self.llm = llm or create_llm(
            self.memory_extract_model,
            EMBEDDING_MODEL,
            query_cache_kv=query_cache_kv,
            embedding_cache_kv=embedding_cache_kv,
            db_path=_db,
        )

        _dimensions = dimensions or default_embedding_dimensions(EMBEDDING_MODEL)
        self.stores = StoreBundle(
            embeddings_db=embeddings_db or SqliteVectorStore(
                _db, dimensions=_dimensions, table=EMBEDDINGS_TABLE, embedding_model=EMBEDDING_MODEL
            ),
            entities_db=entities_db or SqliteVectorStore(
                _db, dimensions=_dimensions, table=ENTITIES_TABLE, embedding_model=EMBEDDING_MODEL
            ),
            relationships_db=relationships_db or SqliteVectorStore(
                _db, dimensions=_dimensions, table=RELATIONSHIPS_TABLE, embedding_model=EMBEDDING_MODEL
            ),
            source_doc_map=source_doc_map or SqliteMappingStore(_db, "source_doc_map", "source", "doc_id"),
            doc_excerpt_map=doc_excerpt_map or SqliteMappingStore(_db, "doc_excerpt_map", "doc_id", "excerpt_id"),
            doc_entity_map=doc_entity_map or SqliteMappingStore(_db, "doc_entity_map", "doc_id", "entity_id"),
            doc_relationship_map=doc_relationship_map or SqliteMappingStore(_db, "doc_relationship_map", "doc_id", "relationship_id"),
            excerpt_kv=excerpt_kv or SqliteKvStore(_db, "excerpts"),
            bm25_store=bm25_store or BM25Store(_db, "bm25_index"),
            graph=graph_db or NetworkXGraphStore(graph_path or KG_DB),
            contradiction_detector=contradiction_detector,
        )

        self.query_engine = QueryEngine(
            stores=self.stores,
            llm_provider=self,
        )
        self.doc_manager = DocumentManager(stores=self.stores)
        self.ingestion = IngestionPipeline(
            stores=self.stores,
            llm_provider=self,
            doc_manager=self.doc_manager,
            excerpt_fn=self.excerpt_fn,
            excerpt_size=self.excerpt_size,
            overlap=self.overlap,
            ingest_concurrency=self.ingest_concurrency,
            input_docs_dir=self.input_docs_dir,
        )

    # --- Store property accessors for backward compatibility ---
    @property
    def embeddings_db(self):
        return self.stores.embeddings_db

    @property
    def entities_db(self):
        return self.stores.entities_db

    @property
    def relationships_db(self):
        return self.stores.relationships_db

    @property
    def source_doc_map(self):
        return self.stores.source_doc_map

    @property
    def doc_excerpt_map(self):
        return self.stores.doc_excerpt_map

    @property
    def doc_entity_map(self):
        return self.stores.doc_entity_map

    @property
    def doc_relationship_map(self):
        return self.stores.doc_relationship_map

    @property
    def excerpt_kv(self):
        return self.stores.excerpt_kv

    @property
    def bm25_store(self):
        return self.stores.bm25_store

    @property
    def graph(self):
        return self.stores.graph

    @property
    def contradiction_detector(self):
        return self.stores.contradiction_detector

    @contradiction_detector.setter
    def contradiction_detector(self, value):
        self.stores.contradiction_detector = value

    @property
    def _provenance_lock(self):
        return self.stores.provenance_lock

    async def rate_limited_get_completion(self, *args, **kwargs):
        """Backward-compatible completion helper; defaults to extraction model."""
        return await self.rate_limited_get_extract_completion(*args, **kwargs)

    async def rate_limited_get_extract_completion(self, *args, **kwargs):
        kwargs.setdefault("model", self.memory_extract_model)
        async with self.llm_limiter:
            return await self.llm.get_completion(*args, **kwargs)

    async def rate_limited_get_query_completion(self, *args, **kwargs):
        kwargs.setdefault("model", self.memory_query_model)
        async with self.llm_limiter:
            return await self.llm.get_completion(*args, **kwargs)

    async def rate_limited_get_embedding(self, *args, **kwargs):
        async with self.llm_limiter:
            return await self.llm.get_embedding(*args, **kwargs)

    async def rate_limited_get_embeddings(self, *args, **kwargs):
        async with self.llm_limiter:
            return await self.llm.get_embeddings(*args, **kwargs)

    # --- Document management delegations ---
    async def remove_document_by_id(self, doc_id, persist=True):
        return await self.doc_manager.remove_document_by_id(doc_id, persist=persist)

    async def remove_document_by_source(self, source_id: str):
        return await self.doc_manager.remove_document_by_source(source_id)

    async def _cleanup_entity_contributions(self, doc_id, doc_excerpt_ids):
        return await self.doc_manager._cleanup_entity_contributions(doc_id, doc_excerpt_ids)

    async def _cleanup_relationship_contributions(self, doc_id, doc_excerpt_ids):
        return await self.doc_manager._cleanup_relationship_contributions(doc_id, doc_excerpt_ids)

    # --- Ingestion delegations ---
    async def ingest_text(self, content: str, source_id: str = None, save: bool = True, source: str = "extraction"):
        return await self.ingestion.ingest_text(content, source_id=source_id, save=save, source=source)

    async def import_documents(self):
        return await self.ingestion.import_documents()

    async def _save_stores(self):
        return await self.ingestion._save_stores()

    async def _track_kg_provenance(self, doc_id, entity_ids, relationship_ids):
        return await self.ingestion._track_kg_provenance(doc_id, entity_ids, relationship_ids)

    @staticmethod
    def _extract_frontmatter(content: str) -> dict:
        return IngestionPipeline._extract_frontmatter(content)

    # --- Query method delegations ---
    async def query(self, text):
        return await self.query_engine.query(text)

    async def hybrid_kg_query(self, text):
        return await self.query_engine.hybrid_kg_query(text)

    async def local_kg_query(self, text):
        return await self.query_engine.local_kg_query(text)

    async def global_kg_query(self, text):
        return await self.query_engine.global_kg_query(text)

    async def bm25_query(self, text: str, top_k: int = 10) -> list[dict]:
        return await self.query_engine.bm25_query(text, top_k=top_k)

    async def mix_query(self, text, memory_type=None, include_bm25=False, return_metadata=False):
        return await self.query_engine.mix_query(text, memory_type=memory_type, include_bm25=include_bm25, return_metadata=return_metadata)

    # Backward-compatible aliases for internal dataset methods
    async def _get_high_level_dataset(self, keyword_data):
        return await self.query_engine.get_high_level_dataset(keyword_data)

    async def _get_low_level_dataset(self, keyword_data):
        return await self.query_engine.get_low_level_dataset(keyword_data)

    @staticmethod
    def _attach_excerpt_id(excerpt_id, excerpt_data):
        return QueryEngine._attach_excerpt_id(excerpt_id, excerpt_data)

    @staticmethod
    def _filter_excerpts_by_memory_type(excerpts, memory_type):
        return QueryEngine._filter_excerpts_by_memory_type(excerpts, memory_type)

    @staticmethod
    def _collect_excerpt_ids(excerpts):
        return QueryEngine._collect_excerpt_ids(excerpts)

    def _get_entities_from_relationships(self, kg_dataset):
        return self.query_engine._get_entities_from_relationships(kg_dataset)

    def _get_relationships_from_entities(self, kg_dataset):
        return self.query_engine._get_relationships_from_entities(kg_dataset)

    # --- Public accessor methods (replace direct store access by consumers) ---
    async def vector_search(self, embedding, top_k=5, better_than_threshold=0.02):
        return await self.stores.embeddings_db.query(query=embedding, top_k=top_k, better_than_threshold=better_than_threshold)

    def _current_excerpt(self, excerpt_data):
        attached = QueryEngine._attach_excerpt_id("", excerpt_data)
        if attached is None:
            return None
        embedding_model = getattr(self.stores.embeddings_db, "embedding_model", None)
        embedding_dimensions = getattr(self.stores.embeddings_db, "dimensions", None)
        if not QueryEngine._excerpt_matches_embedding_model(attached, embedding_model, embedding_dimensions):
            return None
        attached.pop("excerpt_id", None)
        return attached

    async def get_excerpt(self, excerpt_id):
        return self._current_excerpt(await self.stores.excerpt_kv.get_by_key(excerpt_id))

    async def get_all_excerpts(self):
        excerpts = await self.stores.excerpt_kv.get_all()
        return {
            excerpt_id: current
            for excerpt_id, data in excerpts.items()
            if (current := self._current_excerpt(data)) is not None
        }

    async def update_excerpt(self, excerpt_id, data):
        return await self.stores.excerpt_kv.add(excerpt_id, data)

    def get_graph_node(self, name):
        return self.stores.graph.get_node(name)

    def get_graph_edges(self, name):
        return self.stores.graph.get_node_edges(name)

    def get_graph_edge(self, edge):
        return self.stores.graph.get_edge(edge)

    async def add_graph_node(self, name, **kwargs):
        return await self.stores.graph.async_add_node(name, **kwargs)

    async def add_graph_edge(self, src, tgt, **kwargs):
        return await self.stores.graph.async_add_edge(src, tgt, **kwargs)

    async def get_pending_contradiction_count(self):
        if self.contradiction_detector:
            return await self.contradiction_detector.get_count("pending")
        return 0

    async def get_high_level_dataset(self, keyword_data):
        return await self.query_engine.get_high_level_dataset(keyword_data)

    async def get_low_level_dataset(self, keyword_data):
        return await self.query_engine.get_low_level_dataset(keyword_data)

    async def close(self):
        """Close all SQLite-backed stores and caches used by this SmolRag instance."""
        seen = set()

        async def _close_resource(resource):
            if resource is None or id(resource) in seen:
                return
            seen.add(id(resource))
            close_fn = getattr(resource, "close", None)
            if not callable(close_fn):
                return
            result = close_fn()
            if inspect.isawaitable(result):
                await result

        for resource in (
            self.embeddings_db,
            self.entities_db,
            self.relationships_db,
            self.source_doc_map,
            self.doc_excerpt_map,
            self.doc_entity_map,
            self.doc_relationship_map,
            self.excerpt_kv,
            self.bm25_store,
            self.llm,
            getattr(self.contradiction_detector, "store", None),
        ):
            await _close_resource(resource)


def create_smol_rag(**kwargs) -> SmolRag:
    """Create a SmolRag instance with contradiction detection wired in."""
    from app.contradiction import ContradictionDetector

    rag = SmolRag(**kwargs)

    async def _embedding_fn(text):
        return await rag.rate_limited_get_embedding(text)

    async def _llm_fn(prompt):
        return await rag.rate_limited_get_extract_completion(prompt)

    db_path = kwargs.get("db_path") or SQLITE_DB_PATH
    contradiction_store = SqliteKvStore(db_path, "contradictions")
    rag.contradiction_detector = ContradictionDetector(
        graph_store=rag.graph,
        contradiction_store=contradiction_store,
        llm=_llm_fn,
        embedding_fn=_embedding_fn,
    )
    return rag
