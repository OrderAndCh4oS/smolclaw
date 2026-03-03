import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.context_assembly import ContextAssembler, AssemblyManifest, InclusionRecord


@pytest.fixture
def mock_smol_rag_for_assembly():
    """SmolRAG mock with vector search support."""
    mock = MagicMock()

    # Mock embedding generation
    mock.rate_limited_get_embedding = AsyncMock(return_value=[0.1] * 1536)

    # Mock vector query results
    mock.embeddings_db = MagicMock()
    mock.embeddings_db.query = AsyncMock(return_value=[
        {"__id__": "exc_1"},
        {"__id__": "exc_2"},
        {"__id__": "exc_3"},
    ])

    # Mock excerpt data
    async def get_excerpt(key):
        data = {
            "exc_1": {
                "excerpt": "Python is a programming language.",
                "summary": "About Python.",
                "importance": 0.9,
                "confidence": 0.95,
                "indexed_at": time.time() - 86400,  # 1 day ago
            },
            "exc_2": {
                "excerpt": "FastAPI is a web framework built with Python.",
                "summary": "About FastAPI.",
                "importance": 0.7,
                "confidence": 0.8,
                "indexed_at": time.time() - 86400 * 7,  # 7 days ago
            },
            "exc_3": {
                "excerpt": "JavaScript runs in the browser and on Node.js servers.",
                "summary": "About JavaScript.",
                "importance": 0.5,
                "confidence": 0.6,
                "indexed_at": time.time() - 86400 * 30,  # 30 days ago
            },
        }
        return data.get(key)

    mock.excerpt_kv = MagicMock()
    mock.excerpt_kv.get_by_key = AsyncMock(side_effect=get_excerpt)
    return mock


class TestContextAssembler:
    @pytest.mark.asyncio
    async def test_retrieve_context_returns_text(self, mock_smol_rag_for_assembly):
        assembler = ContextAssembler(
            smol_rag=mock_smol_rag_for_assembly,
            token_budget=4000,
        )
        context, manifest = await assembler.retrieve_context("What is Python?")
        assert "Python" in context
        assert len(manifest.included) > 0
        assert manifest.used_tokens > 0

    @pytest.mark.asyncio
    async def test_budget_limits_excerpts(self, mock_smol_rag_for_assembly):
        assembler = ContextAssembler(
            smol_rag=mock_smol_rag_for_assembly,
            token_budget=10,  # Very small budget
        )
        context, manifest = await assembler.retrieve_context("test")
        assert manifest.used_tokens <= 10
        assert len(manifest.excluded) > 0

    @pytest.mark.asyncio
    async def test_scoring_prioritizes_high_importance(self, mock_smol_rag_for_assembly):
        assembler = ContextAssembler(
            smol_rag=mock_smol_rag_for_assembly,
            token_budget=4000,
        )
        _, manifest = await assembler.retrieve_context("test")
        # First included should be highest scored
        if len(manifest.included) >= 2:
            assert manifest.included[0].score >= manifest.included[1].score

    @pytest.mark.asyncio
    async def test_manifest_logged(self, mock_smol_rag_for_assembly):
        assembler = ContextAssembler(
            smol_rag=mock_smol_rag_for_assembly,
            token_budget=4000,
        )
        await assembler.retrieve_context("test")
        assert assembler.last_manifest is not None
        assert assembler.last_manifest.total_budget == 4000

    @pytest.mark.asyncio
    async def test_build_messages_with_context(self, mock_smol_rag_for_assembly):
        assembler = ContextAssembler(
            smol_rag=mock_smol_rag_for_assembly,
            token_budget=4000,
        )
        messages = await assembler.build_messages_with_context(
            history=[{"role": "user", "content": "hi"}],
            user_content="What is Python?",
        )
        assert messages[0]["role"] == "system"
        assert "Relevant Memories" in messages[0]["content"]
        assert messages[-1]["content"] == "What is Python?"

    @pytest.mark.asyncio
    async def test_build_messages_async_includes_context(self, mock_smol_rag_for_assembly):
        assembler = ContextAssembler(
            smol_rag=mock_smol_rag_for_assembly,
            token_budget=4000,
        )
        messages = await assembler.build_messages_async(
            history=[{"role": "user", "content": "hi"}],
            user_content="What is Python?",
        )
        assert messages[0]["role"] == "system"
        assert "Relevant Memories" in messages[0]["content"]
        assert messages[-1]["content"] == "What is Python?"

    def test_recency_decay(self, mock_smol_rag_for_assembly):
        assembler = ContextAssembler(smol_rag=mock_smol_rag_for_assembly)
        # Recent item should have higher decay
        recent = assembler._recency_decay(time.time() - 3600)  # 1 hour ago
        old = assembler._recency_decay(time.time() - 86400 * 60)  # 60 days ago
        assert recent > old

    def test_score_excerpt(self, mock_smol_rag_for_assembly):
        assembler = ContextAssembler(smol_rag=mock_smol_rag_for_assembly)
        high_score = assembler._score_excerpt({
            "importance": 1.0, "confidence": 1.0, "indexed_at": time.time(),
        })
        low_score = assembler._score_excerpt({
            "importance": 0.1, "confidence": 0.5, "indexed_at": time.time() - 86400 * 90,
        })
        assert high_score > low_score


class TestAssemblyManifest:
    def test_summary(self):
        manifest = AssemblyManifest(
            total_budget=1000,
            used_tokens=500,
            included=[
                InclusionRecord("a", True, "fits", 0.9, 250),
                InclusionRecord("b", True, "fits", 0.8, 250),
            ],
            excluded=[
                InclusionRecord("c", False, "over budget", 0.5, 300),
            ],
        )
        summary = manifest.summary()
        assert "2 included" in summary
        assert "1 excluded" in summary
        assert "500/1000" in summary
