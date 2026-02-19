import os
import tempfile
import shutil

import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock

from app.graph_store import NetworkXGraphStore
from app.kv_store import JsonKvStore
from app.vector_store import NanoVectorStore
from app.smol_rag import SmolRag


@pytest.fixture
def rag_temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_rag(rag_temp_dir, mock_openai_llm):
    """Create a SmolRag instance with mock LLM and temp storage."""
    return SmolRag(
        llm=mock_openai_llm,
        embeddings_db=NanoVectorStore(os.path.join(rag_temp_dir, "embeddings.json"), 1536),
        entities_db=NanoVectorStore(os.path.join(rag_temp_dir, "entities.json"), 1536),
        relationships_db=NanoVectorStore(os.path.join(rag_temp_dir, "relationships.json"), 1536),
        source_to_doc_kv=JsonKvStore(os.path.join(rag_temp_dir, "s2d.json")),
        doc_to_source_kv=JsonKvStore(os.path.join(rag_temp_dir, "d2s.json")),
        doc_to_excerpt_kv=JsonKvStore(os.path.join(rag_temp_dir, "d2e.json")),
        doc_to_entity_kv=JsonKvStore(os.path.join(rag_temp_dir, "d2ent.json")),
        doc_to_relationship_kv=JsonKvStore(os.path.join(rag_temp_dir, "d2rel.json")),
        entity_to_doc_kv=JsonKvStore(os.path.join(rag_temp_dir, "ent2d.json")),
        relationship_to_doc_kv=JsonKvStore(os.path.join(rag_temp_dir, "rel2d.json")),
        excerpt_kv=JsonKvStore(os.path.join(rag_temp_dir, "excerpts.json")),
        query_cache_kv=JsonKvStore(os.path.join(rag_temp_dir, "qcache.json")),
        embedding_cache_kv=JsonKvStore(os.path.join(rag_temp_dir, "ecache.json")),
        graph_db=NetworkXGraphStore(os.path.join(rag_temp_dir, "kg.graphml")),
        dimensions=1536,
        excerpt_size=500,
        overlap=50,
    )


class TestIngestText:
    @pytest.mark.asyncio
    async def test_ingest_text_creates_excerpts(self, test_rag):
        text = "Python is a great programming language. " * 20
        await test_rag.ingest_text(text)
        all_excerpts = await test_rag.excerpt_kv.get_all()
        assert len(all_excerpts) > 0

    @pytest.mark.asyncio
    async def test_ingest_text_creates_embeddings(self, test_rag):
        text = "Python is a great programming language. " * 20
        await test_rag.ingest_text(text)
        # Verify embeddings_db has vectors by querying with a random vector
        query_vec = np.random.rand(1536).astype(np.float32)
        results = await test_rag.embeddings_db.query(query=query_vec, top_k=5)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_ingest_text_extracts_entities(self, test_rag):
        # Mock completion to return entity extraction format
        from app.definitions import TUPLE_SEP, REC_SEP, COMPLETE_TAG
        entity_output = (
            f'("entity"{TUPLE_SEP}"Python"{TUPLE_SEP}"language"{TUPLE_SEP}"A programming language")'
            f'{REC_SEP}'
            f'("entity"{TUPLE_SEP}"FastAPI"{TUPLE_SEP}"framework"{TUPLE_SEP}"A web framework")'
            f'{REC_SEP}'
            f'("relationship"{TUPLE_SEP}"FastAPI"{TUPLE_SEP}"Python"{TUPLE_SEP}"built with"{TUPLE_SEP}"framework"{TUPLE_SEP}8)'
            f'{COMPLETE_TAG}'
        )
        test_rag.llm.get_completion = AsyncMock(return_value=entity_output)

        text = "Python and FastAPI are great tools for building web applications."
        await test_rag.ingest_text(text)
        # Check graph has nodes
        assert test_rag.graph.get_node("Python") is not None or test_rag.graph.get_node("FastAPI") is not None

    @pytest.mark.asyncio
    async def test_ingest_text_with_source_id(self, test_rag):
        text = "Test content for source tracking."
        await test_rag.ingest_text(text, source_id="my-source")
        has_source = await test_rag.source_to_doc_kv.has("my-source")
        assert has_source

    @pytest.mark.asyncio
    async def test_ingest_text_default_source_id(self, test_rag):
        text = "Test content without explicit source."
        await test_rag.ingest_text(text)
        all_sources = await test_rag.source_to_doc_kv.get_all()
        # Should have one entry with a hash-based key
        assert len(all_sources) == 1
        key = list(all_sources.keys())[0]
        assert key.startswith("text-")

    @pytest.mark.asyncio
    async def test_ingest_text_with_obsidian_links(self, test_rag):
        from app.definitions import TUPLE_SEP, REC_SEP, COMPLETE_TAG
        entity_output = (
            f'("entity"{TUPLE_SEP}"Python"{TUPLE_SEP}"language"{TUPLE_SEP}"A language")'
            f'{COMPLETE_TAG}'
        )
        test_rag.llm.get_completion = AsyncMock(return_value=entity_output)

        text = "I love [[Python]] and [[JavaScript|JS]] for web dev."
        await test_rag.ingest_text(text)
        # Wiki links should create edges in graph
        # Python and JavaScript nodes should exist
        has_python = test_rag.graph.graph.has_node("Python")
        has_js = test_rag.graph.graph.has_node("JavaScript")
        assert has_python or has_js

    @pytest.mark.asyncio
    async def test_ingest_text_searchable_after(self, test_rag):
        text = "SmolClaw is an agentic memory system built on SmolRAG. " * 10
        await test_rag.ingest_text(text)
        await test_rag._save_stores()
        # Querying should find related content
        # Since mock LLM returns random embeddings, we just verify it doesn't crash
        query_vec = np.random.rand(1536).astype(np.float32)
        results = await test_rag.embeddings_db.query(query=query_vec, top_k=5)
        assert len(results) > 0
