import os
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent_factory import ChildAgentFactory
from app.journal import generate_journal
from app.session import Session


@pytest.fixture
def journal_session():
    session = Session(key="test-journal")
    session.add_message({"role": "user", "content": "What is Python?"})
    session.add_message({"role": "assistant", "content": "Python is a high-level programming language."})
    session.add_message({"role": "user", "content": "What about FastAPI?"})
    session.add_message({"role": "assistant", "content": "FastAPI is a modern web framework for Python."})
    return session


@pytest.fixture
def mock_journal_llm():
    llm = MagicMock()
    llm.get_completion = AsyncMock(
        return_value="I explored Python and FastAPI today. The key insight was how well they work together."
    )
    return llm


class TestGenerateJournal:
    @pytest.mark.asyncio
    async def test_generates_journal_content(self, journal_session, mock_journal_llm, mock_smol_rag):
        with tempfile.TemporaryDirectory() as td:
            result = await generate_journal(journal_session, mock_journal_llm, mock_smol_rag, td)
            assert "Python" in result or "FastAPI" in result
            mock_journal_llm.get_completion.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_writes_file_to_memory_dir(self, journal_session, mock_journal_llm, mock_smol_rag):
        with tempfile.TemporaryDirectory() as td:
            await generate_journal(journal_session, mock_journal_llm, mock_smol_rag, td)
            files = os.listdir(td)
            assert len(files) == 1
            assert files[0].startswith("journal-")
            assert files[0].endswith(".md")

    @pytest.mark.asyncio
    async def test_file_has_frontmatter(self, journal_session, mock_journal_llm, mock_smol_rag):
        with tempfile.TemporaryDirectory() as td:
            await generate_journal(journal_session, mock_journal_llm, mock_smol_rag, td)
            files = os.listdir(td)
            with open(os.path.join(td, files[0])) as f:
                content = f.read()
            assert "memory_type: journal" in content
            assert "session_reflection" in content

    @pytest.mark.asyncio
    async def test_ingests_into_smol_rag(self, journal_session, mock_journal_llm, mock_smol_rag):
        with tempfile.TemporaryDirectory() as td:
            await generate_journal(journal_session, mock_journal_llm, mock_smol_rag, td)
            mock_smol_rag.remove_document_by_source.assert_awaited_once_with("journal-test-journal")
            mock_smol_rag.ingest_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_session_returns_empty(self, mock_journal_llm, mock_smol_rag):
        empty_session = Session(key="empty")
        with tempfile.TemporaryDirectory() as td:
            result = await generate_journal(empty_session, mock_journal_llm, mock_smol_rag, td)
            assert result == ""
            mock_journal_llm.get_completion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_tool_messages(self, mock_journal_llm, mock_smol_rag):
        session = Session(key="with-tools")
        session.add_message({"role": "user", "content": "Hello"})
        session.add_message({"role": "assistant", "content": "Hi there"})
        session.add_message({"role": "tool", "content": "tool output"})
        with tempfile.TemporaryDirectory() as td:
            await generate_journal(session, mock_journal_llm, mock_smol_rag, td)
            # The prompt should only include user/assistant messages
            call_args = mock_journal_llm.get_completion.call_args[0][0]
            assert "tool output" not in call_args

    @pytest.mark.asyncio
    async def test_repeated_generation_overwrites_same_session_file(self, journal_session, mock_journal_llm, mock_smol_rag):
        with tempfile.TemporaryDirectory() as td:
            await generate_journal(journal_session, mock_journal_llm, mock_smol_rag, td)
            await generate_journal(journal_session, mock_journal_llm, mock_smol_rag, td)

            assert sorted(os.listdir(td)) == ["journal-test-journal.md"]
            assert mock_smol_rag.remove_document_by_source.await_count == 2

    @pytest.mark.asyncio
    async def test_generated_child_session_key_writes_portable_filename(self, mock_journal_llm, mock_smol_rag):
        factory = ChildAgentFactory(
            master_registry=MagicMock(),
            smol_rag=MagicMock(),
            session_manager=MagicMock(),
            parent_session_key="parent:root",
        )
        child_key = factory.make_session_key("worker", "spawn-sub-1")
        session = Session(key=child_key)
        session.add_message({"role": "user", "content": "Hello"})
        session.add_message({"role": "assistant", "content": "Hi there"})

        with tempfile.TemporaryDirectory() as td:
            await generate_journal(session, mock_journal_llm, mock_smol_rag, td)
            expected = f"journal-{child_key}.md"
            assert sorted(os.listdir(td)) == [expected]
            assert ":" not in expected
