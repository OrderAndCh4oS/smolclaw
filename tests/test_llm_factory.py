from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.llm import detect_provider, create_llm, CompositeLlm


class TestDetectProvider:
    def test_claude_models(self):
        assert detect_provider("claude-sonnet-4-20250514") == "anthropic"
        assert detect_provider("claude-3-haiku-20240307") == "anthropic"
        assert detect_provider("claude-opus-4-20250514") == "anthropic"

    def test_openai_models(self):
        assert detect_provider("gpt-4o") == "openai"
        assert detect_provider("gpt-4.1-mini") == "openai"
        assert detect_provider("gpt-3.5-turbo") == "openai"

    def test_empty_and_none(self):
        assert detect_provider("") == "openai"
        assert detect_provider("some-other-model") == "openai"


class TestCreateLlm:
    @patch("app.llm.OpenAiLlm")
    def test_returns_openai_for_gpt(self, MockOpenAi):
        mock_instance = MagicMock()
        MockOpenAi.side_effect = lambda **kwargs: mock_instance

        result = create_llm(completion_model="gpt-4o", embedding_model="text-embedding-3-small")
        assert result is mock_instance
        MockOpenAi.assert_called_once_with(
            completion_model="gpt-4o",
            embedding_model="text-embedding-3-small",
            query_cache_kv=None,
            embedding_cache_kv=None,
            openai_api_key=None,
        )

    @patch("app.llm.OpenAiLlm")
    @patch("app.llm.AnthropicLlm")
    def test_returns_composite_for_claude_with_embedding(self, MockAnthropic, MockOpenAi):
        mock_anthropic = MagicMock()
        mock_openai = MagicMock()
        MockAnthropic.side_effect = lambda **kwargs: mock_anthropic
        MockOpenAi.side_effect = lambda **kwargs: mock_openai

        result = create_llm(completion_model="claude-sonnet-4-20250514", embedding_model="text-embedding-3-small")
        assert isinstance(result, CompositeLlm)
        assert result.completion_provider is mock_anthropic
        assert result.embedding_provider is mock_openai

    @patch("app.llm.AnthropicLlm")
    def test_returns_bare_anthropic_without_embedding(self, MockAnthropic):
        mock_anthropic = MagicMock()
        MockAnthropic.side_effect = lambda **kwargs: mock_anthropic

        result = create_llm(completion_model="claude-sonnet-4-20250514")
        assert result is mock_anthropic

    @patch("app.llm.OpenAiLlm")
    def test_returns_openai_for_none_model(self, MockOpenAi):
        mock_instance = MagicMock()
        MockOpenAi.side_effect = lambda **kwargs: mock_instance

        result = create_llm()
        assert result is mock_instance


class TestCompositeLlm:
    @pytest.mark.asyncio
    async def test_routes_completion_to_completion_provider(self):
        completion = MagicMock()
        completion.completion_model = "claude-sonnet-4-20250514"
        completion.get_completion = AsyncMock(return_value="hello")
        embedding = MagicMock()

        composite = CompositeLlm(completion, embedding)
        result = await composite.get_completion("test")
        assert result == "hello"
        completion.get_completion.assert_called_once_with("test")
        embedding.get_completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_routes_tool_completion_to_completion_provider(self):
        completion = MagicMock()
        completion.completion_model = "claude-sonnet-4-20250514"
        completion.get_tool_completion = AsyncMock(return_value={"content": "ok", "tool_calls": None, "has_tool_calls": False})
        embedding = MagicMock()

        composite = CompositeLlm(completion, embedding)
        result = await composite.get_tool_completion(messages=[])
        assert result["content"] == "ok"
        completion.get_tool_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_embedding_to_embedding_provider(self):
        completion = MagicMock()
        completion.completion_model = "claude-sonnet-4-20250514"
        embedding = MagicMock()
        embedding.get_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])

        composite = CompositeLlm(completion, embedding)
        result = await composite.get_embedding("test")
        assert result == [0.1, 0.2, 0.3]
        embedding.get_embedding.assert_called_once_with("test")
        completion.get_embedding.assert_not_called()

    @pytest.mark.asyncio
    async def test_routes_embeddings_to_embedding_provider(self):
        completion = MagicMock()
        completion.completion_model = "claude-sonnet-4-20250514"
        embedding = MagicMock()
        embedding.get_embeddings = AsyncMock(return_value=[[0.1], [0.2]])

        composite = CompositeLlm(completion, embedding)
        result = await composite.get_embeddings(["a", "b"])
        assert result == [[0.1], [0.2]]
        embedding.get_embeddings.assert_called_once()

    def test_completion_model_property(self):
        completion = MagicMock()
        completion.completion_model = "claude-sonnet-4-20250514"
        embedding = MagicMock()

        composite = CompositeLlm(completion, embedding)
        assert composite.completion_model == "claude-sonnet-4-20250514"
