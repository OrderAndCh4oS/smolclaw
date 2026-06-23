import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.factory import build_tool_registry
from app.tools.permissions import PermissionMiddleware
from app.tools.research_sources import ResearchSourceStoreTool
from app.workspace import WorkspaceContext


class TestResearchSourceStoreTool:
    @pytest.mark.asyncio
    async def test_stores_plain_text_source_note_and_indexes_it(self, temp_dir):
        smol_rag = MagicMock()
        smol_rag.ingest_text = AsyncMock()
        tool = ResearchSourceStoreTool(temp_dir, smol_rag=smol_rag)

        result = await tool.execute(
            url="https://example.com/paper",
            title="Agent Harness Paper",
            topic="coding harnesses",
            summary="Supports the architecture decision.",
            extracted_text="Relevant plain text from the page.",
            related_urls=["https://example.com/appendix"],
            source_id="agent harness paper",
        )

        path = os.path.join(temp_dir, "agent-harness-paper.txt")
        assert result == "Stored research source: agent-harness-paper.txt"
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "Title: Agent Harness Paper" in content
        assert "URL: https://example.com/paper" in content
        assert "Topic: coding harnesses" in content
        assert "Summary:\nSupports the architecture decision." in content
        assert "- https://example.com/appendix" in content
        assert "Extracted text:\nRelevant plain text from the page." in content
        smol_rag.ingest_text.assert_awaited_once()
        assert smol_rag.ingest_text.await_args.kwargs["source_id"] == "research/agent-harness-paper"
        assert smol_rag.ingest_text.await_args.kwargs["source"] == "research"

    @pytest.mark.asyncio
    async def test_rejects_invalid_urls(self, temp_dir):
        tool = ResearchSourceStoreTool(temp_dir)

        result = await tool.execute(url="file:///etc/passwd", summary="bad")

        assert result == "Error: invalid URL: file:///etc/passwd"
        assert os.listdir(temp_dir) == []

    @pytest.mark.asyncio
    async def test_can_skip_ingestion(self, temp_dir):
        smol_rag = MagicMock()
        smol_rag.ingest_text = AsyncMock()
        tool = ResearchSourceStoreTool(temp_dir, smol_rag=smol_rag)

        await tool.execute(
            url="https://example.com/source",
            summary="Useful.",
            source_id="source",
            ingest=False,
        )

        smol_rag.ingest_text.assert_not_awaited()


class TestResearchSourceStoreWiring:
    def test_memory_capability_registers_research_source_store(self, mock_smol_rag, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

        registry = build_tool_registry(
            smol_rag=mock_smol_rag,
            workspace=workspace,
            transport="direct",
            capability_names=["memory"],
        )

        assert "research_source_store" in registry._tools

    @pytest.mark.asyncio
    async def test_research_permission_mode_allows_source_archive(self, temp_dir):
        tool = ResearchSourceStoreTool(temp_dir)
        middleware = PermissionMiddleware("research")

        async def next_fn(_tool, _kwargs):
            return "allowed"

        result = await middleware(tool, {"url": "https://example.com", "summary": "source"}, next_fn)

        assert result == "allowed"
