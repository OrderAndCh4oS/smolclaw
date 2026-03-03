from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.session import Session
from app.session_export_hook import SessionExportHook


def _make_session(key="export-test"):
    s = Session(key=key)
    s.add_message({"role": "user", "content": "hello"})
    s.add_message({"role": "assistant", "content": "hi there"})
    return s


class TestSessionExportHook:
    @pytest.mark.asyncio
    async def test_calls_journal_and_index(self, mock_smol_rag, temp_dir):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        mock_llm = MagicMock()
        mock_llm.get_completion = AsyncMock(return_value="Journal reflection text")

        hook = SessionExportHook(
            smol_rag=mock_smol_rag,
            llm=mock_llm,
            memory_dir=temp_dir,
        )
        session = _make_session()
        await hook({"session": session})

        # Both journal and indexer should have called ingest_text
        assert mock_smol_rag.ingest_text.call_count == 2

    @pytest.mark.asyncio
    async def test_disabled_hook_does_nothing(self, mock_smol_rag, temp_dir):
        hook = SessionExportHook(
            smol_rag=mock_smol_rag,
            memory_dir=temp_dir,
            enabled=False,
        )
        session = _make_session()
        await hook({"session": session})
        mock_smol_rag.ingest_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_session_in_context(self, mock_smol_rag, temp_dir):
        hook = SessionExportHook(smol_rag=mock_smol_rag, memory_dir=temp_dir)
        await hook({})  # no "session" key — should not raise
        mock_smol_rag.ingest_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_journal_failure_does_not_block_index(self, mock_smol_rag, temp_dir):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        mock_llm = MagicMock()
        mock_llm.get_completion = AsyncMock(side_effect=Exception("LLM down"))

        hook = SessionExportHook(
            smol_rag=mock_smol_rag,
            llm=mock_llm,
            memory_dir=temp_dir,
        )
        session = _make_session()
        await hook({"session": session})

        # Journal fails, but indexing should still happen
        mock_smol_rag.ingest_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_journal_only(self, mock_smol_rag, temp_dir):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        mock_llm = MagicMock()
        mock_llm.get_completion = AsyncMock(return_value="journal text")

        hook = SessionExportHook(
            smol_rag=mock_smol_rag,
            llm=mock_llm,
            memory_dir=temp_dir,
            generate_journal=False,
        )
        session = _make_session()
        await hook({"session": session})

        # Only indexing should happen, not journal
        assert mock_smol_rag.ingest_text.call_count == 1

    @pytest.mark.asyncio
    async def test_skip_index_only(self, mock_smol_rag, temp_dir):
        mock_llm = MagicMock()
        mock_llm.get_completion = AsyncMock(return_value="journal text")

        hook = SessionExportHook(
            smol_rag=mock_smol_rag,
            llm=mock_llm,
            memory_dir=temp_dir,
            index_session=False,
        )
        session = _make_session()
        await hook({"session": session})

        # Only journal should happen
        assert mock_smol_rag.ingest_text.call_count == 1

    @pytest.mark.asyncio
    async def test_no_llm_skips_journal(self, mock_smol_rag, temp_dir):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        hook = SessionExportHook(
            smol_rag=mock_smol_rag,
            llm=None,
            memory_dir=temp_dir,
        )
        session = _make_session()
        await hook({"session": session})

        # Without LLM, journal is skipped, only indexing happens
        assert mock_smol_rag.ingest_text.call_count == 1
