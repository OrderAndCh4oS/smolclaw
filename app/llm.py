from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from app.anthropic_llm import AnthropicLlm
from app.openai_llm import OpenAiLlm


@runtime_checkable
class LlmProvider(Protocol):
    completion_model: str

    async def get_completion(self, query: str, model: Optional[str] = None, context: str = "",
                             use_cache: bool = True) -> str: ...

    async def get_tool_completion(self, messages: List[Dict[str, str]], tools: Optional[List[dict]] = None,
                                  model: Optional[str] = None) -> Dict[str, Any]: ...

    async def get_embedding(self, content: Any, model: Optional[str] = None) -> List[float]: ...

    async def get_embeddings(self, contents: List[Any], model: Optional[str] = None) -> List[List[float]]: ...


class CompositeLlm:
    def __init__(self, completion_provider, embedding_provider):
        self.completion_provider = completion_provider
        self.embedding_provider = embedding_provider

    @property
    def completion_model(self):
        return self.completion_provider.completion_model

    async def get_completion(self, *args, **kwargs) -> str:
        return await self.completion_provider.get_completion(*args, **kwargs)

    async def get_tool_completion(self, *args, **kwargs) -> Dict[str, Any]:
        return await self.completion_provider.get_tool_completion(*args, **kwargs)

    async def get_embedding(self, *args, **kwargs) -> List[float]:
        return await self.embedding_provider.get_embedding(*args, **kwargs)

    async def get_embeddings(self, *args, **kwargs) -> List[List[float]]:
        return await self.embedding_provider.get_embeddings(*args, **kwargs)


def detect_provider(model: str) -> str:
    if model and model.startswith("claude-"):
        return "anthropic"
    return "openai"


def create_llm(completion_model=None, embedding_model=None, **kwargs):
    provider = detect_provider(completion_model or "")

    if provider == "anthropic":
        anthropic_llm = AnthropicLlm(
            completion_model=completion_model,
            query_cache_kv=kwargs.get("query_cache_kv"),
        )

        if embedding_model:
            openai_llm = OpenAiLlm(
                embedding_model=embedding_model,
                query_cache_kv=kwargs.get("query_cache_kv"),
                embedding_cache_kv=kwargs.get("embedding_cache_kv"),
                openai_api_key=kwargs.get("openai_api_key"),
            )
            return CompositeLlm(
                completion_provider=anthropic_llm,
                embedding_provider=openai_llm,
            )

        return anthropic_llm

    return OpenAiLlm(
        completion_model=completion_model,
        embedding_model=embedding_model,
        query_cache_kv=kwargs.get("query_cache_kv"),
        embedding_cache_kv=kwargs.get("embedding_cache_kv"),
        openai_api_key=kwargs.get("openai_api_key"),
    )
