"""Tests for SqliteKvStore — drop-in replacement for JsonKvStore."""
import asyncio
import os
import pytest

from app.sqlite_store import SqliteKvStore


@pytest.fixture
def sqlite_kv(temp_dir):
    db_path = os.path.join(temp_dir, "test.db")
    store = SqliteKvStore(db_path, "test_table")
    yield store


class TestSqliteKvStoreBaseline:
    @pytest.mark.asyncio
    async def test_set_and_get_single_value(self, sqlite_kv):
        await sqlite_kv.add("test_key", "test_value")
        value = await sqlite_kv.get_by_key("test_key")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_set_complex_value(self, sqlite_kv):
        complex_data = {
            "nested": {
                "data": [1, 2, 3],
                "more": {"deep": "value"}
            }
        }
        await sqlite_kv.add("complex", complex_data)
        retrieved = await sqlite_kv.get_by_key("complex")
        assert retrieved == complex_data

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, sqlite_kv):
        value = await sqlite_kv.get_by_key("nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_delete_key(self, sqlite_kv):
        await sqlite_kv.add("to_delete", "value")
        await sqlite_kv.remove("to_delete")
        value = await sqlite_kv.get_by_key("to_delete")
        assert value is None

    @pytest.mark.asyncio
    async def test_has_key(self, sqlite_kv):
        await sqlite_kv.add("exists", "value")
        assert await sqlite_kv.has("exists") is True
        assert await sqlite_kv.has("missing") is False

    @pytest.mark.asyncio
    async def test_equal(self, sqlite_kv):
        await sqlite_kv.add("key", "value")
        assert await sqlite_kv.equal("key", "value") is True
        assert await sqlite_kv.equal("key", "other") is False
        assert await sqlite_kv.equal("missing", "value") is False

    @pytest.mark.asyncio
    async def test_get_all(self, sqlite_kv):
        await sqlite_kv.add("a", 1)
        await sqlite_kv.add("b", 2)
        all_data = await sqlite_kv.get_all()
        assert all_data == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_multiple_keys(self, sqlite_kv):
        data = {"key1": "value1", "key2": "value2", "key3": "value3"}
        for key, value in data.items():
            await sqlite_kv.add(key, value)
        for key, expected in data.items():
            assert await sqlite_kv.get_by_key(key) == expected

    @pytest.mark.asyncio
    async def test_overwrite_key(self, sqlite_kv):
        await sqlite_kv.add("key", "old")
        await sqlite_kv.add("key", "new")
        assert await sqlite_kv.get_by_key("key") == "new"

    @pytest.mark.asyncio
    async def test_save_is_noop(self, sqlite_kv):
        await sqlite_kv.add("key", "value")
        await sqlite_kv.save()  # Should not raise
        assert await sqlite_kv.get_by_key("key") == "value"

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, temp_dir):
        db_path = os.path.join(temp_dir, "persist.db")
        store1 = SqliteKvStore(db_path, "persist_table")
        await store1.add("persistent", "data")
        await store1.close()

        store2 = SqliteKvStore(db_path, "persist_table")
        value = await store2.get_by_key("persistent")
        await store2.close()
        assert value == "data"

    @pytest.mark.asyncio
    async def test_stores_list_values(self, sqlite_kv):
        await sqlite_kv.add("key", [1, 2, 3])
        result = await sqlite_kv.get_by_key("key")
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_concurrent_writes(self, sqlite_kv):
        async def writer(prefix, count):
            for i in range(count):
                await sqlite_kv.add(f"{prefix}_{i}", f"value_{i}")

        await asyncio.gather(
            writer("a", 50),
            writer("b", 50),
        )

        for prefix in ("a", "b"):
            for i in range(50):
                assert await sqlite_kv.get_by_key(f"{prefix}_{i}") == f"value_{i}"
