from typing import Any, Callable, Dict, List, Optional, Protocol


class CompletionAdapter(Protocol):
    completion_model: str
    usage_collector: object | None

    async def get_completion(
        self,
        query: str,
        model: Optional[str] = None,
        context: str = "",
        use_cache: bool = True,
    ) -> str:
        ...

    async def close(self):
        ...


class ToolCompletionAdapter(CompletionAdapter, Protocol):
    async def get_tool_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[dict]] = None,
        model: Optional[str] = None,
        stream: bool = False,
        on_chunk: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        ...


class StructuredCompletionAdapter(CompletionAdapter, Protocol):
    async def get_structured_completion(
        self,
        query: str,
        response_model,
        model: Optional[str] = None,
        context: str = "",
        use_cache: bool = True,
    ):
        ...


class EmbeddingAdapter(Protocol):
    embedding_model: str
    usage_collector: object | None

    async def get_embedding(self, content: Any, model: Optional[str] = None) -> List[float]:
        ...

    async def get_embeddings(self, contents: List[Any], model: Optional[str] = None) -> List[List[float]]:
        ...

    async def close(self):
        ...


class LlmAdapter(ToolCompletionAdapter, StructuredCompletionAdapter, EmbeddingAdapter, Protocol):
    pass
