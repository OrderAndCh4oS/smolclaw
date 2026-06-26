import json
import os
import time
from typing import Any, List, Optional

import httpx
from dotenv import load_dotenv

from app.definitions import SQLITE_DB_PATH
from app.logger import logger
from app.model_defaults import DEFAULT_VOYAGE_EMBEDDING_MODEL
from app.sqlite_store import SqliteKvStore
from app.utilities import make_hash

load_dotenv()

DEFAULT_VOYAGE_PROVIDER_EMBEDDING_MODEL = os.getenv(
    "VOYAGE_EMBEDDING_MODEL",
    DEFAULT_VOYAGE_EMBEDDING_MODEL,
)
DEFAULT_VOYAGE_BASE_URL = "https://api.voyageai.com/v1"


class VoyageEmbeddingLlm:
    def __init__(
        self,
        embedding_model: str | None = None,
        embedding_cache_kv=None,
        voyage_api_key: str | None = None,
        db_path: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self.embedding_model = embedding_model or DEFAULT_VOYAGE_PROVIDER_EMBEDDING_MODEL
        self.embedding_cache_kv = embedding_cache_kv or SqliteKvStore(
            db_path or SQLITE_DB_PATH,
            "embedding_cache",
        )
        self.api_key = voyage_api_key if voyage_api_key is not None else os.getenv("VOYAGE_API_KEY")
        self.base_url = (base_url or os.getenv("VOYAGE_BASE_URL") or DEFAULT_VOYAGE_BASE_URL).rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=60)
        self._owns_client = client is None
        self.usage_collector = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def _record_usage(self, operation: str, model: str, total_tokens: int, duration_ms: int, cached: bool = False):
        if self.usage_collector is None:
            return
        from app.usage import LlmUsageRecord
        self.usage_collector.record(LlmUsageRecord(
            timestamp=time.time(),
            category="unknown",
            operation=operation,
            model=model or self.embedding_model,
            prompt_tokens=total_tokens,
            completion_tokens=0,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            cached=cached,
        ))

    def _get_embedding_cache_key(self, content: Any, model: str) -> str:
        key_payload = {
            "content": str(content),
            "model": model,
        }
        return make_hash(json.dumps(key_payload, sort_keys=True), "emb-")

    async def get_embedding(self, content: Any, model: Optional[str] = None) -> List[float]:
        return (await self.get_embeddings([content], model=model))[0]

    async def get_embeddings(self, contents: List[Any], model: Optional[str] = None) -> List[List[float]]:
        model = model or self.embedding_model
        embeddings: list[list[float] | None] = [None] * len(contents)
        uncached_indices = []
        uncached_contents = []

        for index, content in enumerate(contents):
            content_hash = self._get_embedding_cache_key(content, model)
            if await self.embedding_cache_kv.has(content_hash):
                logger.debug(f"Voyage embedding cache hit for item {index}")
                embeddings[index] = await self.embedding_cache_kv.get_by_key(content_hash)
            else:
                uncached_indices.append(index)
                uncached_contents.append((content, content_hash))

        if uncached_contents:
            fetched = await self._fetch_embeddings([content for content, _ in uncached_contents], model)
            for index, (_, content_hash), embedding in zip(uncached_indices, uncached_contents, fetched):
                embeddings[index] = embedding
                await self.embedding_cache_kv.add(content_hash, embedding)
        else:
            logger.info(f"All {len(contents)} Voyage embeddings served from cache")
            self._record_usage("embeddings", model, 0, 0, cached=True)

        return [embedding for embedding in embeddings if embedding is not None]

    async def _fetch_embeddings(self, contents: list[Any], model: str) -> list[list[float]]:
        if not self.api_key:
            raise ValueError("VOYAGE_API_KEY is required for Voyage embeddings")

        started = time.perf_counter()
        try:
            response = await self.client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": contents,
                    "model": model,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.error(f"Error getting Voyage embeddings: {e}")
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        usage = payload.get("usage") or {}
        self._record_usage(
            "embeddings",
            model,
            int(usage.get("total_tokens") or 0),
            duration_ms,
        )
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in data]

    async def close(self):
        if self._owns_client:
            await self.client.aclose()
        close_fn = getattr(self.embedding_cache_kv, "close", None)
        if callable(close_fn):
            result = close_fn()
            if hasattr(result, "__await__"):
                await result
