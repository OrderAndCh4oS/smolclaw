import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.lifecycle import MemoryLifecycleManager


@pytest.fixture
def mock_lifecycle_rag():
    mock = MagicMock()

    excerpt_store = {}

    async def get_by_key(key):
        return excerpt_store.get(key)

    async def add(key, value):
        excerpt_store[key] = value

    async def get_all():
        return {k: v for k, v in excerpt_store.items()}

    mock.excerpt_kv = MagicMock()
    mock.excerpt_kv.get_by_key = AsyncMock(side_effect=get_by_key)
    mock.excerpt_kv.add = AsyncMock(side_effect=add)
    mock.excerpt_kv.get_all = AsyncMock(side_effect=get_all)

    mock.source_doc_map = MagicMock()
    mock.source_doc_map.get_left_single = AsyncMock(return_value="/path/to/source.md")

    mock.rate_limited_get_embedding = AsyncMock(return_value=[0.1] * 1536)
    mock.embeddings_db = MagicMock()
    mock.embeddings_db.query = AsyncMock(return_value=[])

    # Pre-populate some excerpts
    excerpt_store["exc_1"] = {
        "doc_id": "doc_1",
        "excerpt": "Python is a high-level language.",
        "summary": "About Python.",
        "importance": 0.5,
        "confidence": 0.9,
        "indexed_at": time.time() - 3600,
    }
    excerpt_store["exc_2"] = {
        "doc_id": "doc_1",
        "excerpt": "FastAPI uses Python.",
        "summary": "About FastAPI.",
        "importance": 0.6,
        "confidence": 0.8,
        "indexed_at": time.time() - 86400 * 60,  # 60 days old
    }
    excerpt_store["exc_3"] = {
        "doc_id": "doc_2",
        "excerpt": "JavaScript runs in the browser.",
        "summary": "About JS.",
        "importance": 0.3,
        "confidence": 0.7,
        "indexed_at": time.time() - 86400 * 90,  # 90 days old
    }

    return mock


class TestPromote:
    @pytest.mark.asyncio
    async def test_promote_increases_importance(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        new_importance = await mgr.promote("exc_1", boost=0.2)
        assert new_importance == 0.7

    @pytest.mark.asyncio
    async def test_promote_caps_at_one(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        new_importance = await mgr.promote("exc_1", boost=0.9)
        assert new_importance == 1.0

    @pytest.mark.asyncio
    async def test_promote_nonexistent(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        result = await mgr.promote("nonexistent")
        assert result == 0.0


class TestDecay:
    @pytest.mark.asyncio
    async def test_decay_affects_old_memories(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        count = await mgr.decay(threshold_days=30, factor=0.9)
        assert count >= 1  # exc_2 and exc_3 are older than 30 days

    @pytest.mark.asyncio
    async def test_decay_preserves_recent_memories(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        data_before = await mock_lifecycle_rag.excerpt_kv.get_by_key("exc_1")
        importance_before = data_before["importance"]
        await mgr.decay(threshold_days=30, factor=0.9)
        data_after = await mock_lifecycle_rag.excerpt_kv.get_by_key("exc_1")
        assert data_after["importance"] == importance_before


class TestConsolidate:
    @pytest.mark.asyncio
    async def test_consolidate_with_llm(self, mock_lifecycle_rag):
        llm = MagicMock()
        llm.get_completion = AsyncMock(return_value="Python is a high-level language used with FastAPI.")
        mgr = MemoryLifecycleManager(mock_lifecycle_rag, llm=llm)
        result = await mgr.consolidate(["exc_1", "exc_2"])
        assert "Python" in result
        llm.get_completion.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_consolidate_without_llm(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag, llm=None)
        result = await mgr.consolidate(["exc_1", "exc_2"])
        assert result is None

    @pytest.mark.asyncio
    async def test_consolidate_single_item(self, mock_lifecycle_rag):
        llm = MagicMock()
        mgr = MemoryLifecycleManager(mock_lifecycle_rag, llm=llm)
        result = await mgr.consolidate(["exc_1"])
        assert result is None


class TestDetectContradictions:
    @pytest.mark.asyncio
    async def test_detect_no_contradictions(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        results = await mgr.detect_contradictions("exc_1")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_detect_nonexistent(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        results = await mgr.detect_contradictions("nonexistent")
        assert results == []


class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_audit_trail_returns_provenance(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        trail = await mgr.get_audit_trail("exc_1")
        assert trail["excerpt_id"] == "exc_1"
        assert trail["doc_id"] == "doc_1"
        assert trail["source"] == "/path/to/source.md"

    @pytest.mark.asyncio
    async def test_audit_trail_nonexistent(self, mock_lifecycle_rag):
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        trail = await mgr.get_audit_trail("nonexistent")
        assert "error" in trail
