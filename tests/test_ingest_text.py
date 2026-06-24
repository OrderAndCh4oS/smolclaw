import os
import tempfile
import shutil

import pytest
import numpy as np
from unittest.mock import AsyncMock

from app.graph_store import NetworkXGraphStore
from app.sqlite_store import SqliteKvStore
from app.sqlite_mapping_store import SqliteMappingStore
from app.vector_store import SqliteVectorStore
from app.smol_rag import SmolRag


@pytest.fixture
def rag_temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def test_rag(rag_temp_dir, mock_openai_llm):
    """Create a SmolRag instance with mock LLM and temp storage."""
    db_path = os.path.join(rag_temp_dir, "test.db")
    rag = SmolRag(
        llm=mock_openai_llm,
        embeddings_db=SqliteVectorStore(os.path.join(rag_temp_dir, "embeddings.json"), 1536),
        entities_db=SqliteVectorStore(os.path.join(rag_temp_dir, "entities.json"), 1536),
        relationships_db=SqliteVectorStore(os.path.join(rag_temp_dir, "relationships.json"), 1536),
        source_doc_map=SqliteMappingStore(db_path, "source_doc_map", "source", "doc_id"),
        doc_excerpt_map=SqliteMappingStore(db_path, "doc_excerpt_map", "doc_id", "excerpt_id"),
        doc_entity_map=SqliteMappingStore(db_path, "doc_entity_map", "doc_id", "entity_id"),
        doc_relationship_map=SqliteMappingStore(db_path, "doc_relationship_map", "doc_id", "relationship_id"),
        excerpt_kv=SqliteKvStore(db_path, "excerpts"),
        query_cache_kv=SqliteKvStore(db_path, "query_cache"),
        embedding_cache_kv=SqliteKvStore(db_path, "embedding_cache"),
        graph_db=NetworkXGraphStore(os.path.join(rag_temp_dir, "kg.graphml")),
        dimensions=1536,
        excerpt_size=500,
        overlap=50,
    )
    yield rag
    await rag.close()


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
        has_source = await test_rag.source_doc_map.has_left("my-source")
        assert has_source

    @pytest.mark.asyncio
    async def test_ingest_text_strips_memory_metadata_from_indexed_content(self, test_rag):
        from app.definitions import COMPLETE_TAG

        test_rag.llm.get_completion = AsyncMock(return_value=COMPLETE_TAG)
        text = """---
memory_type: episode
tags:
  - text-editor
created_at: '2026-06-23T15:48:20.187614+00:00'
source_id: session-coder-default
---

#episode #text-editor

For the text editor project, add tests for cursor movement.
"""

        await test_rag.ingest_text(text, source_id="session-coder-default")

        all_excerpts = await test_rag.excerpt_kv.get_all()
        assert len(all_excerpts) == 1
        excerpt = next(iter(all_excerpts.values()))
        assert excerpt["memory_type"] == "episode"
        assert excerpt["excerpt"] == "For the text editor project, add tests for cursor movement."

        prompt_texts = [call.args[0] for call in test_rag.llm.get_completion.await_args_list]
        assert prompt_texts
        assert all("memory_type" not in prompt for prompt in prompt_texts)
        assert all("created_at" not in prompt for prompt in prompt_texts)
        assert all("#episode" not in prompt for prompt in prompt_texts)
        assert all("cursor movement" in prompt for prompt in prompt_texts)

    @pytest.mark.asyncio
    async def test_ingest_text_default_source_id(self, test_rag):
        text = "Test content without explicit source."
        await test_rag.ingest_text(text)
        # The source_doc_map should have one entry with a hash-based source key
        # We can't call get_all on a mapping store, but we can check the source was added
        # by checking that the mapping store has at least one entry
        from app.utilities import make_hash
        expected_source = make_hash(text, "text-")
        has_source = await test_rag.source_doc_map.has_left(expected_source)
        assert has_source

    @pytest.mark.asyncio
    async def test_ingest_text_with_obsidian_links(self, test_rag):
        from app.definitions import TUPLE_SEP, COMPLETE_TAG
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
