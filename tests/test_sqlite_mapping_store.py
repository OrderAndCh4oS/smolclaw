"""Tests for SqliteMappingStore — relational many-to-many mapping store."""
import asyncio
import os
import pytest

from app.sqlite_mapping_store import SqliteMappingStore


@pytest.fixture
def mapping_store(temp_dir):
    db_path = os.path.join(temp_dir, "test.db")
    store = SqliteMappingStore(db_path, "test_map", "left_col", "right_col")
    yield store


class TestMappingStoreBaseline:
    @pytest.mark.asyncio
    async def test_add_and_get_by_left(self, mapping_store):
        await mapping_store.add("doc1", "excerpt1")
        await mapping_store.add("doc1", "excerpt2")
        result = await mapping_store.get_by_left("doc1")
        assert set(result) == {"excerpt1", "excerpt2"}

    @pytest.mark.asyncio
    async def test_add_and_get_by_right(self, mapping_store):
        await mapping_store.add("doc1", "entity1")
        await mapping_store.add("doc2", "entity1")
        result = await mapping_store.get_by_right("entity1")
        assert set(result) == {"doc1", "doc2"}

    @pytest.mark.asyncio
    async def test_get_by_left_empty(self, mapping_store):
        result = await mapping_store.get_by_left("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_by_right_empty(self, mapping_store):
        result = await mapping_store.get_by_right("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_remove_by_left(self, mapping_store):
        await mapping_store.add("doc1", "excerpt1")
        await mapping_store.add("doc1", "excerpt2")
        await mapping_store.add("doc2", "excerpt3")
        await mapping_store.remove_by_left("doc1")
        assert await mapping_store.get_by_left("doc1") == []
        assert await mapping_store.get_by_left("doc2") == ["excerpt3"]

    @pytest.mark.asyncio
    async def test_remove_by_right(self, mapping_store):
        await mapping_store.add("doc1", "entity1")
        await mapping_store.add("doc2", "entity1")
        await mapping_store.remove_by_right("entity1")
        assert await mapping_store.get_by_right("entity1") == []

    @pytest.mark.asyncio
    async def test_remove_pair(self, mapping_store):
        await mapping_store.add("doc1", "excerpt1")
        await mapping_store.add("doc1", "excerpt2")
        await mapping_store.remove_pair("doc1", "excerpt1")
        result = await mapping_store.get_by_left("doc1")
        assert result == ["excerpt2"]

    @pytest.mark.asyncio
    async def test_has_left(self, mapping_store):
        await mapping_store.add("doc1", "excerpt1")
        assert await mapping_store.has_left("doc1") is True
        assert await mapping_store.has_left("doc2") is False

    @pytest.mark.asyncio
    async def test_has_right(self, mapping_store):
        await mapping_store.add("doc1", "entity1")
        assert await mapping_store.has_right("entity1") is True
        assert await mapping_store.has_right("entity2") is False


class TestMappingStoreOneToOne:
    @pytest.mark.asyncio
    async def test_get_right_single(self, mapping_store):
        await mapping_store.add("source1", "doc1")
        result = await mapping_store.get_right_single("source1")
        assert result == "doc1"

    @pytest.mark.asyncio
    async def test_get_right_single_missing(self, mapping_store):
        result = await mapping_store.get_right_single("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_left_single(self, mapping_store):
        await mapping_store.add("source1", "doc1")
        result = await mapping_store.get_left_single("doc1")
        assert result == "source1"

    @pytest.mark.asyncio
    async def test_equal_right(self, mapping_store):
        await mapping_store.add("source1", "doc1")
        assert await mapping_store.equal_right("source1", "doc1") is True
        assert await mapping_store.equal_right("source1", "doc2") is False
        assert await mapping_store.equal_right("missing", "doc1") is False


class TestMappingStoreAddMany:
    @pytest.mark.asyncio
    async def test_add_many_replaces_existing(self, mapping_store):
        await mapping_store.add("doc1", "old1")
        await mapping_store.add("doc1", "old2")
        await mapping_store.add_many("doc1", ["new1", "new2", "new3"])
        result = await mapping_store.get_by_left("doc1")
        assert set(result) == {"new1", "new2", "new3"}

    @pytest.mark.asyncio
    async def test_add_many_empty_list(self, mapping_store):
        await mapping_store.add("doc1", "old1")
        await mapping_store.add_many("doc1", [])
        result = await mapping_store.get_by_left("doc1")
        assert result == []


class TestMappingStoreDuplicates:
    @pytest.mark.asyncio
    async def test_add_duplicate_is_ignored(self, mapping_store):
        await mapping_store.add("doc1", "entity1")
        await mapping_store.add("doc1", "entity1")
        result = await mapping_store.get_by_left("doc1")
        assert result == ["entity1"]


class TestMappingStorePersistence:
    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, temp_dir):
        db_path = os.path.join(temp_dir, "persist.db")
        store1 = SqliteMappingStore(db_path, "persist_map", "source", "doc_id")
        await store1.add("source1", "doc1")
        await store1.close()

        store2 = SqliteMappingStore(db_path, "persist_map", "source", "doc_id")
        result = await store2.get_by_left("source1")
        await store2.close()
        assert result == ["doc1"]


class TestMappingStoreConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_adds(self, mapping_store):
        async def add_batch(prefix, count):
            for i in range(count):
                await mapping_store.add(f"{prefix}", f"item_{prefix}_{i}")

        await asyncio.gather(
            add_batch("a", 20),
            add_batch("b", 20),
        )

        a_items = await mapping_store.get_by_left("a")
        b_items = await mapping_store.get_by_left("b")
        assert len(a_items) == 20
        assert len(b_items) == 20
