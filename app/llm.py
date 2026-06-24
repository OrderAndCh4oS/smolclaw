from typing import Any, Dict, List
import inspect

from app.anthropic_llm import AnthropicLlm
from app.definitions import COMPLETION_MODEL
from app.openai_llm import OpenAiLlm

class CompositeLlm:
    def __init__(self, completion_provider, embedding_provider):
        self.completion_provider = completion_provider
        self.embedding_provider = embedding_provider

    @property
    def completion_model(self):
        return self.completion_provider.completion_model

    @property
    def reasoning_effort(self):
        return getattr(self.completion_provider, "reasoning_effort", None)

    @property
    def usage_collector(self):
        return getattr(self.completion_provider, "usage_collector", None)

    @usage_collector.setter
    def usage_collector(self, collector):
        if hasattr(self.completion_provider, "usage_collector"):
            self.completion_provider.usage_collector = collector
        if (self.embedding_provider
                and self.embedding_provider is not self.completion_provider
                and hasattr(self.embedding_provider, "usage_collector")):
            self.embedding_provider.usage_collector = collector

    async def get_completion(self, *args, **kwargs) -> str:
        return await self.completion_provider.get_completion(*args, **kwargs)

    async def get_tool_completion(self, *args, **kwargs) -> Dict[str, Any]:
        return await self.completion_provider.get_tool_completion(*args, **kwargs)

    async def get_structured_completion(self, *args, **kwargs):
        return await self.completion_provider.get_structured_completion(*args, **kwargs)

    async def get_embedding(self, *args, **kwargs) -> List[float]:
        return await self.embedding_provider.get_embedding(*args, **kwargs)

    async def get_embeddings(self, *args, **kwargs) -> List[List[float]]:
        return await self.embedding_provider.get_embeddings(*args, **kwargs)

    async def close(self):
        seen = set()
        for provider in (self.completion_provider, self.embedding_provider):
            if provider is None or id(provider) in seen:
                continue
            seen.add(id(provider))
            close_fn = getattr(provider, "close", None)
            if not callable(close_fn):
                continue
            result = close_fn()
            if inspect.isawaitable(result):
                await result


def detect_provider(model: str) -> str:
    if model and model.startswith("claude-"):
        return "anthropic"
    return "openai"


def create_llm(completion_model=None, embedding_model=None, **kwargs):
    completion_model = completion_model or COMPLETION_MODEL
    provider = detect_provider(completion_model)
    embedding_provider = detect_provider(embedding_model or "") if embedding_model else provider

    if provider == "anthropic":
        anthropic_llm = AnthropicLlm(
            completion_model=completion_model,
            query_cache_kv=kwargs.get("query_cache_kv"),
            db_path=kwargs.get("db_path"),
        )

        if embedding_model:
            embed_llm = _provider_for_embedding(
                embedding_provider,
                embedding_model,
                query_cache_kv=kwargs.get("query_cache_kv"),
                embedding_cache_kv=kwargs.get("embedding_cache_kv"),
                openai_api_key=kwargs.get("openai_api_key"),
                db_path=kwargs.get("db_path"),
            )
            return CompositeLlm(
                completion_provider=anthropic_llm,
                embedding_provider=embed_llm,
            )

        return anthropic_llm

    openai_llm = OpenAiLlm(
        completion_model=completion_model,
        embedding_model=embedding_model if embedding_provider == "openai" else None,
        query_cache_kv=kwargs.get("query_cache_kv"),
        embedding_cache_kv=kwargs.get("embedding_cache_kv"),
        openai_api_key=kwargs.get("openai_api_key"),
        db_path=kwargs.get("db_path"),
    )
    if embedding_model and embedding_provider != "openai":
        return CompositeLlm(
            completion_provider=openai_llm,
            embedding_provider=_provider_for_embedding(
                embedding_provider,
                embedding_model,
                query_cache_kv=kwargs.get("query_cache_kv"),
                embedding_cache_kv=kwargs.get("embedding_cache_kv"),
                openai_api_key=kwargs.get("openai_api_key"),
                db_path=kwargs.get("db_path"),
            ),
        )
    return openai_llm


def _provider_for_embedding(provider: str, embedding_model: str, **kwargs):
    return OpenAiLlm(
        embedding_model=embedding_model,
        query_cache_kv=kwargs.get("query_cache_kv"),
        embedding_cache_kv=kwargs.get("embedding_cache_kv"),
        openai_api_key=kwargs.get("openai_api_key"),
        db_path=kwargs.get("db_path"),
    )
