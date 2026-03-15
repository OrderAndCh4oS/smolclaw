"""Unit tests for ContradictionDetector with mocked graph/LLM."""

import asyncio
import time

import numpy as np
import pytest

from app.contradiction import ContradictionDetector, _cosine_similarity, SIMILARITY_THRESHOLD


class FakeGraph:
    """Minimal graph store mock for contradiction tests."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def get_node(self, name):
        return self.nodes.get(name)

    def get_edge(self, edge):
        return self.edges.get(edge)

    async def async_add_node(self, name, **kwargs):
        self.nodes[name] = kwargs

    async def async_add_edge(self, source, destination, **kwargs):
        self.edges[(source, destination)] = kwargs


class FakeKvStore:
    """Minimal KV store mock."""

    def __init__(self):
        self._data = {}

    async def add(self, key, value):
        self._data[key] = value

    async def get_by_key(self, key):
        return self._data.get(key)

    async def get_all(self):
        return dict(self._data)


def make_embedding(values):
    """Create a normalized embedding from a few values."""
    v = np.array(values, dtype=np.float32)
    norm = np.linalg.norm(v)
    if norm > 0:
        v = v / norm
    return v.tolist()


# Pre-built embeddings for test phrases
# "Python is fast" vs "Python is slow" — different directions
EMB_FAST = make_embedding([1.0, 0.0, 0.3])
EMB_SLOW = make_embedding([-1.0, 0.0, 0.3])
# "Python is a programming language" — unrelated axis
EMB_LANG = make_embedding([0.0, 1.0, 0.3])
# "Python is quite fast" — similar to fast
EMB_QUITE_FAST = make_embedding([0.95, 0.05, 0.3])


class TestCosineSimlarity:
    def test_identical_vectors(self):
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert _cosine_similarity([0, 0], [1, 0]) == pytest.approx(0.0)


class TestContradictionDetector:
    @pytest.fixture
    def graph(self):
        return FakeGraph()

    @pytest.fixture
    def store(self):
        return FakeKvStore()

    def _make_embedding_fn(self, mapping):
        """Create an embedding function that returns pre-set embeddings."""
        async def embedding_fn(text):
            for key, emb in mapping.items():
                if key.lower() in text.lower():
                    return emb
            # Default: return a random-ish embedding
            return make_embedding([0.5, 0.5, 0.5])
        return embedding_fn

    def _make_llm_fn(self, verdict="contradict", confidence=0.9, reasoning="test"):
        async def llm_fn(prompt):
            return f'{{"verdict": "{verdict}", "confidence": {confidence}, "reasoning": "{reasoning}"}}'
        return llm_fn

    @pytest.mark.asyncio
    async def test_new_entity_no_check(self, graph, store):
        """New entities (not in graph) should not trigger any checks."""
        detector = ContradictionDetector(
            graph, store,
            self._make_llm_fn(),
            self._make_embedding_fn({}),
        )
        result = await detector.check_entity(
            "NewEntity", "thing", "some description", "exc-1",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_compatible_descriptions_skip_llm(self, graph, store):
        """High-similarity descriptions should not trigger LLM adjudication."""
        graph.nodes["Python"] = {
            "description": "Python is quite fast",
            "excerpt_id": "exc-old",
            "category": "language",
        }
        llm_called = []

        async def tracking_llm(prompt):
            llm_called.append(True)
            return '{"verdict": "agree", "confidence": 0.9, "reasoning": "ok"}'

        detector = ContradictionDetector(
            graph, store, tracking_llm,
            self._make_embedding_fn({
                "fast": EMB_FAST,
                "quite fast": EMB_QUITE_FAST,
            }),
        )
        result = await detector.check_entity(
            "Python", "language", "Python is fast", "exc-new",
        )
        # High similarity — structural check passes, no LLM call
        assert result == []
        assert llm_called == []

    @pytest.mark.asyncio
    async def test_contradicting_descriptions_detected(self, graph, store):
        """Low similarity + LLM verdict=contradict → contradiction stored."""
        graph.nodes["Python"] = {
            "description": "Python is fast",
            "excerpt_id": "exc-old",
            "category": "language",
        }
        detector = ContradictionDetector(
            graph, store,
            self._make_llm_fn("contradict", 0.85, "opposite claims"),
            self._make_embedding_fn({"fast": EMB_FAST, "slow": EMB_SLOW}),
        )
        result = await detector.check_entity(
            "Python", "language", "Python is slow", "exc-new",
            source="extraction",
        )
        assert len(result) == 1
        assert result[0]["verdict"] == "contradict"
        # Extraction source + contradict → auto-dismissed
        assert result[0]["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_user_source_stays_pending(self, graph, store):
        """User-sourced contradictions should stay pending, not auto-dismiss."""
        graph.nodes["Python"] = {
            "description": "Python is fast",
            "excerpt_id": "exc-old",
            "category": "language",
        }
        detector = ContradictionDetector(
            graph, store,
            self._make_llm_fn("contradict", 0.85, "user says opposite"),
            self._make_embedding_fn({"fast": EMB_FAST, "slow": EMB_SLOW}),
        )
        result = await detector.check_entity(
            "Python", "language", "Python is slow", "exc-new",
            source="user",
        )
        assert len(result) == 1
        assert result[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_ambiguous_stays_pending(self, graph, store):
        """Ambiguous verdicts always stay pending regardless of source."""
        graph.nodes["Python"] = {
            "description": "Python is fast",
            "excerpt_id": "exc-old",
            "category": "language",
        }
        detector = ContradictionDetector(
            graph, store,
            self._make_llm_fn("ambiguous", 0.5, "unclear"),
            self._make_embedding_fn({"fast": EMB_FAST, "slow": EMB_SLOW}),
        )
        result = await detector.check_entity(
            "Python", "language", "Python is slow", "exc-new",
            source="extraction",
        )
        assert len(result) == 1
        assert result[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_pending(self, graph, store):
        """get_pending returns only pending records, sorted by created_at desc."""
        now = time.time()
        await store.add("ctr-1", {
            "id": "ctr-1", "status": "pending", "created_at": now - 100,
        })
        await store.add("ctr-2", {
            "id": "ctr-2", "status": "dismissed", "created_at": now - 50,
        })
        await store.add("ctr-3", {
            "id": "ctr-3", "status": "pending", "created_at": now,
        })

        detector = ContradictionDetector(graph, store, None, None)
        pending = await detector.get_pending()
        assert len(pending) == 2
        # Most recent first
        assert pending[0]["id"] == "ctr-3"
        assert pending[1]["id"] == "ctr-1"

    @pytest.mark.asyncio
    async def test_get_count(self, graph, store):
        await store.add("ctr-1", {"status": "pending"})
        await store.add("ctr-2", {"status": "pending"})
        await store.add("ctr-3", {"status": "dismissed"})

        detector = ContradictionDetector(graph, store, None, None)
        assert await detector.get_count("pending") == 2
        assert await detector.get_count("dismissed") == 1

    @pytest.mark.asyncio
    async def test_resolve_keep_existing(self, graph, store):
        graph.nodes["Python"] = {
            "description": "Python is fast",
            "category": "language",
        }
        await store.add("ctr-1", {
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "Python",
            "status": "pending",
            "existing_value": "Python is fast",
            "new_value": "Python is slow",
        })
        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "keep_existing", note="confirmed fast")
        assert result["status"] == "resolved_kept_existing"
        # Graph should not change
        assert graph.nodes["Python"]["description"] == "Python is fast"

    @pytest.mark.asyncio
    async def test_resolve_keep_new(self, graph, store):
        graph.nodes["Python"] = {
            "description": "Python is fast",
            "category": "language",
        }
        await store.add("ctr-1", {
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "Python",
            "status": "pending",
            "existing_value": "Python is fast",
            "new_value": "Python is slow",
        })
        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "keep_new")
        assert result["status"] == "resolved_kept_new"
        # Graph should be updated with new value
        assert graph.nodes["Python"]["description"] == "Python is slow"

    @pytest.mark.asyncio
    async def test_resolve_merge(self, graph, store):
        graph.nodes["Python"] = {
            "description": "Python is fast",
            "category": "language",
        }
        await store.add("ctr-1", {
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "Python",
            "status": "pending",
            "existing_value": "Python is fast",
            "new_value": "Python can be slow for CPU tasks",
        })
        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "merge")
        assert result["status"] == "resolved_merged"
        assert "Python is fast" in graph.nodes["Python"]["description"]
        assert "Python can be slow for CPU tasks" in graph.nodes["Python"]["description"]

    @pytest.mark.asyncio
    async def test_resolve_nonexistent(self, graph, store):
        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-nonexistent", "dismiss")
        assert result is None

    @pytest.mark.asyncio
    async def test_expire_old(self, graph, store):
        old_time = time.time() - (100 * 86400)  # 100 days ago
        recent_time = time.time() - (10 * 86400)  # 10 days ago

        await store.add("ctr-old", {
            "id": "ctr-old", "status": "pending", "created_at": old_time,
        })
        await store.add("ctr-recent", {
            "id": "ctr-recent", "status": "pending", "created_at": recent_time,
        })

        detector = ContradictionDetector(graph, store, None, None)
        expired = await detector.expire_old(max_age_days=90.0)
        assert expired == 1

        old_record = await store.get_by_key("ctr-old")
        assert old_record["status"] == "dismissed"

        recent_record = await store.get_by_key("ctr-recent")
        assert recent_record["status"] == "pending"

    @pytest.mark.asyncio
    async def test_check_relationship(self, graph, store):
        """Test relationship contradiction detection."""
        graph.edges[("A", "B")] = {
            "description": "A causes B",
            "excerpt_id": "exc-old",
        }
        detector = ContradictionDetector(
            graph, store,
            self._make_llm_fn("contradict", 0.8, "opposite relationship"),
            self._make_embedding_fn({
                "causes": EMB_FAST,
                "prevents": EMB_SLOW,
            }),
        )
        result = await detector.check_relationship(
            "A", "B", "A prevents B", "exc-new",
            source_type="extraction",
        )
        assert len(result) == 1
        assert result[0]["kind"] == "relationship_description"
        assert result[0]["edge_key"] == "A||B"

    @pytest.mark.asyncio
    async def test_new_relationship_no_check(self, graph, store):
        """New relationships should not trigger any checks."""
        detector = ContradictionDetector(
            graph, store,
            self._make_llm_fn(),
            self._make_embedding_fn({}),
        )
        result = await detector.check_relationship(
            "X", "Y", "X relates to Y", "exc-1",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_hook_fires_on_contradiction(self, graph, store):
        """The hook callback should fire when a contradiction is detected."""
        graph.nodes["Python"] = {
            "description": "Python is fast",
            "excerpt_id": "exc-old",
            "category": "language",
        }
        hook_calls = []

        async def hook(record):
            hook_calls.append(record)

        detector = ContradictionDetector(
            graph, store,
            self._make_llm_fn("contradict", 0.9, "conflict"),
            self._make_embedding_fn({"fast": EMB_FAST, "slow": EMB_SLOW}),
        )
        detector.set_hook(hook)

        await detector.check_entity(
            "Python", "language", "Python is slow", "exc-new",
        )
        assert len(hook_calls) == 1
        assert hook_calls[0]["verdict"] == "contradict"

    @pytest.mark.asyncio
    async def test_llm_failure_returns_ambiguous(self, graph, store):
        """If LLM fails, verdict should default to ambiguous."""
        graph.nodes["Python"] = {
            "description": "Python is fast",
            "excerpt_id": "exc-old",
            "category": "language",
        }

        async def failing_llm(prompt):
            raise RuntimeError("LLM down")

        detector = ContradictionDetector(
            graph, store, failing_llm,
            self._make_embedding_fn({"fast": EMB_FAST, "slow": EMB_SLOW}),
        )
        result = await detector.check_entity(
            "Python", "language", "Python is slow", "exc-new",
        )
        assert len(result) == 1
        assert result[0]["verdict"] == "ambiguous"
        assert result[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_for_entity(self, graph, store):
        await store.add("ctr-1", {
            "entity_name": "Python", "status": "pending",
        })
        await store.add("ctr-2", {
            "entity_name": "Rust", "status": "pending",
        })
        await store.add("ctr-3", {
            "entity_name": "Python", "status": "dismissed",
        })

        detector = ContradictionDetector(graph, store, None, None)
        python_records = await detector.get_for_entity("Python")
        assert len(python_records) == 2
        assert all(r["entity_name"] == "Python" for r in python_records)
