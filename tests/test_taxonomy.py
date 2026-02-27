import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.taxonomy import MemoryType, MemoryMetadata, classify_chunk


class TestMemoryType:
    def test_enum_values(self):
        assert MemoryType.FACT.value == "fact"
        assert MemoryType.DECISION.value == "decision"
        assert MemoryType.PREFERENCE.value == "preference"
        assert MemoryType.EPISODE.value == "episode"
        assert MemoryType.TASK.value == "task"
        assert MemoryType.JOURNAL.value == "journal"
        assert MemoryType.REFERENCE.value == "reference"

    def test_from_string(self):
        assert MemoryType("fact") == MemoryType.FACT
        assert MemoryType("journal") == MemoryType.JOURNAL


class TestMemoryMetadata:
    def test_defaults(self):
        meta = MemoryMetadata(memory_type=MemoryType.FACT)
        assert meta.confidence == 1.0
        assert meta.importance == 0.5
        assert meta.tags == []
        assert meta.source_file is None
        assert isinstance(meta.created_at, datetime)

    def test_to_dict(self):
        meta = MemoryMetadata(
            memory_type=MemoryType.DECISION,
            confidence=0.9,
            tags=["pricing", "billing"],
            importance=0.8,
        )
        d = meta.to_dict()
        assert d["memory_type"] == "decision"
        assert d["confidence"] == 0.9
        assert d["tags"] == ["pricing", "billing"]
        assert d["importance"] == 0.8

    def test_from_dict(self):
        data = {
            "memory_type": "preference",
            "confidence": 0.95,
            "tags": ["style"],
            "importance": 0.7,
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        meta = MemoryMetadata.from_dict(data)
        assert meta.memory_type == MemoryType.PREFERENCE
        assert meta.confidence == 0.95
        assert meta.tags == ["style"]

    def test_roundtrip(self):
        original = MemoryMetadata(
            memory_type=MemoryType.EPISODE,
            confidence=0.85,
            tags=["session"],
            importance=0.6,
            source_file="/tmp/test.md",
        )
        restored = MemoryMetadata.from_dict(original.to_dict())
        assert restored.memory_type == original.memory_type
        assert restored.confidence == original.confidence
        assert restored.tags == original.tags
        assert restored.importance == original.importance


class TestClassifyChunk:
    @pytest.mark.asyncio
    async def test_classify_fact(self):
        llm = MagicMock()
        llm.get_completion = AsyncMock(
            return_value='{"memory_type": "fact", "confidence": 0.95}'
        )
        memory_type, confidence = await classify_chunk("Stripe charges 2.9% per transaction", llm)
        assert memory_type == MemoryType.FACT
        assert confidence == 0.95

    @pytest.mark.asyncio
    async def test_classify_decision(self):
        llm = MagicMock()
        llm.get_completion = AsyncMock(
            return_value='{"memory_type": "decision", "confidence": 0.8}'
        )
        memory_type, confidence = await classify_chunk("We chose Redis for caching because...", llm)
        assert memory_type == MemoryType.DECISION
        assert confidence == 0.8

    @pytest.mark.asyncio
    async def test_classify_fallback_on_bad_response(self):
        llm = MagicMock()
        llm.get_completion = AsyncMock(return_value="I don't understand")
        memory_type, confidence = await classify_chunk("some content", llm)
        assert memory_type == MemoryType.REFERENCE
        assert confidence == 0.5

    @pytest.mark.asyncio
    async def test_classify_clamps_confidence(self):
        llm = MagicMock()
        llm.get_completion = AsyncMock(
            return_value='{"memory_type": "fact", "confidence": 1.5}'
        )
        _, confidence = await classify_chunk("test", llm)
        assert confidence == 1.0

    @pytest.mark.asyncio
    async def test_classify_invalid_type_fallback(self):
        llm = MagicMock()
        llm.get_completion = AsyncMock(
            return_value='{"memory_type": "invalid_type", "confidence": 0.9}'
        )
        memory_type, confidence = await classify_chunk("test", llm)
        assert memory_type == MemoryType.REFERENCE
        assert confidence == 0.5
