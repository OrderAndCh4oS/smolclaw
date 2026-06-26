from typing import Any, Dict, List
import inspect

from app.anthropic_llm import AnthropicLlm
from app.definitions import COMPLETION_MODEL
from app.llm_base import CompletionAdapter, EmbeddingAdapter, LlmAdapter
from app.model_defaults import DEFAULT_EMBEDDING_MODEL
from app.openai_llm import OpenAiLlm
from app.voyage_llm import VoyageEmbeddingLlm

class CompositeLlm:
    def __init__(self, completion_provider: CompletionAdapter, embedding_provider: EmbeddingAdapter):
        self.completion_provider = completion_provider
        self.embedding_provider = embedding_provider

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

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


def detect_provider(model: str | None, provider: str | None = None) -> str:
    if provider:
        return provider
    if model and model.startswith("claude-"):
        return "anthropic"
    if model and model.startswith("voyage-"):
        return "voyage"
    return "openai"


def create_llm(
    completion_model=None,
    embedding_model=None,
    *,
    provider: str | None = None,
    embedding_provider: str | None = None,
    require_embeddings: bool = False,
    openai_factory=None,
    anthropic_factory=None,
    voyage_factory=None,
    **kwargs,
) -> LlmAdapter | CompletionAdapter:
    completion_model = completion_model or COMPLETION_MODEL
    provider = detect_provider(completion_model, provider)
    if require_embeddings and not embedding_model:
        embedding_model = DEFAULT_EMBEDDING_MODEL
    embedding_provider = detect_provider(
        embedding_model or "",
        embedding_provider,
    ) if embedding_model else provider

    if provider == "anthropic":
        anthropic_factory = anthropic_factory or AnthropicLlm
        anthropic_llm = anthropic_factory(
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
                voyage_api_key=kwargs.get("voyage_api_key"),
                db_path=kwargs.get("db_path"),
                openai_factory=openai_factory,
                voyage_factory=voyage_factory,
            )
            return CompositeLlm(
                completion_provider=anthropic_llm,
                embedding_provider=embed_llm,
            )

        return anthropic_llm

    if provider != "openai":
        raise ValueError(f"Unsupported LLM provider: {provider}")

    openai_factory = openai_factory or OpenAiLlm
    openai_llm = openai_factory(
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
                voyage_api_key=kwargs.get("voyage_api_key"),
                db_path=kwargs.get("db_path"),
                openai_factory=openai_factory,
                voyage_factory=voyage_factory,
            ),
        )
    return openai_llm


def _provider_for_embedding(provider: str, embedding_model: str, **kwargs):
    if provider == "openai":
        openai_factory = kwargs.get("openai_factory") or OpenAiLlm
        return openai_factory(
            embedding_model=embedding_model,
            query_cache_kv=kwargs.get("query_cache_kv"),
            embedding_cache_kv=kwargs.get("embedding_cache_kv"),
            openai_api_key=kwargs.get("openai_api_key"),
            db_path=kwargs.get("db_path"),
        )
    if provider == "voyage":
        voyage_factory = kwargs.get("voyage_factory") or VoyageEmbeddingLlm
        return voyage_factory(
            embedding_model=embedding_model,
            embedding_cache_kv=kwargs.get("embedding_cache_kv"),
            voyage_api_key=kwargs.get("voyage_api_key"),
            db_path=kwargs.get("db_path"),
        )
    raise ValueError(f"Unsupported embedding provider: {provider}")
