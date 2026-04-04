import os
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("nltk")

from app.graph_store import NetworkXGraphStore
from app.sqlite_store import SqliteKvStore
from app.sqlite_mapping_store import SqliteMappingStore
from app.smol_rag import SmolRag
from app.vector_store import SqliteVectorStore


def _build_rag(temp_dir, llm):
    db_path = os.path.join(temp_dir, "test.db")
    return SmolRag(
        llm=llm,
        excerpt_fn=lambda text, _size, _overlap: [text],
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


@pytest.mark.asyncio
async def test_import_documents_skips_unchanged_source(temp_dir, mock_openai_llm):
    doc_path = os.path.join(temp_dir, "doc.md")
    with open(doc_path, "w") as f:
        f.write("original content")

    rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)

    with patch("app.ingestion.get_docs", return_value=[doc_path]):
        await rag.import_documents()

    rag.ingestion._embed_document = AsyncMock()
    rag.ingestion._extract_entities = AsyncMock()

    with patch("app.ingestion.get_docs", return_value=[doc_path]):
        await rag.import_documents()

    rag.ingestion._embed_document.assert_not_called()
    rag.ingestion._extract_entities.assert_not_called()


@pytest.mark.asyncio
async def test_import_documents_reprocesses_changed_source(temp_dir, mock_openai_llm):
    doc_path = os.path.join(temp_dir, "doc.md")
    with open(doc_path, "w") as f:
        f.write("v1")

    rag = _build_rag(temp_dir=temp_dir, llm=mock_openai_llm)

    with patch("app.ingestion.get_docs", return_value=[doc_path]):
        await rag.import_documents()

    rag.ingestion.doc_manager.remove_document_by_id = AsyncMock()
    rag.ingestion._embed_document = AsyncMock()
    rag.ingestion._extract_entities = AsyncMock()

    with open(doc_path, "w") as f:
        f.write("v2")

    with patch("app.ingestion.get_docs", return_value=[doc_path]):
        await rag.import_documents()

    rag.ingestion.doc_manager.remove_document_by_id.assert_awaited_once()
    rag.ingestion._embed_document.assert_awaited_once()
    rag.ingestion._extract_entities.assert_awaited_once()


