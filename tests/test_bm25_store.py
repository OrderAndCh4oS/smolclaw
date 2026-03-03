import os

import pytest

from app.bm25_store import BM25Store


@pytest.fixture
def bm25(temp_dir):
    db_path = os.path.join(temp_dir, "test.db")
    return BM25Store(db_path, "bm25_test")


class TestBM25StoreBaseline:
    @pytest.mark.asyncio
    async def test_add_and_query(self, bm25):
        await bm25.add("doc1", "the quick brown fox jumps over the lazy dog")
        await bm25.add("doc2", "the quick brown cat sits on the mat")
        results = await bm25.query("fox jumps", top_k=5)
        assert len(results) > 0
        assert results[0]["doc_id"] == "doc1"

    @pytest.mark.asyncio
    async def test_empty_index_returns_empty(self, bm25):
        results = await bm25.query("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, bm25):
        await bm25.add("doc1", "hello world")
        results = await bm25.query("")
        assert results == []

    @pytest.mark.asyncio
    async def test_remove_document(self, bm25):
        await bm25.add("doc1", "python programming language")
        await bm25.add("doc2", "javascript programming language")
        await bm25.remove("doc1")
        results = await bm25.query("python", top_k=5)
        doc_ids = [r["doc_id"] for r in results]
        assert "doc1" not in doc_ids

    @pytest.mark.asyncio
    async def test_remove_nonexistent_is_noop(self, bm25):
        await bm25.remove("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_ranking_order(self, bm25):
        await bm25.add("doc1", "cat cat cat dog")
        await bm25.add("doc2", "cat dog dog dog")
        results = await bm25.query("cat", top_k=5)
        assert results[0]["doc_id"] == "doc1"
        assert results[0]["score"] > results[1]["score"]

    @pytest.mark.asyncio
    async def test_top_k_limit(self, bm25):
        for i in range(20):
            await bm25.add(f"doc{i}", f"common term plus unique_{i}")
        results = await bm25.query("common term", top_k=5)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_scores_are_positive(self, bm25):
        await bm25.add("doc1", "hello world")
        results = await bm25.query("hello")
        assert all(r["score"] > 0 for r in results)


class TestBM25StoreTokenization:
    @pytest.mark.asyncio
    async def test_case_insensitive(self, bm25):
        await bm25.add("doc1", "Python Programming")
        results = await bm25.query("python programming")
        assert len(results) == 1
        assert results[0]["doc_id"] == "doc1"

    @pytest.mark.asyncio
    async def test_punctuation_ignored(self, bm25):
        await bm25.add("doc1", "hello, world! how are you?")
        results = await bm25.query("hello world")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_tokenize_static(self):
        tokens = BM25Store._tokenize("Hello, World! This is a test.")
        assert tokens == ["hello", "world", "this", "is", "a", "test"]


class TestBM25StorePersistence:
    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, temp_dir):
        db_path = os.path.join(temp_dir, "persist.db")

        store1 = BM25Store(db_path, "bm25_persist")
        await store1.add("doc1", "persistent data about foxes")
        await store1.add("doc2", "ephemeral data about cats")
        await store1.close()

        store2 = BM25Store(db_path, "bm25_persist")
        results = await store2.query("foxes", top_k=5)
        assert len(results) > 0
        assert results[0]["doc_id"] == "doc1"
        await store2.close()

    @pytest.mark.asyncio
    async def test_remove_persists(self, temp_dir):
        db_path = os.path.join(temp_dir, "persist_rm.db")

        store1 = BM25Store(db_path, "bm25_rm")
        await store1.add("doc1", "alpha beta gamma")
        await store1.remove("doc1")
        await store1.close()

        store2 = BM25Store(db_path, "bm25_rm")
        results = await store2.query("alpha", top_k=5)
        assert len(results) == 0
        await store2.close()


class TestBM25StoreReplace:
    @pytest.mark.asyncio
    async def test_add_same_id_replaces(self, bm25):
        await bm25.add("doc1", "old content about dogs")
        await bm25.add("doc1", "new content about cats")
        results = await bm25.query("cats", top_k=5)
        assert len(results) == 1
        assert results[0]["doc_id"] == "doc1"
        results = await bm25.query("dogs", top_k=5)
        # "dogs" should not match the replaced doc
        assert len(results) == 0
