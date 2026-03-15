"""Integration tests for contradiction detection in the pipeline."""

import pytest

from app.contradiction import ContradictionDetector
from app.tools.memory_tools import ContradictionReviewTool


class FakeGraph:
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
    def __init__(self):
        self._data = {}

    async def add(self, key, value):
        self._data[key] = value

    async def get_by_key(self, key):
        return self._data.get(key)

    async def get_all(self):
        return dict(self._data)


class TestContradictionReviewTool:
    """Test the ContradictionReviewTool agent interface."""

    @pytest.fixture
    def graph(self):
        return FakeGraph()

    @pytest.fixture
    def store(self):
        return FakeKvStore()

    @pytest.fixture
    def detector(self, graph, store):
        return ContradictionDetector(graph, store, None, None)

    @pytest.fixture
    def tool(self, detector):
        return ContradictionReviewTool(detector)

    @pytest.mark.asyncio
    async def test_list_empty(self, tool):
        result = await tool.execute(action="list")
        assert "No pending" in result

    @pytest.mark.asyncio
    async def test_list_with_pending(self, store, tool):
        await store.add("ctr-1", {
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "Python",
            "existing_value": "Python is fast",
            "new_value": "Python is slow",
            "verdict": "contradict",
            "confidence": 0.85,
            "status": "pending",
            "created_at": 1000.0,
        })
        result = await tool.execute(action="list")
        assert "ctr-1" in result
        assert "Python" in result
        assert "contradict" in result

    @pytest.mark.asyncio
    async def test_detail(self, store, tool):
        await store.add("ctr-1", {
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "Python",
            "existing_value": "Python is fast",
            "new_value": "Python is slow",
            "verdict": "contradict",
            "confidence": 0.85,
            "status": "pending",
            "source": "extraction",
            "resolution_note": "opposite claims",
            "existing_excerpt_id": "exc-old",
            "new_excerpt_id": "exc-new",
            "created_at": 1000.0,
            "resolved_at": None,
        })
        result = await tool.execute(action="detail", contradiction_id="ctr-1")
        assert "ctr-1" in result
        assert "entity_description" in result
        assert "Python is fast" in result

    @pytest.mark.asyncio
    async def test_detail_missing_id(self, tool):
        result = await tool.execute(action="detail")
        assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_resolve_keep_new_updates_graph(self, graph, store, tool):
        """Resolving with keep_new should update the knowledge graph."""
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
        result = await tool.execute(
            action="resolve",
            contradiction_id="ctr-1",
            resolution="keep_new",
            note="corrected",
        )
        assert "resolved_kept_new" in result.lower()
        assert graph.nodes["Python"]["description"] == "Python is slow"

    @pytest.mark.asyncio
    async def test_resolve_dismiss(self, store, tool):
        await store.add("ctr-1", {
            "id": "ctr-1",
            "kind": "entity_description",
            "entity_name": "Python",
            "status": "pending",
            "existing_value": "old",
            "new_value": "new",
        })
        result = await tool.execute(
            action="resolve",
            contradiction_id="ctr-1",
            resolution="dismiss",
        )
        assert "dismissed" in result.lower()

    @pytest.mark.asyncio
    async def test_resolve_missing_params(self, tool):
        result = await tool.execute(action="resolve")
        assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_resolve_nonexistent(self, tool):
        result = await tool.execute(
            action="resolve",
            contradiction_id="ctr-nope",
            resolution="dismiss",
        )
        assert "No contradiction" in result


class TestContextAssemblyContradictionNudge:
    """Test that pending contradictions appear in system prompt."""

    @pytest.mark.asyncio
    async def test_nudge_appears_when_pending(self):
        """When pending contradictions exist, build_messages_async should include a nudge."""
        # We test the logic directly rather than full assembly (which needs SmolRAG)
        from app.contradiction import ContradictionDetector

        store = FakeKvStore()
        await store.add("ctr-1", {"status": "pending"})
        await store.add("ctr-2", {"status": "pending"})

        detector = ContradictionDetector(FakeGraph(), store, None, None)
        count = await detector.get_count("pending")
        assert count == 2

    @pytest.mark.asyncio
    async def test_no_nudge_when_clean(self):
        store = FakeKvStore()
        detector = ContradictionDetector(FakeGraph(), store, None, None)
        count = await detector.get_count("pending")
        assert count == 0


class TestLifecycleExpiry:
    """Test contradiction expiry lifecycle hook."""

    @pytest.mark.asyncio
    async def test_expiry_hook(self):
        from app.lifecycle_hooks import ContradictionExpiryHook
        import time

        store = FakeKvStore()
        old_time = time.time() - (100 * 86400)
        await store.add("ctr-old", {
            "id": "ctr-old", "status": "pending", "created_at": old_time,
        })
        await store.add("ctr-new", {
            "id": "ctr-new", "status": "pending", "created_at": time.time(),
        })

        detector = ContradictionDetector(FakeGraph(), store, None, None)
        hook = ContradictionExpiryHook(detector, max_age_days=90.0)
        await hook({})

        old = await store.get_by_key("ctr-old")
        assert old["status"] == "dismissed"

        new = await store.get_by_key("ctr-new")
        assert new["status"] == "pending"
