import os
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

import pytest
import yaml

from app.obsidian import parse_tags
from app.tools.base import ToolResult
from app.tools.memory_tools import (
    MEMORY_TYPES,
    MemoryRelateTool,
    MemoryRecallTool,
    MemorySearchTool,
    MemoryGraphQueryTool,
    MemoryStoreTool,
    MemoryGetTool,
    ContradictionReviewTool,
    format_memory_content,
)


def _parse_yaml_frontmatter(content: str) -> dict:
    if not content.startswith("---\n"):
        return {}
    _, remainder = content.split("---\n", 1)
    frontmatter, _, _ = remainder.partition("\n---\n")
    return yaml.safe_load(frontmatter) or {}


class TestMemorySearchTool:
    @pytest.mark.asyncio
    async def test_memory_search_calls_mix_query(self, mock_smol_rag):
        tool = MemorySearchTool(mock_smol_rag)
        await tool.execute(query="test query")
        mock_smol_rag.mix_query.assert_called_once_with(
            "test query",
            memory_type=None,
            return_metadata=True,
        )

    @pytest.mark.asyncio
    async def test_memory_search_returns_result(self, mock_smol_rag):
        mock_smol_rag.mix_query = AsyncMock(return_value={
            "content": "found X",
            "excerpt_ids": ["exc-1"],
        })
        tool = MemorySearchTool(mock_smol_rag)
        result = await tool.execute(query="test")
        assert isinstance(result, ToolResult)
        assert result.content == "found X"
        assert result.metadata["accessed_excerpt_ids"] == ["exc-1"]


class TestMemoryRecallTool:
    @pytest.mark.asyncio
    async def test_topic_mode_calls_mix_query_with_episode_filter_and_bm25(self, mock_smol_rag):
        tool = MemoryRecallTool(mock_smol_rag)
        await tool.execute(query="session summary", mode="topic")
        mock_smol_rag.mix_query.assert_called_once_with(
            "session summary",
            memory_type="episode",
            include_bm25=True,
            return_metadata=True,
        )

    @pytest.mark.asyncio
    async def test_topic_mode_returns_accessed_excerpt_ids(self, mock_smol_rag):
        mock_smol_rag.mix_query = AsyncMock(return_value={
            "content": "remembered",
            "excerpt_ids": ["exc-episode-1"],
        })
        tool = MemoryRecallTool(mock_smol_rag)

        result = await tool.execute(query="session summary", mode="topic")

        assert isinstance(result, ToolResult)
        assert result.content == "remembered"
        assert result.metadata["accessed_excerpt_ids"] == ["exc-episode-1"]


class TestMemoryGraphQueryTool:
    @pytest.mark.asyncio
    async def test_memory_graph_query_returns_subgraph(self, mock_smol_rag):
        mock_smol_rag.graph.get_node = MagicMock(return_value={"category": "language", "description": "A programming language"})
        mock_smol_rag.graph.get_node_edges = MagicMock(return_value=[("Python", "FastAPI")])
        mock_smol_rag.graph.get_edge = MagicMock(return_value={"description": "used by"})
        tool = MemoryGraphQueryTool(mock_smol_rag)
        result = await tool.execute(entity="Python")
        assert "Python" in result
        assert "language" in result
        assert "FastAPI" in result

    @pytest.mark.asyncio
    async def test_memory_graph_query_unknown_entity(self, mock_smol_rag):
        mock_smol_rag.graph.get_node = MagicMock(return_value=None)
        tool = MemoryGraphQueryTool(mock_smol_rag)
        result = await tool.execute(entity="Unknown")
        assert "No entity found" in result


class TestMemoryStoreTool:
    @pytest.mark.asyncio
    async def test_memory_store_calls_ingest(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        await tool.execute(content="some knowledge")
        mock_smol_rag.ingest_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_store_writes_file(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        await tool.execute(content="some knowledge", source_id="test-id")
        file_path = os.path.join(temp_dir, "test-id.md")
        assert os.path.exists(file_path)
        with open(file_path) as f:
            assert f.read() == "some knowledge"


class TestFormatMemoryContent:
    def test_format_plain(self):
        result = format_memory_content("some content")
        assert result == "some content"

    def test_format_with_type(self):
        result = format_memory_content("body", memory_type="reference")
        assert "memory_type: reference" in result
        assert "#reference" in result

    def test_format_with_tags(self):
        result = format_memory_content("body", tags=["pricing", "saas"])
        fm = _parse_yaml_frontmatter(result)
        assert fm["tags"] == ["pricing", "saas"]
        assert "#pricing" in result
        assert "#saas" in result

    def test_format_with_type_and_tags(self):
        result = format_memory_content("body", memory_type="fact", tags=["pricing", "stripe"])
        fm = _parse_yaml_frontmatter(result)
        assert fm["memory_type"] == "fact"
        assert fm["tags"] == ["pricing", "stripe"]
        assert "#fact" in result
        assert "#pricing" in result
        assert "#stripe" in result

    def test_format_without_taxonomy_ignores_source_id(self):
        result = format_memory_content("body", source_id="src-1")
        assert result == "body"

    def test_format_created_at_is_iso(self):
        result = format_memory_content("body", memory_type="fact")
        fm = _parse_yaml_frontmatter(result)
        ts = fm["created_at"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_format_roundtrips_through_yaml_frontmatter(self):
        result = format_memory_content("body", memory_type="decision", tags=["billing"])
        fm = _parse_yaml_frontmatter(result)
        assert fm["memory_type"] == "decision"
        assert fm["tags"] == ["billing"]
        assert "created_at" in fm

    def test_format_tags_found_by_parse_tags(self):
        result = format_memory_content("body", memory_type="reference", tags=["pricing", "saas"])
        found = parse_tags(result)
        assert "reference" in found
        assert "pricing" in found
        assert "saas" in found


class TestMemoryStoreToolSchema:
    def test_schema_has_memory_type_enum(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        props = tool.parameters["properties"]
        assert props["memory_type"]["enum"] == MEMORY_TYPES

    def test_schema_has_tags_array(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        props = tool.parameters["properties"]
        assert props["tags"]["type"] == "array"
        assert props["tags"]["items"]["type"] == "string"

    def test_schema_required_unchanged(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        assert tool.parameters["required"] == ["content"]


class TestMemoryStoreToolExecuteTaxonomy:
    @pytest.mark.asyncio
    async def test_store_without_taxonomy_unchanged(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        await tool.execute(content="raw content", source_id="plain-id")
        file_path = os.path.join(temp_dir, "plain-id.md")
        with open(file_path) as f:
            assert f.read() == "raw content"
        mock_smol_rag.ingest_text.assert_called_once_with("raw content", source_id="plain-id")

    @pytest.mark.asyncio
    async def test_store_with_type_writes_frontmatter(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        await tool.execute(content="some fact", source_id="typed-id", memory_type="fact")
        file_path = os.path.join(temp_dir, "typed-id.md")
        with open(file_path) as f:
            on_disk = f.read()
        assert "memory_type: fact" in on_disk
        assert "---" in on_disk

    @pytest.mark.asyncio
    async def test_store_with_type_passes_formatted_to_ingest(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        await tool.execute(content="some fact", memory_type="reference", tags=["pricing"])
        call_args = mock_smol_rag.ingest_text.call_args
        ingested = call_args[0][0]
        assert "#reference" in ingested
        assert "#pricing" in ingested

    @pytest.mark.asyncio
    async def test_store_with_tags_only(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        await tool.execute(content="tagged content", source_id="tags-id", tags=["saas", "billing"])
        file_path = os.path.join(temp_dir, "tags-id.md")
        with open(file_path) as f:
            on_disk = f.read()
        assert "#saas" in on_disk
        assert "#billing" in on_disk
        fm = _parse_yaml_frontmatter(on_disk)
        assert fm["tags"] == ["saas", "billing"]

    @pytest.mark.asyncio
    async def test_store_return_value_unchanged(self, mock_smol_rag, temp_dir):
        tool = MemoryStoreTool(mock_smol_rag, temp_dir)
        result = await tool.execute(content="x", source_id="ret-id", memory_type="fact")
        assert result == "Stored memory: ret-id"


class TestMemoryRelateTool:
    @pytest.mark.asyncio
    async def test_relate_creates_edge(self, mock_smol_rag):
        mock_smol_rag.graph.get_node = MagicMock(return_value={"category": "entity"})
        mock_smol_rag.graph.async_add_edge = AsyncMock()
        tool = MemoryRelateTool(mock_smol_rag)
        result = await tool.execute(
            source_entity="Python", target_entity="FastAPI", relationship="used_by",
        )
        mock_smol_rag.graph.async_add_edge.assert_called_once_with(
            "Python", "FastAPI", description="used_by", keywords="used_by", weight=1.0,
        )
        assert "Python" in result
        assert "FastAPI" in result
        assert "used_by" in result

    @pytest.mark.asyncio
    async def test_relate_creates_missing_nodes(self, mock_smol_rag):
        mock_smol_rag.graph.get_node = MagicMock(return_value=None)
        mock_smol_rag.graph.async_add_node = AsyncMock()
        mock_smol_rag.graph.async_add_edge = AsyncMock()
        tool = MemoryRelateTool(mock_smol_rag)
        await tool.execute(
            source_entity="Alpha", target_entity="Beta", relationship="links_to",
        )
        assert mock_smol_rag.graph.async_add_node.call_count == 2
        mock_smol_rag.graph.async_add_edge.assert_called_once()

    @pytest.mark.asyncio
    async def test_relate_with_description(self, mock_smol_rag):
        mock_smol_rag.graph.get_node = MagicMock(return_value={"category": "entity"})
        mock_smol_rag.graph.async_add_edge = AsyncMock()
        tool = MemoryRelateTool(mock_smol_rag)
        await tool.execute(
            source_entity="A", target_entity="B",
            relationship="depends_on", description="A depends on B for auth",
        )
        mock_smol_rag.graph.async_add_edge.assert_called_once_with(
            "A", "B", description="A depends on B for auth", keywords="depends_on", weight=1.0,
        )

    def test_relate_schema(self, mock_smol_rag):
        tool = MemoryRelateTool(mock_smol_rag)
        schema = tool.to_schema()
        params = schema["function"]["parameters"]
        assert "source_entity" in params["properties"]
        assert "target_entity" in params["properties"]
        assert "relationship" in params["properties"]
        assert params["required"] == ["source_entity", "target_entity", "relationship"]


class TestMemorySearchFiltered:
    @pytest.mark.asyncio
    async def test_search_passes_memory_type(self, mock_smol_rag):
        tool = MemorySearchTool(mock_smol_rag)
        await tool.execute(query="pricing", memory_type="fact")
        mock_smol_rag.mix_query.assert_called_once_with(
            "pricing",
            memory_type="fact",
            return_metadata=True,
        )

    @pytest.mark.asyncio
    async def test_search_without_type_passes_none(self, mock_smol_rag):
        tool = MemorySearchTool(mock_smol_rag)
        await tool.execute(query="pricing")
        mock_smol_rag.mix_query.assert_called_once_with(
            "pricing",
            memory_type=None,
            return_metadata=True,
        )

    def test_search_schema_has_memory_type_enum(self, mock_smol_rag):
        tool = MemorySearchTool(mock_smol_rag)
        props = tool.parameters["properties"]
        assert "memory_type" in props
        assert props["memory_type"]["enum"] == MEMORY_TYPES


class TestToolSchemas:
    def test_tool_schemas_valid(self, mock_smol_rag, temp_dir):
        tools = [
            MemorySearchTool(mock_smol_rag),
            MemoryGraphQueryTool(mock_smol_rag),
            MemoryStoreTool(mock_smol_rag, temp_dir),
            MemoryRelateTool(mock_smol_rag),
        ]
        for tool in tools:
            schema = tool.to_schema()
            assert schema["type"] == "function"
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]


class TestToolExamples:
    """Verify all memory tools have well-formed usage examples."""

    def _all_memory_tools(self, mock_smol_rag, temp_dir):
        detector = MagicMock()
        return [
            MemorySearchTool(mock_smol_rag),
            MemoryGraphQueryTool(mock_smol_rag),
            MemoryStoreTool(mock_smol_rag, temp_dir),
            MemoryRelateTool(mock_smol_rag),
            MemoryRecallTool(mock_smol_rag),
            MemoryGetTool(mock_smol_rag),
            ContradictionReviewTool(detector),
        ]

    def test_each_memory_tool_has_examples(self, mock_smol_rag, temp_dir):
        for tool in self._all_memory_tools(mock_smol_rag, temp_dir):
            assert len(tool.examples) >= 1, f"{tool.name} should have at least 1 example"

    def test_examples_have_required_keys(self, mock_smol_rag, temp_dir):
        for tool in self._all_memory_tools(mock_smol_rag, temp_dir):
            for ex in tool.examples:
                assert "description" in ex, f"{tool.name} example missing 'description'"
                assert "arguments" in ex, f"{tool.name} example missing 'arguments'"

    def test_example_arguments_are_valid_params(self, mock_smol_rag, temp_dir):
        for tool in self._all_memory_tools(mock_smol_rag, temp_dir):
            valid_keys = set(tool.parameters.get("properties", {}).keys())
            for ex in tool.examples:
                arg_keys = set(ex["arguments"].keys())
                assert arg_keys <= valid_keys, (
                    f"{tool.name} example has invalid argument keys: {arg_keys - valid_keys}"
                )

    def test_examples_included_in_schema(self, mock_smol_rag, temp_dir):
        for tool in self._all_memory_tools(mock_smol_rag, temp_dir):
            schema = tool.to_schema()
            assert "examples" in schema["function"], f"{tool.name} schema should include examples"
            assert schema["function"]["examples"] == tool.examples
