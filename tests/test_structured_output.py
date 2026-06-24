"""Tests for structured output LLM methods and integration."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas import MemoryClassification
from app.taxonomy import MemoryType, classify_chunk


class FakeParsedMessage:
    def __init__(self, parsed):
        self.parsed = parsed


class FakeChoice:
    def __init__(self, parsed):
        self.message = FakeParsedMessage(parsed)


class FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class FakeResponse:
    def __init__(self, parsed):
        self.choices = [FakeChoice(parsed)]
        self.usage = FakeUsage()


class TestOpenAiStructuredCompletion:
    @pytest.mark.asyncio
    async def test_returns_pydantic_model(self):
        from app.openai_llm import OpenAiLlm

        expected = MemoryClassification(memory_type="fact", confidence=0.95)
        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.return_value = FakeResponse(expected)

        llm = OpenAiLlm.__new__(OpenAiLlm)
        llm.client = mock_client
        llm.completion_model = "gpt-4o"
        llm.usage_collector = None
        llm.query_cache_kv = MagicMock()
        llm.query_cache_kv.has = AsyncMock(return_value=False)
        llm.query_cache_kv.add = AsyncMock()

        result = await llm.get_structured_completion("classify this", MemoryClassification)
        assert isinstance(result, MemoryClassification)
        assert result.memory_type == "fact"
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_uses_cache(self):
        from app.openai_llm import OpenAiLlm

        llm = OpenAiLlm.__new__(OpenAiLlm)
        llm.client = MagicMock()
        llm.completion_model = "gpt-4o"
        llm.usage_collector = None
        llm.query_cache_kv = MagicMock()
        llm.query_cache_kv.has = AsyncMock(return_value=True)
        llm.query_cache_kv.get_by_key = AsyncMock(return_value={
            "result": {"memory_type": "decision", "confidence": 0.8},
        })

        result = await llm.get_structured_completion("classify", MemoryClassification)
        assert result.memory_type == "decision"
        llm.client.beta.chat.completions.parse.assert_not_called()


class TestAnthropicStructuredCompletion:
    @pytest.mark.asyncio
    async def test_returns_pydantic_model(self):
        from app.anthropic_llm import AnthropicLlm

        mock_content = MagicMock()
        mock_content.text = json.dumps({"memory_type": "episode", "confidence": 0.7})
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        llm = AnthropicLlm.__new__(AnthropicLlm)
        llm.client = mock_client
        llm.completion_model = "claude-3-sonnet"
        llm.usage_collector = None
        llm.query_cache_kv = MagicMock()
        llm.query_cache_kv.has = AsyncMock(return_value=False)
        llm.query_cache_kv.add = AsyncMock()

        result = await llm.get_structured_completion("classify", MemoryClassification)
        assert isinstance(result, MemoryClassification)
        assert result.memory_type == "episode"


class TestCompositeLlmStructured:
    @pytest.mark.asyncio
    async def test_delegates_to_completion_provider(self):
        from app.llm import CompositeLlm

        expected = MemoryClassification(memory_type="task", confidence=0.6)
        mock_provider = MagicMock()
        mock_provider.get_structured_completion = AsyncMock(return_value=expected)

        llm = CompositeLlm(completion_provider=mock_provider, embedding_provider=MagicMock())
        result = await llm.get_structured_completion("test", MemoryClassification)
        assert result is expected


class TestClassifyChunkStructured:
    @pytest.mark.asyncio
    async def test_uses_structured_output(self):
        expected = MemoryClassification(memory_type="fact", confidence=0.9)
        mock_llm = MagicMock()
        mock_llm.get_structured_completion = AsyncMock(return_value=expected)

        mt, conf = await classify_chunk("Python is a language", mock_llm)
        assert mt == MemoryType.FACT
        assert conf == 0.9

    @pytest.mark.asyncio
    async def test_falls_back_to_text_parsing(self):
        mock_llm = MagicMock()
        mock_llm.get_structured_completion = AsyncMock(side_effect=Exception("not supported"))
        mock_llm.get_completion = AsyncMock(
            return_value='{"memory_type": "decision", "confidence": 0.75}'
        )

        mt, conf = await classify_chunk("We decided to use Python", mock_llm)
        assert mt == MemoryType.DECISION
        assert conf == 0.75

    @pytest.mark.asyncio
    async def test_falls_back_to_default_on_failure(self):
        mock_llm = MagicMock()
        mock_llm.get_structured_completion = AsyncMock(side_effect=Exception("fail"))
        mock_llm.get_completion = AsyncMock(return_value="gibberish no json here")

        mt, conf = await classify_chunk("something", mock_llm)
        assert mt == MemoryType.REFERENCE
        assert conf == 0.5

    @pytest.mark.asyncio
    async def test_no_structured_support(self):
        """LLM without get_structured_completion falls back to text parsing."""
        mock_llm = MagicMock(spec=[])  # No attributes at all
        mock_llm.get_completion = AsyncMock(
            return_value='{"memory_type": "preference", "confidence": 0.8}'
        )

        mt, conf = await classify_chunk("I prefer dark mode", mock_llm)
        assert mt == MemoryType.PREFERENCE
        assert conf == 0.8
