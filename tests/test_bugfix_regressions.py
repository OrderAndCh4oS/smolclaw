import os
import asyncio
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.openai_llm import OpenAiLlm
from app.sqlite_store import SqliteKvStore
from app.sqlite_mapping_store import SqliteMappingStore
from app.vector_store import SqliteVectorStore
from app.graph_store import NetworkXGraphStore
from app.utilities import make_hash
from app.definitions import KG_SEP


class _InMemoryKv:
    """In-memory KV store matching SqliteKvStore interface for LLM cache tests."""
    def __init__(self):
        self.store = {}

    async def remove(self, key):
        if key in self.store:
            del self.store[key]

    async def has(self, key):
        return key in self.store

    async def equal(self, key, value):
        return self.store.get(key) == value

    async def get_by_key(self, key):
        return self.store.get(key)

    async def add(self, key, value):
        self.store[key] = value

    async def save(self):
        return None


class _FakeChoice:
    def __init__(self, content):
        self.message = type("Message", (), {"content": content})()


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, model, store, messages):
        system_context = ""
        if messages and messages[0].get("role") == "system":
            system_context = messages[0]["content"]
        user_query = messages[-1]["content"]
        self.calls.append((model, user_query, system_context))
        return type("Response", (), {"choices": [_FakeChoice(f"{user_query}|{system_context}") ]})()


class _FakeClient:
    def __init__(self):
        self._completions = _FakeCompletions()
        self.chat = type("Chat", (), {"completions": self._completions})()
        self.embeddings = _FakeEmbeddings()


class _FakeEmbeddings:
    def __init__(self):
        self.calls = []

    def create(self, model, input):
        inputs = input if isinstance(input, list) else [input]
        self.calls.append((model, inputs))
        base = float((sum(ord(ch) for ch in model) % 1000) / 1000.0)
        data = [
            type("EmbeddingData", (), {"embedding": [base + idx, base + idx + 0.1, base + idx + 0.2]})()
            for idx, _ in enumerate(inputs)
        ]
        return type("EmbeddingResponse", (), {"data": data})()


def _build_rag(temp_dir, llm, excerpt_fn=None):
    pytest.importorskip("nltk")
    from app.smol_rag import SmolRag

    db_path = os.path.join(temp_dir, "test.db")
    return SmolRag(
        llm=llm,
        excerpt_fn=excerpt_fn,
        embeddings_db=SqliteVectorStore(os.path.join(temp_dir, "embeddings"), dimensions=1536),
        entities_db=SqliteVectorStore(os.path.join(temp_dir, "entities"), dimensions=1536),
        relationships_db=SqliteVectorStore(os.path.join(temp_dir, "relationships"), dimensions=1536),
        source_doc_map=SqliteMappingStore(db_path, "source_doc_map", "source", "doc_id"),
        doc_excerpt_map=SqliteMappingStore(db_path, "doc_excerpt_map", "doc_id", "excerpt_id"),
        doc_entity_map=SqliteMappingStore(db_path, "doc_entity_map", "doc_id", "entity_id"),
        doc_relationship_map=SqliteMappingStore(db_path, "doc_relationship_map", "doc_id", "relationship_id"),
        excerpt_kv=SqliteKvStore(db_path, "excerpts"),
        graph_db=NetworkXGraphStore(os.path.join(temp_dir, "graph.graphml")),
    )


def _test_vector():
    return np.ones(1536, dtype=np.float32)


class TestRuntimeRegressions:
    def test_openai_client_initializes_with_explicit_api_key(self):
        llm = OpenAiLlm(openai_api_key="sk-test")
        assert hasattr(llm.client, "chat")
        assert hasattr(llm.client, "embeddings")

    @pytest.mark.asyncio
    async def test_query_cache_key_includes_context(self):
        cache = _InMemoryKv()
        llm = OpenAiLlm(
            query_cache_kv=cache,
            embedding_cache_kv=_InMemoryKv(),
            openai_api_key="sk-test"
        )
        fake_client = _FakeClient()
        llm.client = fake_client

        first = await llm.get_completion("same question", context="context one", use_cache=True)
        second = await llm.get_completion("same question", context="context two", use_cache=True)

        assert first != second
        assert len(cache.store) == 2
        assert len(fake_client._completions.calls) == 2

    @pytest.mark.asyncio
    async def test_embedding_cache_key_includes_model(self):
        cache = _InMemoryKv()
        llm = OpenAiLlm(
            query_cache_kv=_InMemoryKv(),
            embedding_cache_kv=cache,
            openai_api_key="sk-test"
        )
        fake_client = _FakeClient()
        llm.client = fake_client

        first = await llm.get_embedding("same content", model="text-embedding-a")
        second = await llm.get_embedding("same content", model="text-embedding-b")

        assert first != second
        assert len(cache.store) == 2
        assert len(fake_client.embeddings.calls) == 2

    @pytest.mark.asyncio
    async def test_hybrid_query_handles_invalid_keyword_json(self, temp_dir, mock_openai_llm):
        response_stream = iter(["not-json", "final response"])
        mock_openai_llm.get_completion = AsyncMock(side_effect=lambda *args, **kwargs: next(response_stream))
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)

        result = await rag.hybrid_kg_query("what is this?")
        assert result == "final response"
        await rag.close()

    @pytest.mark.asyncio
    async def test_entities_from_relationships_handles_missing_nodes(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        rag.graph.add_edge("A", "B", description="edge", keywords="k", weight=1.0, excerpt_id="x")

        dataset = [{"src_tgt": ("A", "B"), "rank": 1, "description": "edge", "keywords": "k", "weight": 1.0}]
        entities = rag._get_entities_from_relationships(dataset)
        assert entities == []
        await rag.close()

    @pytest.mark.asyncio
    async def test_import_update_removes_then_reindexes_without_excerpt_loss(self, temp_dir, mock_openai_llm):
        def excerpt_fn(content, _size, _overlap):
            return [part.strip() for part in content.split("|") if part.strip()]

        doc_path = os.path.join(temp_dir, "doc.md")
        with open(doc_path, "w") as f:
            f.write("shared|old")

        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm, excerpt_fn=excerpt_fn)

        with patch("app.ingestion.get_docs", return_value=[doc_path]):
            await rag.import_documents()

        original_remove = rag.remove_document_by_id

        async def delayed_remove(doc_id, persist=True):
            await asyncio.sleep(0.05)
            await original_remove(doc_id, persist=persist)

        with open(doc_path, "w") as f:
            f.write("shared|new")

        with patch.object(rag, "remove_document_by_id", new=AsyncMock(side_effect=delayed_remove)):
            with patch("app.ingestion.get_docs", return_value=[doc_path]):
                await rag.import_documents()

        doc_id = await rag.source_doc_map.get_right_single(doc_path)
        excerpt_ids = await rag.doc_excerpt_map.get_by_left(doc_id)
        shared_excerpt_id = make_hash("shared", "excerpt_id_")

        assert shared_excerpt_id in excerpt_ids
        assert await rag.excerpt_kv.get_by_key(shared_excerpt_id) is not None
        await rag.close()

    @pytest.mark.asyncio
    async def test_low_level_dataset_skips_stale_entity_rows(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        rag.entities_db.query = AsyncMock(return_value=[{"__entity_name__": "MissingNode"}])

        ll_dataset, ll_excerpts, ll_relations = await rag.get_low_level_dataset(
            {"low_level_keywords": ["missing node"]}
        )

        assert ll_dataset == []
        assert ll_excerpts == []
        assert ll_relations == []
        await rag.close()

    @pytest.mark.asyncio
    async def test_high_level_dataset_skips_stale_relationship_rows(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        rag.relationships_db.query = AsyncMock(return_value=[{"__source__": "A", "__target__": "B"}])

        hl_dataset, hl_entities, hl_excerpts = await rag.get_high_level_dataset(
            {"high_level_keywords": ["missing edge"]}
        )

        assert hl_dataset == []
        assert hl_entities == []
        assert hl_excerpts == []
        await rag.close()

    @pytest.mark.asyncio
    async def test_mix_query_keeps_metadata_only_session_content_for_episode_recall(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        rag.rate_limited_get_extract_completion = AsyncMock(return_value="{}")
        rag.rate_limited_get_query_completion = AsyncMock(return_value="final response")
        rag.query_engine.get_low_level_dataset = AsyncMock(return_value=([], [], []))
        rag.query_engine.get_high_level_dataset = AsyncMock(return_value=([], [], []))
        rag.query_engine._get_query_excerpts = AsyncMock(return_value=[
            {"excerpt": "#episode #session", "summary": "header"},
            {"excerpt": "user: shipped the feature", "summary": "body", "memory_type": "episode"},
            {"excerpt": "pricing decision", "summary": "decision", "memory_type": "decision"},
        ])

        result = await rag.mix_query("what did we do?", memory_type="episode")

        assert result == "final response"
        context = rag.rate_limited_get_query_completion.await_args.kwargs["context"]
        assert "user: shipped the feature" in context
        assert "pricing decision" not in context
        await rag.close()

    @pytest.mark.asyncio
    async def test_mix_query_return_metadata_uses_filtered_excerpt_ids(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        rag.rate_limited_get_extract_completion = AsyncMock(return_value="{}")
        rag.rate_limited_get_query_completion = AsyncMock(return_value="final response")
        rag.query_engine.get_low_level_dataset = AsyncMock(return_value=([], [
            {"excerpt_id": "exc-low-episode", "excerpt": "low episode", "summary": "low", "memory_type": "episode"},
            {"excerpt_id": "exc-low-decision", "excerpt": "low decision", "summary": "low", "memory_type": "decision"},
        ], []))
        rag.query_engine.get_high_level_dataset = AsyncMock(return_value=([], [], [
            {"excerpt_id": "exc-shared", "excerpt": "shared episode", "summary": "shared", "memory_type": "episode"},
        ]))
        rag.query_engine._get_query_excerpts = AsyncMock(return_value=[
            {"excerpt_id": "exc-query-episode", "excerpt": "query episode", "summary": "query", "memory_type": "episode"},
            {"excerpt_id": "exc-query-decision", "excerpt": "query decision", "summary": "query", "memory_type": "decision"},
            {"excerpt_id": "exc-shared", "excerpt": "shared episode", "summary": "shared", "memory_type": "episode"},
        ])

        result = await rag.mix_query("what did we do?", memory_type="episode", return_metadata=True)

        assert result == {
            "content": "final response",
            "excerpt_ids": ["exc-query-episode", "exc-shared", "exc-low-episode"],
        }
        await rag.close()

    @pytest.mark.asyncio
    async def test_mix_query_include_bm25_deduplicates_by_excerpt_id(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        rag.rate_limited_get_extract_completion = AsyncMock(return_value="{}")
        rag.rate_limited_get_query_completion = AsyncMock(return_value="final response")
        rag.query_engine.get_low_level_dataset = AsyncMock(return_value=([], [], []))
        rag.query_engine.get_high_level_dataset = AsyncMock(return_value=([], [], []))
        rag.query_engine._get_query_excerpts = AsyncMock(return_value=[
            {"excerpt_id": "exc-query", "excerpt": "query episode", "summary": "query"},
        ])
        rag.query_engine.bm25_query = AsyncMock(return_value=[
            {"excerpt_id": "exc-query", "excerpt": "query duplicate", "summary": "dup"},
            {"excerpt_id": "exc-bm25-1", "excerpt": "keyword alpha", "summary": "alpha"},
            {"excerpt_id": "exc-bm25-2", "excerpt": "keyword beta", "summary": "beta"},
        ])

        result = await rag.mix_query(
            "what did we do?",
            include_bm25=True,
            return_metadata=True,
        )

        assert result == {
            "content": "final response",
            "excerpt_ids": ["exc-query", "exc-bm25-1", "exc-bm25-2"],
        }
        await rag.close()

    @pytest.mark.asyncio
    async def test_remove_document_removes_orphaned_kg_entries(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        doc_id = "doc-orphan"
        source = "source-orphan.md"
        excerpt_id = "excerpt-orphan"
        entity_name = "EntityOrphan"
        entity_id = make_hash(entity_name, prefix="ent-")
        relationship_id = make_hash(f"{entity_name}_EntityPeer", prefix="rel-")

        await rag.source_doc_map.add(source, doc_id)
        await rag.doc_excerpt_map.add_many(doc_id, [excerpt_id])
        await rag.excerpt_kv.add(excerpt_id, {"doc_id": doc_id, "excerpt": "text", "summary": "sum"})
        await rag.embeddings_db.upsert([{
            "__id__": excerpt_id,
            "__vector__": _test_vector(),
            "__doc_id__": doc_id,
        }])

        await rag.graph.async_add_node(entity_name, category="Type", description="Desc", excerpt_id=excerpt_id)
        await rag.graph.async_add_node("EntityPeer", category="Type", description="Desc2", excerpt_id=excerpt_id)
        await rag.graph.async_add_edge(
            entity_name, "EntityPeer", description="Rel", keywords="k", weight=1.0, excerpt_id=excerpt_id
        )

        await rag.entities_db.upsert([{
            "__id__": entity_id,
            "__entity_name__": entity_name,
            "__vector__": _test_vector(),
            "__inserted_at__": 0,
        }])
        await rag.relationships_db.upsert([{
            "__id__": relationship_id,
            "__source__": entity_name,
            "__target__": "EntityPeer",
            "__vector__": _test_vector(),
            "__inserted_at__": 0,
        }])
        await rag.doc_entity_map.add(doc_id, entity_id)
        await rag.doc_relationship_map.add(doc_id, relationship_id)

        await rag.remove_document_by_id(doc_id, persist=False)

        assert await rag.entities_db.get([entity_id]) == []
        assert await rag.relationships_db.get([relationship_id]) == []
        assert rag.graph.get_node(entity_name) is None
        assert rag.graph.get_edge((entity_name, "EntityPeer")) is None
        await rag.close()

    @pytest.mark.asyncio
    async def test_remove_document_prunes_shared_entity_excerpt_ids(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        doc_a = "doc-a"
        doc_b = "doc-b"
        excerpt_a = "excerpt-a"
        excerpt_b = "excerpt-b"
        entity_name = "EntityShared"
        entity_id = make_hash(entity_name, prefix="ent-")

        await rag.doc_excerpt_map.add_many(doc_a, [excerpt_a])
        await rag.doc_excerpt_map.add_many(doc_b, [excerpt_b])
        await rag.excerpt_kv.add(excerpt_a, {"doc_id": doc_a, "excerpt": "a", "summary": "a"})
        await rag.excerpt_kv.add(excerpt_b, {"doc_id": doc_b, "excerpt": "b", "summary": "b"})
        await rag.embeddings_db.upsert([{
            "__id__": excerpt_a,
            "__vector__": _test_vector(),
            "__doc_id__": doc_a,
        }])

        await rag.graph.async_add_node(
            entity_name,
            category="Type",
            description="Desc",
            excerpt_id=f"{excerpt_a}{KG_SEP}{excerpt_b}",
        )
        await rag.entities_db.upsert([{
            "__id__": entity_id,
            "__entity_name__": entity_name,
            "__vector__": _test_vector(),
            "__inserted_at__": 0,
        }])
        await rag.doc_entity_map.add(doc_a, entity_id)
        await rag.doc_entity_map.add(doc_b, entity_id)

        await rag.remove_document_by_id(doc_a, persist=False)

        node = rag.graph.get_node(entity_name)
        assert node is not None
        assert node["excerpt_id"] == excerpt_b
        remaining_docs = await rag.doc_entity_map.get_by_right(entity_id)
        assert remaining_docs == [doc_b]
        assert len(await rag.entities_db.get([entity_id])) == 1
        await rag.close()

    @pytest.mark.asyncio
    async def test_cleanup_entity_retains_node_when_excerpt_ids_overlap(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        doc_a = "doc-a"
        doc_b = "doc-b"
        shared_excerpt = "excerpt-shared"
        entity_name = "EntityOverlap"
        entity_id = make_hash(entity_name, prefix="ent-")

        await rag.doc_entity_map.add(doc_a, entity_id)
        await rag.doc_entity_map.add(doc_b, entity_id)
        await rag.graph.async_add_node(
            entity_name,
            category="Type",
            description="Desc",
            excerpt_id=shared_excerpt,
        )
        await rag.entities_db.upsert([{
            "__id__": entity_id,
            "__entity_name__": entity_name,
            "__vector__": _test_vector(),
            "__inserted_at__": 0,
        }])

        removed = await rag._cleanup_entity_contributions(doc_a, {shared_excerpt})

        assert removed is True
        node = rag.graph.get_node(entity_name)
        assert node is not None
        assert node["excerpt_id"] == shared_excerpt
        doc_a_entities = await rag.doc_entity_map.get_by_left(doc_a)
        assert doc_a_entities == []
        remaining_docs = await rag.doc_entity_map.get_by_right(entity_id)
        assert remaining_docs == [doc_b]
        assert len(await rag.entities_db.get([entity_id])) == 1
        await rag.close()

    @pytest.mark.asyncio
    async def test_cleanup_relationship_retains_edge_when_excerpt_ids_overlap(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        doc_a = "doc-a"
        doc_b = "doc-b"
        shared_excerpt = "excerpt-shared"
        source = "EntityA"
        target = "EntityB"
        relationship_id = make_hash(f"{source}_{target}", prefix="rel-")

        await rag.doc_relationship_map.add(doc_a, relationship_id)
        await rag.doc_relationship_map.add(doc_b, relationship_id)
        await rag.graph.async_add_edge(
            source,
            target,
            description="Rel",
            keywords="k",
            weight=1.0,
            excerpt_id=shared_excerpt,
        )
        await rag.relationships_db.upsert([{
            "__id__": relationship_id,
            "__source__": source,
            "__target__": target,
            "__vector__": _test_vector(),
            "__inserted_at__": 0,
        }])

        removed = await rag._cleanup_relationship_contributions(doc_a, {shared_excerpt})

        assert removed is True
        edge = rag.graph.get_edge((source, target))
        assert edge is not None
        assert edge["excerpt_id"] == shared_excerpt
        doc_a_rels = await rag.doc_relationship_map.get_by_left(doc_a)
        assert doc_a_rels == []
        remaining_docs = await rag.doc_relationship_map.get_by_right(relationship_id)
        assert remaining_docs == [doc_b]
        assert len(await rag.relationships_db.get([relationship_id])) == 1
        await rag.close()

    @pytest.mark.asyncio
    async def test_track_kg_provenance_serializes_shared_id_updates(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        shared_entity_id = make_hash("SharedEntity", prefix="ent-")
        shared_relationship_id = make_hash("SharedEntity_OtherEntity", prefix="rel-")

        await asyncio.gather(
            rag._track_kg_provenance("doc-a", {shared_entity_id}, {shared_relationship_id}),
            rag._track_kg_provenance("doc-b", {shared_entity_id}, {shared_relationship_id}),
        )

        entity_docs = await rag.doc_entity_map.get_by_right(shared_entity_id)
        relationship_docs = await rag.doc_relationship_map.get_by_right(shared_relationship_id)
        doc_a_entities = await rag.doc_entity_map.get_by_left("doc-a")
        doc_b_entities = await rag.doc_entity_map.get_by_left("doc-b")
        doc_a_relationships = await rag.doc_relationship_map.get_by_left("doc-a")
        doc_b_relationships = await rag.doc_relationship_map.get_by_left("doc-b")

        assert set(entity_docs) == {"doc-a", "doc-b"}
        assert set(relationship_docs) == {"doc-a", "doc-b"}
        assert doc_a_entities == [shared_entity_id]
        assert doc_b_entities == [shared_entity_id]
        assert doc_a_relationships == [shared_relationship_id]
        assert doc_b_relationships == [shared_relationship_id]
        await rag.close()

    @pytest.mark.asyncio
    async def test_remove_document_serializes_shared_provenance_pruning(self, temp_dir, mock_openai_llm):
        rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)
        doc_a = "doc-a"
        doc_b = "doc-b"
        entity_name = "EntitySharedAtomic"
        entity_id = make_hash(entity_name, prefix="ent-")

        await rag.doc_entity_map.add(doc_a, entity_id)
        await rag.doc_entity_map.add(doc_b, entity_id)
        await rag.graph.async_add_node(entity_name, category="Type", description="Desc", excerpt_id="shared-excerpt")
        await rag.entities_db.upsert([{
            "__id__": entity_id,
            "__entity_name__": entity_name,
            "__vector__": _test_vector(),
            "__inserted_at__": 0,
        }])

        await asyncio.gather(
            rag.remove_document_by_id(doc_a, persist=False),
            rag.remove_document_by_id(doc_b, persist=False),
        )

        assert await rag.doc_entity_map.get_by_left(doc_a) == []
        assert await rag.doc_entity_map.get_by_left(doc_b) == []
        assert await rag.doc_entity_map.get_by_right(entity_id) == []
        assert await rag.entities_db.get([entity_id]) == []
        assert rag.graph.get_node(entity_name) is None
        await rag.close()
