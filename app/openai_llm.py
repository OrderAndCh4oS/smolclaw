import json
from typing import Any, Dict, List, Optional

import os

from dotenv import load_dotenv
from openai import OpenAI

from app.definitions import SQLITE_DB_PATH, COMPLETION_MODEL, EMBEDDING_MODEL
from app.sqlite_store import SqliteKvStore
from app.logger import logger
from app.utilities import make_hash

load_dotenv()


class OpenAiLlm:
    def __init__(self, completion_model=None, embedding_model=None, query_cache_kv=None, embedding_cache_kv=None,
                 openai_api_key=None) -> None:
        """
        Initializes the OpenAiLlm instance with specified models and caches.
        """
        api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
        self.client = OpenAI(api_key=api_key)
        self.query_cache_kv = query_cache_kv or SqliteKvStore(SQLITE_DB_PATH, "query_cache")
        self.embedding_cache_kv = embedding_cache_kv or SqliteKvStore(SQLITE_DB_PATH, "embedding_cache")
        self.completion_model = completion_model or COMPLETION_MODEL
        self.embedding_model = embedding_model or EMBEDDING_MODEL

    def _get_query_cache_key(self, query: str, model: str, context: str) -> str:
        key_payload = {
            "query": query,
            "model": model,
            "context": context,
        }
        return make_hash(json.dumps(key_payload, sort_keys=True), "qry-")

    def _get_embedding_cache_key(self, content: Any, model: str) -> str:
        key_payload = {
            "content": str(content),
            "model": model,
        }
        return make_hash(json.dumps(key_payload, sort_keys=True), "emb-")

    async def get_completion(self, query: str, model: Optional[str] = None, context: str = "",
                             use_cache: bool = True) -> str:
        """
        Gets a completion from the API with optional caching.

        :param query: User's query string.
        :param model: The model to use; if None, use self.completion_model.
        :param context: Optional context or instructions.
        :param use_cache: Whether to use the cached results.
        :return: The completion result.
        """
        model = model or self.completion_model
        query_hash = self._get_query_cache_key(query=query, model=model, context=context)
        if use_cache and await self.query_cache_kv.has(query_hash):
            logger.info("Query cache hit")
            cache_data = await self.query_cache_kv.get_by_key(query_hash)
            return cache_data["result"]

        logger.info("New query")
        system_message = [{"role": "system", "content": context}] if context else []
        messages: List[Dict[str, str]] = [{"role": "user", "content": query}]

        try:
            response = self.client.chat.completions.create(
                model=model,
                store=True,
                messages=system_message + messages
            )
            result = response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error getting completion: {e}")
            raise

        await self.query_cache_kv.add(query_hash, {
            "query": query,
            "model": model,
            "context": context,
            "result": result
        })

        return result

    async def get_tool_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[dict]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gets a completion that may include tool calls.

        :param messages: Full message list including system, history, user.
        :param tools: Optional list of tool schemas in OpenAI format.
        :param model: The model to use; if None, use self.completion_model.
        :return: Dict with 'content', 'tool_calls', 'has_tool_calls'.
        """
        model = model or self.completion_model
        kwargs = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        try:
            response = self.client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            tool_calls = message.tool_calls
            return {
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    }
                    for tc in (tool_calls or [])
                ] or None,
                "has_tool_calls": bool(tool_calls),
            }
        except Exception as e:
            logger.error(f"Error getting tool completion: {e}")
            raise

    async def get_embedding(self, content: Any, model: Optional[str] = None) -> List[float]:
        """
        Gets the embedding for the provided content using the specified model.

        :param content: The text or data to be embedded.
        :param model: The model to use; if None, use self.embedding_model.
        :return: The embedding vector.
        """
        model = model or self.embedding_model
        content_hash = self._get_embedding_cache_key(content, model)

        if await self.embedding_cache_kv.has(content_hash):
            logger.info("Embedding cache hit")
            embedding = await self.embedding_cache_kv.get_by_key(content_hash)
        else:
            logger.info("New embedding")
            try:
                response = self.client.embeddings.create(
                    model=model,
                    input=content,
                )
                embedding = response.data[0].embedding
            except Exception as e:
                logger.error(f"Error getting embedding: {e}")
                raise
            await self.embedding_cache_kv.add(content_hash, embedding)

        return embedding

    async def get_embeddings(self, contents: List[Any], model: Optional[str] = None) -> List[List[float]]:
        """
        Gets embeddings for multiple contents in a batched API call.
        Uses cache when available and only fetches uncached embeddings.

        :param contents: List of texts or data to be embedded.
        :param model: The model to use; if None, use self.embedding_model.
        :return: List of embedding vectors in the same order as contents.
        """
        model = model or self.embedding_model

        # Check cache for each content
        embeddings = [None] * len(contents)
        uncached_indices = []
        uncached_contents = []

        for i, content in enumerate(contents):
            content_hash = self._get_embedding_cache_key(content, model)
            if await self.embedding_cache_kv.has(content_hash):
                logger.debug(f"Embedding cache hit for item {i}")
                embeddings[i] = await self.embedding_cache_kv.get_by_key(content_hash)
            else:
                uncached_indices.append(i)
                uncached_contents.append((content, content_hash))

        # Batch fetch uncached embeddings
        if uncached_contents:
            logger.info(f"Fetching {len(uncached_contents)} new embeddings in batch")
            try:
                response = self.client.embeddings.create(
                    model=model,
                    input=[content for content, _ in uncached_contents],
                )

                # Store new embeddings in cache and result
                for idx, (content, content_hash), embedding_data in zip(
                    uncached_indices, uncached_contents, response.data
                ):
                    embedding = embedding_data.embedding
                    embeddings[idx] = embedding
                    await self.embedding_cache_kv.add(content_hash, embedding)

            except Exception as e:
                logger.error(f"Error getting batch embeddings: {e}")
                raise
        else:
            logger.info(f"All {len(contents)} embeddings served from cache")

        return embeddings
