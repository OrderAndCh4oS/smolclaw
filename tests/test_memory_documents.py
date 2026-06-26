import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory_documents import MemoryDocumentService
from app.storage_paths import safe_storage_stem


class TestMemoryDocumentService:
    @pytest.mark.asyncio
    async def test_memory_source_id_is_used_for_file_and_ingest(self, temp_dir, mock_smol_rag):
        service = MemoryDocumentService(mock_smol_rag, memory_dir=temp_dir)

        stored = await service.store_document(
            "remember this",
            kind="memory",
            source_id=None,
        )

        assert stored.source_id.startswith("mem-")
        assert stored.path == os.path.realpath(os.path.join(temp_dir, f"{stored.source_id}.md"))
        assert os.path.exists(stored.path)
        mock_smol_rag.remove_document_by_source.assert_awaited_once_with(stored.source_id)
        mock_smol_rag.ingest_text.assert_awaited_once_with("remember this", source_id=stored.source_id)

    @pytest.mark.asyncio
    async def test_source_id_traversal_is_normalized(self, temp_dir, mock_smol_rag):
        service = MemoryDocumentService(mock_smol_rag, memory_dir=temp_dir)

        stored = await service.store_document(
            "contained",
            kind="memory",
            source_id="../../outside",
        )

        assert stored.source_id != "../../outside"
        assert os.path.commonpath([os.path.realpath(temp_dir), stored.path]) == os.path.realpath(temp_dir)
        assert not os.path.exists(os.path.join(temp_dir, "..", "..", "outside.md"))
        mock_smol_rag.ingest_text.assert_awaited_once_with("contained", source_id=stored.source_id)

    @pytest.mark.asyncio
    async def test_replacing_source_removes_old_index_first(self, temp_dir, mock_smol_rag):
        service = MemoryDocumentService(mock_smol_rag, memory_dir=temp_dir)

        await service.store_document("first", kind="memory", source_id="stable")
        await service.store_document("second", kind="memory", source_id="stable")

        assert mock_smol_rag.remove_document_by_source.await_count == 2
        assert mock_smol_rag.ingest_text.await_count == 2
        with open(os.path.join(temp_dir, "stable.md")) as handle:
            assert handle.read() == "second"

    @pytest.mark.asyncio
    async def test_research_source_id_uses_prefix_but_flat_file(self, temp_dir):
        smol_rag = MagicMock()
        smol_rag.remove_document_by_source = AsyncMock()
        smol_rag.ingest_text = AsyncMock()
        service = MemoryDocumentService(smol_rag, research_dir=temp_dir)

        stored = await service.store_document(
            "source note",
            kind="research",
            source_id="Agent Harness Paper",
            extension=".txt",
            source="research",
        )

        expected_stem = safe_storage_stem("Agent Harness Paper")
        assert stored.source_id == f"research/{expected_stem}"
        assert stored.path == os.path.realpath(os.path.join(temp_dir, f"{expected_stem}.txt"))
        smol_rag.ingest_text.assert_awaited_once_with(
            "source note",
            source_id=stored.source_id,
            source="research",
        )

    @pytest.mark.asyncio
    async def test_external_ingest_does_not_write_file(self, temp_dir, mock_smol_rag):
        service = MemoryDocumentService(
            mock_smol_rag,
            memory_dir=temp_dir,
            ingestion_jobs_dir=os.path.join(temp_dir, "jobs"),
        )

        stored = await service.ingest_external_text("external", source_id="/tmp/source.md")

        assert stored.path is None
        assert not [name for name in os.listdir(temp_dir) if name.endswith(".md")]
        jobs = service.list_ingestion_jobs()
        assert len(jobs) == 1
        assert jobs[0].source_id == stored.source_id
        assert jobs[0].status == "complete"
        mock_smol_rag.ingest_text.assert_awaited_once_with("external", source_id=stored.source_id)

    @pytest.mark.asyncio
    async def test_failed_ingestion_job_can_be_repaired(self, temp_dir):
        smol_rag = MagicMock()
        smol_rag.remove_document_by_source = AsyncMock()
        smol_rag.ingest_text = AsyncMock(side_effect=[RuntimeError("index unavailable"), None])
        service = MemoryDocumentService(
            smol_rag,
            memory_dir=temp_dir,
            ingestion_jobs_dir=os.path.join(temp_dir, "jobs"),
        )

        with pytest.raises(RuntimeError, match="index unavailable"):
            await service.store_document("repair me", kind="memory", source_id="stable")

        failed = service.list_ingestion_jobs(status="failed")
        assert len(failed) == 1
        assert failed[0].stage == "failed"
        assert failed[0].error == "index unavailable"

        repaired = await service.repair_ingestion_job(failed[0].job_id)

        assert repaired.source_id == "stable"
        assert smol_rag.ingest_text.await_count == 2
        assert service.list_ingestion_jobs(status="complete")[0].source_id == "stable"
