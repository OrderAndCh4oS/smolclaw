"""End-to-end contradiction resolution flow tests.

Each test follows the full cycle: detect → store → resolve → verify KG state.
Covers all resolution types, entity/relationship/category kinds, edge cases.
"""

import time

import numpy as np
import pytest

from app.contradiction import ContradictionDetector
from app.definitions import KG_SEP
from app.tools.memory_tools import ContradictionReviewTool


# ── Test infrastructure ─────────────────────────────────────


class FakeGraph:
    """Graph mock that tracks all mutations for assertion."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self._mutation_log = []

    def get_node(self, name):
        return self.nodes.get(name)

    def get_edge(self, edge):
        return self.edges.get(edge)

    async def async_add_node(self, name, **kwargs):
        self._mutation_log.append(("add_node", name, kwargs))
        self.nodes[name] = kwargs

    async def async_add_edge(self, source, destination, **kwargs):
        self._mutation_log.append(("add_edge", source, destination, kwargs))
        self.edges[(source, destination)] = kwargs

    @property
    def mutations(self):
        return list(self._mutation_log)

    def clear_mutations(self):
        self._mutation_log.clear()


class FakeKvStore:
    def __init__(self):
        self._data = {}

    async def add(self, key, value):
        self._data[key] = value

    async def get_by_key(self, key):
        return self._data.get(key)

    async def get_all(self):
        return dict(self._data)


def _emb(values):
    v = np.array(values, dtype=np.float32)
    norm = np.linalg.norm(v)
    return (v / norm).tolist() if norm > 0 else v.tolist()


# Orthogonal embeddings to guarantee structural check flags them
EMB_A = _emb([1.0, 0.0, 0.0])
EMB_B = _emb([0.0, 1.0, 0.0])
EMB_C = _emb([0.0, 0.0, 1.0])


def _embedding_fn(mapping):
    async def fn(text):
        for key, emb in mapping.items():
            if key.lower() in text.lower():
                return emb
        return _emb([0.5, 0.5, 0.5])
    return fn


def _llm_fn(verdict, confidence=0.9, reasoning="test"):
    async def fn(prompt):
        return f'{{"verdict": "{verdict}", "confidence": {confidence}, "reasoning": "{reasoning}"}}'
    return fn


# ── Full flow: detect → resolve → verify KG ────────────────


class TestEntityDescriptionResolution:
    """Full cycle for entity description contradictions."""

    @pytest.fixture
    def graph(self):
        g = FakeGraph()
        g.nodes["Python"] = {
            "description": "Python is slow",
            "category": "language",
            "excerpt_id": "exc-old",
        }
        return g

    @pytest.fixture
    def store(self):
        return FakeKvStore()

    async def _detect(self, graph, store, verdict, source="user"):
        detector = ContradictionDetector(
            graph, store,
            _llm_fn(verdict),
            _embedding_fn({"slow": EMB_A, "fast": EMB_B}),
        )
        results = await detector.check_entity(
            "Python", "language", "Python is fast", "exc-new",
            source=source,
        )
        return detector, results

    @pytest.mark.asyncio
    async def test_detect_then_keep_existing(self, graph, store):
        """Detect contradiction → resolve keep_existing → graph unchanged."""
        detector, results = await self._detect(graph, store, "contradict")
        assert len(results) == 1
        cid = results[0]["id"]
        assert results[0]["status"] == "pending"

        graph.clear_mutations()
        resolved = await detector.resolve(cid, "keep_existing", note="slow is correct")
        assert resolved["status"] == "resolved_kept_existing"
        assert resolved["resolved_at"] is not None
        assert resolved["resolution_note"] == "slow is correct"
        # Graph must NOT have been mutated
        assert graph.mutations == []
        assert graph.nodes["Python"]["description"] == "Python is slow"

        # Store record updated
        stored = await store.get_by_key(cid)
        assert stored["status"] == "resolved_kept_existing"

    @pytest.mark.asyncio
    async def test_detect_then_keep_new(self, graph, store):
        """Detect contradiction → resolve keep_new → graph description replaced."""
        detector, results = await self._detect(graph, store, "contradict")
        cid = results[0]["id"]

        graph.clear_mutations()
        resolved = await detector.resolve(cid, "keep_new")
        assert resolved["status"] == "resolved_kept_new"
        # Graph must have been updated with new value
        assert graph.nodes["Python"]["description"] == "Python is fast"
        # Category and excerpt_id preserved
        assert graph.nodes["Python"]["category"] == "language"
        assert graph.nodes["Python"]["excerpt_id"] == "exc-old"
        # Exactly one mutation
        assert len(graph.mutations) == 1
        assert graph.mutations[0][0] == "add_node"

    @pytest.mark.asyncio
    async def test_detect_then_merge(self, graph, store):
        """Detect contradiction → resolve merge → both descriptions in graph."""
        detector, results = await self._detect(graph, store, "contradict")
        cid = results[0]["id"]

        graph.clear_mutations()
        resolved = await detector.resolve(cid, "merge")
        assert resolved["status"] == "resolved_merged"
        desc = graph.nodes["Python"]["description"]
        assert "Python is slow" in desc
        assert "Python is fast" in desc
        assert KG_SEP in desc

    @pytest.mark.asyncio
    async def test_detect_then_dismiss(self, graph, store):
        """Detect contradiction → dismiss → graph unchanged, record dismissed."""
        detector, results = await self._detect(graph, store, "contradict")
        cid = results[0]["id"]

        graph.clear_mutations()
        resolved = await detector.resolve(cid, "dismiss")
        assert resolved["status"] == "dismissed"
        assert resolved["resolved_at"] is not None
        assert graph.mutations == []
        assert graph.nodes["Python"]["description"] == "Python is slow"

    @pytest.mark.asyncio
    async def test_extraction_source_auto_dismisses(self, graph, store):
        """Extraction-sourced contradictions auto-dismiss, never reach pending."""
        detector, results = await self._detect(
            graph, store, "contradict", source="extraction",
        )
        assert len(results) == 1
        assert results[0]["status"] == "dismissed"
        assert await detector.get_count("pending") == 0

    @pytest.mark.asyncio
    async def test_pending_count_decreases_after_resolve(self, graph, store):
        """Resolving a contradiction should decrease the pending count."""
        detector, results = await self._detect(graph, store, "contradict")
        assert await detector.get_count("pending") == 1

        await detector.resolve(results[0]["id"], "keep_existing")
        assert await detector.get_count("pending") == 0


class TestRelationshipResolution:
    """Full cycle for relationship description contradictions."""

    @pytest.fixture
    def graph(self):
        g = FakeGraph()
        g.edges[("A", "B")] = {
            "description": "A depends on B",
            "keywords": "dependency",
            "weight": 1.0,
            "excerpt_id": "exc-old",
        }
        return g

    @pytest.fixture
    def store(self):
        return FakeKvStore()

    async def _detect(self, graph, store, verdict="contradict"):
        detector = ContradictionDetector(
            graph, store,
            _llm_fn(verdict),
            _embedding_fn({"depends": EMB_A, "independent": EMB_B}),
        )
        results = await detector.check_relationship(
            "A", "B", "A is independent of B", "exc-new",
            source_type="user",
        )
        return detector, results

    @pytest.mark.asyncio
    async def test_detect_relationship_contradiction(self, graph, store):
        """Relationship contradiction detected and stored with correct edge_key."""
        detector, results = await self._detect(graph, store)
        assert len(results) == 1
        assert results[0]["kind"] == "relationship_description"
        assert results[0]["edge_key"] == "A||B"
        assert results[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_relationship_keep_new(self, graph, store):
        """keep_new replaces relationship description, preserves other edge data."""
        detector, results = await self._detect(graph, store)
        cid = results[0]["id"]

        graph.clear_mutations()
        await detector.resolve(cid, "keep_new")
        edge = graph.edges[("A", "B")]
        assert edge["description"] == "A is independent of B"
        # Other edge attributes preserved
        assert edge["keywords"] == "dependency"
        assert edge["weight"] == 1.0
        assert edge["excerpt_id"] == "exc-old"

    @pytest.mark.asyncio
    async def test_relationship_merge(self, graph, store):
        """Merge appends new description to existing."""
        detector, results = await self._detect(graph, store)
        cid = results[0]["id"]

        await detector.resolve(cid, "merge")
        desc = graph.edges[("A", "B")]["description"]
        assert "A depends on B" in desc
        assert "A is independent of B" in desc
        assert KG_SEP in desc

    @pytest.mark.asyncio
    async def test_relationship_keep_existing(self, graph, store):
        """keep_existing leaves edge untouched."""
        detector, results = await self._detect(graph, store)
        cid = results[0]["id"]

        graph.clear_mutations()
        await detector.resolve(cid, "keep_existing")
        assert graph.mutations == []
        assert graph.edges[("A", "B")]["description"] == "A depends on B"


class TestCategoryResolution:
    """Entity category contradictions."""

    @pytest.mark.asyncio
    async def test_category_mismatch_detected(self):
        graph = FakeGraph()
        graph.nodes["Python"] = {
            "description": "A programming language",
            "category": "language",
            "excerpt_id": "exc-old",
        }
        store = FakeKvStore()

        ContradictionDetector(
            graph, store,
            # Description agrees, so entity_description won't fire
            _llm_fn("agree"),
            _embedding_fn({"programming": EMB_A}),
        )
        # Same description (so structural check passes as compatible)
        # but different category → should create category record
        # For this to work, the structural check must flag it first.
        # Use a dissimilar description to trigger the check:
        detector2 = ContradictionDetector(
            graph, store,
            _llm_fn("contradict"),
            _embedding_fn({"language": EMB_A, "snake": EMB_B}),
        )
        results = await detector2.check_entity(
            "Python", "animal", "A type of snake", "exc-new",
            source="user",
        )
        # Should have entity_description contradiction
        assert any(r["kind"] == "entity_description" for r in results)

        # Category mismatch also stored (check store directly)
        all_records = await store.get_all()
        cat_records = [
            r for r in all_records.values()
            if isinstance(r, dict) and r.get("kind") == "entity_category"
        ]
        assert len(cat_records) == 1
        assert cat_records[0]["existing_value"] == "language"
        assert cat_records[0]["new_value"] == "animal"

    @pytest.mark.asyncio
    async def test_category_keep_new_updates_category(self):
        graph = FakeGraph()
        graph.nodes["Python"] = {
            "description": "A programming language",
            "category": "language",
            "excerpt_id": "exc-old",
        }
        store = FakeKvStore()

        # Manually insert a category contradiction
        await store.add("cat-1", {
            "id": "cat-1",
            "kind": "entity_category",
            "entity_name": "Python",
            "status": "pending",
            "existing_value": "language",
            "new_value": "animal",
        })

        detector = ContradictionDetector(graph, store, None, None)
        await detector.resolve("cat-1", "keep_new")
        assert graph.nodes["Python"]["category"] == "animal"
        # Description should be unchanged
        assert graph.nodes["Python"]["description"] == "A programming language"


class TestMultiDescriptionResolution:
    """Entities with pipe-separated descriptions (accumulated over time)."""

    @pytest.mark.asyncio
    async def test_keep_new_replaces_all_descriptions(self):
        """keep_new should replace ALL existing descriptions with the new one."""
        graph = FakeGraph()
        graph.nodes["Python"] = {
            "description": f"Desc one{KG_SEP}Desc two{KG_SEP}Desc three",
            "category": "language",
            "excerpt_id": "exc-old",
        }
        store = FakeKvStore()
        await store.add("ctr-1", {
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "Python",
            "status": "pending",
            "existing_value": f"Desc one{KG_SEP}Desc two{KG_SEP}Desc three",
            "new_value": "The definitive description",
        })

        detector = ContradictionDetector(graph, store, None, None)
        await detector.resolve("ctr-1", "keep_new")
        assert graph.nodes["Python"]["description"] == "The definitive description"
        assert KG_SEP not in graph.nodes["Python"]["description"]

    @pytest.mark.asyncio
    async def test_merge_appends_to_existing_multi(self):
        """Merge should append to the existing pipe-separated descriptions."""
        graph = FakeGraph()
        graph.nodes["Python"] = {
            "description": f"Desc one{KG_SEP}Desc two",
            "category": "language",
            "excerpt_id": "exc-old",
        }
        store = FakeKvStore()
        await store.add("ctr-1", {
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "Python",
            "status": "pending",
            "existing_value": f"Desc one{KG_SEP}Desc two",
            "new_value": "Desc three",
        })

        detector = ContradictionDetector(graph, store, None, None)
        await detector.resolve("ctr-1", "merge")
        desc = graph.nodes["Python"]["description"]
        parts = desc.split(KG_SEP)
        assert len(parts) == 3
        assert parts[0] == "Desc one"
        assert parts[1] == "Desc two"
        assert parts[2] == "Desc three"


class TestResolutionRecordIntegrity:
    """Verify the stored record has correct metadata after resolution."""

    @pytest.mark.asyncio
    async def test_resolved_at_timestamp_set(self):
        store = FakeKvStore()
        graph = FakeGraph()
        graph.nodes["X"] = {"description": "old", "category": "thing"}
        await store.add("ctr-1", {
            "id": "ctr-1", "kind": "entity_description",
            "entity_name": "X", "status": "pending",
            "existing_value": "old", "new_value": "new",
            "resolved_at": None,
        })

        before = time.time()
        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "keep_new")
        after = time.time()

        assert result["resolved_at"] is not None
        assert before <= result["resolved_at"] <= after

    @pytest.mark.asyncio
    async def test_resolution_note_preserved(self):
        store = FakeKvStore()
        graph = FakeGraph()
        graph.nodes["X"] = {"description": "old", "category": "thing"}
        await store.add("ctr-1", {
            "id": "ctr-1", "kind": "entity_description",
            "entity_name": "X", "status": "pending",
            "existing_value": "old", "new_value": "new",
        })

        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "dismiss", note="Not relevant")
        assert result["resolution_note"] == "Not relevant"

        stored = await store.get_by_key("ctr-1")
        assert stored["resolution_note"] == "Not relevant"

    @pytest.mark.asyncio
    async def test_original_fields_preserved_after_resolve(self):
        """Resolution should not lose existing record fields."""
        store = FakeKvStore()
        graph = FakeGraph()
        graph.nodes["X"] = {"description": "old", "category": "thing"}
        await store.add("ctr-1", {
            "id": "ctr-1", "kind": "entity_description",
            "entity_name": "X", "status": "pending",
            "existing_value": "old", "new_value": "new",
            "verdict": "contradict", "confidence": 0.9,
            "source": "user", "created_at": 1000.0,
            "existing_excerpt_id": "exc-old",
            "new_excerpt_id": "exc-new",
        })

        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "keep_new")

        # All original fields intact
        assert result["verdict"] == "contradict"
        assert result["confidence"] == 0.9
        assert result["source"] == "user"
        assert result["created_at"] == 1000.0
        assert result["existing_excerpt_id"] == "exc-old"
        assert result["new_excerpt_id"] == "exc-new"


class TestResolutionEdgeCases:
    """Edge cases and error paths in resolution."""

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_returns_none(self):
        detector = ContradictionDetector(FakeGraph(), FakeKvStore(), None, None)
        assert await detector.resolve("no-such-id", "dismiss") is None

    @pytest.mark.asyncio
    async def test_resolve_already_resolved(self):
        """Resolving an already-resolved contradiction should update it again."""
        store = FakeKvStore()
        graph = FakeGraph()
        graph.nodes["X"] = {"description": "old", "category": "thing"}
        await store.add("ctr-1", {
            "id": "ctr-1", "kind": "entity_description",
            "entity_name": "X", "status": "resolved_kept_existing",
            "existing_value": "old", "new_value": "new",
            "resolved_at": 1000.0,
        })

        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "keep_new", note="changed my mind")
        assert result["status"] == "resolved_kept_new"
        assert result["resolved_at"] > 1000.0
        assert graph.nodes["X"]["description"] == "new"

    @pytest.mark.asyncio
    async def test_keep_new_entity_deleted_from_graph(self):
        """If the entity was deleted from graph between detect and resolve, no crash."""
        store = FakeKvStore()
        graph = FakeGraph()
        # Entity existed at detection time but is gone now
        await store.add("ctr-1", {
            "id": "ctr-1", "kind": "entity_description",
            "entity_name": "Gone", "status": "pending",
            "existing_value": "old", "new_value": "new",
        })

        detector = ContradictionDetector(graph, store, None, None)
        # Should not crash — node doesn't exist
        result = await detector.resolve("ctr-1", "keep_new")
        assert result["status"] == "resolved_kept_new"
        # Node was not in graph, so no mutation
        assert "Gone" not in graph.nodes

    @pytest.mark.asyncio
    async def test_keep_new_relationship_deleted_from_graph(self):
        """If the edge was deleted between detect and resolve, no crash."""
        store = FakeKvStore()
        graph = FakeGraph()
        await store.add("ctr-1", {
            "id": "ctr-1", "kind": "relationship_description",
            "edge_key": "A||B", "status": "pending",
            "existing_value": "old", "new_value": "new",
        })

        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "keep_new")
        assert result["status"] == "resolved_kept_new"
        assert ("A", "B") not in graph.edges

    @pytest.mark.asyncio
    async def test_merge_relationship_deleted_from_graph(self):
        """Merge on a deleted edge should not crash."""
        store = FakeKvStore()
        graph = FakeGraph()
        await store.add("ctr-1", {
            "id": "ctr-1", "kind": "relationship_description",
            "edge_key": "A||B", "status": "pending",
            "existing_value": "old", "new_value": "new",
        })

        detector = ContradictionDetector(graph, store, None, None)
        result = await detector.resolve("ctr-1", "merge")
        assert result["status"] == "resolved_merged"

    @pytest.mark.asyncio
    async def test_unknown_resolution_defaults_to_dismissed(self):
        store = FakeKvStore()
        await store.add("ctr-1", {
            "id": "ctr-1", "kind": "entity_description",
            "entity_name": "X", "status": "pending",
            "existing_value": "old", "new_value": "new",
        })

        detector = ContradictionDetector(FakeGraph(), store, None, None)
        result = await detector.resolve("ctr-1", "invalid_action")
        assert result["status"] == "dismissed"


class TestToolDrivenResolutionFlow:
    """Full detect → tool list → tool detail → tool resolve → verify KG."""

    @pytest.mark.asyncio
    async def test_full_tool_flow_keep_new(self):
        graph = FakeGraph()
        graph.nodes["Redis"] = {
            "description": "Redis is single-threaded",
            "category": "database",
            "excerpt_id": "exc-old",
        }
        store = FakeKvStore()

        # Phase 1: detect
        detector = ContradictionDetector(
            graph, store,
            _llm_fn("contradict", 0.88, "threading model changed"),
            _embedding_fn({"single-threaded": EMB_A, "multi-threaded": EMB_B}),
        )
        results = await detector.check_entity(
            "Redis", "database", "Redis is multi-threaded since v7", "exc-new",
            source="user",
        )
        assert len(results) == 1
        cid = results[0]["id"]

        # Phase 2: tool list
        tool = ContradictionReviewTool(detector)
        list_output = await tool.execute(action="list")
        assert cid in list_output
        assert "Redis" in list_output

        # Phase 3: tool detail
        detail_output = await tool.execute(action="detail", contradiction_id=cid)
        assert "single-threaded" in detail_output
        assert "multi-threaded" in detail_output
        assert "contradict" in detail_output

        # Phase 4: tool resolve
        resolve_output = await tool.execute(
            action="resolve",
            contradiction_id=cid,
            resolution="keep_new",
            note="Redis 7+ uses io-threads",
        )
        assert "resolved_kept_new" in resolve_output.lower()

        # Phase 5: verify KG
        assert graph.nodes["Redis"]["description"] == "Redis is multi-threaded since v7"
        assert graph.nodes["Redis"]["category"] == "database"

        # Phase 6: list should now be empty
        list_after = await tool.execute(action="list")
        assert "No pending" in list_after

    @pytest.mark.asyncio
    async def test_full_tool_flow_merge(self):
        graph = FakeGraph()
        graph.nodes["Git"] = {
            "description": "Git is a version control system",
            "category": "tool",
            "excerpt_id": "exc-old",
        }
        store = FakeKvStore()

        detector = ContradictionDetector(
            graph, store,
            _llm_fn("ambiguous", 0.6, "complementary info"),
            _embedding_fn({"version control": EMB_A, "distributed": EMB_B}),
        )
        results = await detector.check_entity(
            "Git", "tool", "Git is distributed and decentralised", "exc-new",
            source="user",
        )
        cid = results[0]["id"]

        tool = ContradictionReviewTool(detector)
        await tool.execute(
            action="resolve",
            contradiction_id=cid,
            resolution="merge",
            note="Both are true, complementary facts",
        )

        desc = graph.nodes["Git"]["description"]
        assert "Git is a version control system" in desc
        assert "Git is distributed and decentralised" in desc

    @pytest.mark.asyncio
    async def test_full_tool_flow_relationship(self):
        graph = FakeGraph()
        graph.edges[("Docker", "Kubernetes")] = {
            "description": "Docker is required by Kubernetes",
            "keywords": "dependency",
            "weight": 1.0,
            "excerpt_id": "exc-old",
        }
        store = FakeKvStore()

        detector = ContradictionDetector(
            graph, store,
            _llm_fn("contradict", 0.82, "containerd replaced docker"),
            _embedding_fn({"required": EMB_A, "optional": EMB_B}),
        )
        results = await detector.check_relationship(
            "Docker", "Kubernetes",
            "Docker is optional for Kubernetes since v1.24",
            "exc-new", source_type="user",
        )
        cid = results[0]["id"]

        tool = ContradictionReviewTool(detector)
        await tool.execute(
            action="resolve",
            contradiction_id=cid,
            resolution="keep_new",
        )

        edge = graph.edges[("Docker", "Kubernetes")]
        assert edge["description"] == "Docker is optional for Kubernetes since v1.24"
        assert edge["weight"] == 1.0  # preserved
