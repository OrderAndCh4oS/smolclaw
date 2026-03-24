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

    @pytest.mark.asyncio
    async def test_batch_decay_used_for_sqlite_store(self):
        """When excerpt_kv is SqliteKvStore, batch_decay is called per tier (T1 + T2, not T0)."""
        from app.sqlite_store import SqliteKvStore

        mock_rag = MagicMock()
        mock_kv = MagicMock(spec=SqliteKvStore)
        mock_kv.batch_decay = AsyncMock(return_value=5)
        mock_rag.excerpt_kv = mock_kv

        mgr = MemoryLifecycleManager(mock_rag)
        count = await mgr.decay(threshold_days=30, factor=0.9)
        # Called twice: once for T1 (factor 0.98) and once for T2 (factor 0.95)
        assert mock_kv.batch_decay.await_count == 2
        assert count == 10  # 5 per tier pass
