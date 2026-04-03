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

    mock.get_excerpt = AsyncMock(side_effect=get_by_key)
    mock.update_excerpt = AsyncMock(side_effect=add)

    # Pre-populate some excerpts
    excerpt_store["exc_1"] = {
        "doc_id": "doc_1",
        "excerpt": "Python is a high-level language.",
        "importance": 0.5,
        "indexed_at": time.time() - 3600,
    }
    excerpt_store["exc_2"] = {
        "doc_id": "doc_1",
        "excerpt": "FastAPI uses Python.",
        "importance": 0.6,
        "indexed_at": time.time() - 86400 * 60,
        "tier": 2,
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

    @pytest.mark.asyncio
    async def test_auto_promote_t2_to_t1(self, mock_lifecycle_rag):
        """T2 memory crossing importance 0.8 auto-promotes to T1."""
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        # exc_2 starts at importance 0.6, tier 2
        await mgr.promote("exc_2", boost=0.25)  # 0.85 -> should auto-promote
        data = await mock_lifecycle_rag.get_excerpt("exc_2")
        assert data["tier"] == 1
        assert data["importance"] == 0.85

    @pytest.mark.asyncio
    async def test_no_auto_promote_below_threshold(self, mock_lifecycle_rag):
        """T2 memory below 0.8 stays at T2."""
        mgr = MemoryLifecycleManager(mock_lifecycle_rag)
        await mgr.promote("exc_2", boost=0.1)  # 0.7 -> stays T2
        data = await mock_lifecycle_rag.get_excerpt("exc_2")
        assert data["tier"] == 2
