import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.session import Session, SessionManager
from app.session_indexer import (
    parse_session_content,
    index_session,
    index_all_sessions,
)


def _make_session(key="test-session", messages=None):
    s = Session(key=key)
    for msg in (messages or []):
        s.add_message(msg)
    return s


class TestParseSessionContent:
    def test_concatenates_user_and_assistant(self):
        session = _make_session(messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "how are you?"},
        ])
        result = parse_session_content(session)
        assert "user: hello" in result
        assert "assistant: hi there" in result
        assert "user: how are you?" in result

    def test_skips_tool_calls(self):
        session = _make_session(messages=[
            {"role": "user", "content": "search for X"},
            {"role": "tool", "tool_call_id": "tc1", "content": "tool result"},
            {"role": "assistant", "content": "I found X"},
        ])
        result = parse_session_content(session)
        assert "tool result" not in result
        assert "user: search for X" in result
        assert "assistant: I found X" in result

    def test_empty_session(self):
        session = _make_session(messages=[])
        result = parse_session_content(session)
        assert result == ""

    def test_skips_empty_content(self):
        session = _make_session(messages=[
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "response"},
        ])
        result = parse_session_content(session)
        assert "user:" not in result
        assert "assistant: response" in result


class TestIndexSession:
    @pytest.mark.asyncio
    async def test_indexes_session_into_smolrag(self, mock_smol_rag):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        session = _make_session(messages=[
            {"role": "user", "content": "tell me about Python"},
            {"role": "assistant", "content": "Python is a programming language"},
        ])
        source_id = await index_session(session, mock_smol_rag)
        assert source_id == "session-test-session"
        mock_smol_rag.remove_document_by_source.assert_called_once_with("session-test-session")
        mock_smol_rag.ingest_text.assert_called_once()
        call_args = mock_smol_rag.ingest_text.call_args
        assert call_args[1]["source_id"] == "session-test-session"
        ingested = call_args[0][0]
        assert "#episode" in ingested
        assert "#session" in ingested

    @pytest.mark.asyncio
    async def test_empty_session_returns_empty(self, mock_smol_rag):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        session = _make_session(messages=[])
        source_id = await index_session(session, mock_smol_rag)
        assert source_id == ""
        mock_smol_rag.ingest_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_to_memory_dir(self, mock_smol_rag, temp_dir):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        session = _make_session(messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ])
        await index_session(session, mock_smol_rag, memory_dir=temp_dir)
        expected = os.path.join(temp_dir, "session-test-session.md")
        assert os.path.exists(expected)
        with open(expected) as f:
            content = f.read()
        assert "#episode" in content

    @pytest.mark.asyncio
    async def test_extracts_topics_with_llm(self, mock_smol_rag):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        mock_llm = MagicMock()
        mock_llm.get_completion = AsyncMock(return_value='{"topics": ["python", "coding"]}')
        session = _make_session(messages=[
            {"role": "user", "content": "teach me python"},
            {"role": "assistant", "content": "sure, let's start"},
        ])
        await index_session(session, mock_smol_rag, llm=mock_llm)
        ingested = mock_smol_rag.ingest_text.call_args[0][0]
        assert "#python" in ingested
        assert "#coding" in ingested


class TestIndexAllSessions:
    @pytest.mark.asyncio
    async def test_indexes_all_jsonl_files(self, mock_smol_rag, temp_dir):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        # Create two session files
        for key in ("sess1", "sess2"):
            path = os.path.join(temp_dir, f"{key}.jsonl")
            with open(path, "w") as f:
                meta = {"key": key, "last_consolidated": 0}
                f.write(json.dumps(meta) + "\n")
                f.write(json.dumps({"role": "user", "content": f"hello from {key}"}) + "\n")
                f.write(json.dumps({"role": "assistant", "content": f"hi {key}"}) + "\n")

        results = await index_all_sessions(temp_dir, mock_smol_rag)
        assert len(results) == 2
        assert "sess1" in results
        assert "sess2" in results
        assert mock_smol_rag.ingest_text.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_empty_sessions(self, mock_smol_rag, temp_dir):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        path = os.path.join(temp_dir, "empty.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"key": "empty", "last_consolidated": 0}) + "\n")

        results = await index_all_sessions(temp_dir, mock_smol_rag)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_ignores_non_jsonl_files(self, mock_smol_rag, temp_dir):
        mock_smol_rag.remove_document_by_source = AsyncMock()
        # Create a non-jsonl file
        with open(os.path.join(temp_dir, "notes.txt"), "w") as f:
            f.write("not a session")
        # Create a valid session
        path = os.path.join(temp_dir, "valid.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"key": "valid", "last_consolidated": 0}) + "\n")
            f.write(json.dumps({"role": "user", "content": "hello"}) + "\n")

        results = await index_all_sessions(temp_dir, mock_smol_rag)
        assert len(results) == 1
        assert "valid" in results
