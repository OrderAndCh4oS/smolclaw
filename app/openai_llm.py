import json
import time
from typing import Any, Callable, Dict, List, Optional

import os

from dotenv import load_dotenv
from openai import OpenAI

from app.definitions import SQLITE_DB_PATH
from app.model_defaults import DEFAULT_OPENAI_CHAT_MODEL, DEFAULT_OPENAI_EMBEDDING_MODEL
from app.sqlite_store import SqliteKvStore
from app.logger import logger
from app.model_registry import MODEL_REGISTRY
from app.utilities import make_hash

load_dotenv()

DEFAULT_OPENAI_COMPLETION_MODEL = os.getenv("OPENAI_COMPLETION_MODEL", DEFAULT_OPENAI_CHAT_MODEL)
DEFAULT_OPENAI_PROVIDER_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_OPENAI_EMBEDDING_MODEL)


def _default_reasoning_effort_for_model(model: str | None) -> str | None:
    return MODEL_REGISTRY.default_effort(model)


def _supports_reasoning_effort(model: str | None) -> bool:
    return MODEL_REGISTRY.supports_reasoning_effort(model)


def _use_responses_for_tool_completion(model: str | None, tools: Optional[List[dict]], reasoning_effort: str | None) -> bool:
    return MODEL_REGISTRY.endpoint_for(
        model,
        tools=bool(tools),
        reasoning_effort=reasoning_effort,
    ) == "responses"


class OpenAiLlm:
    def __init__(self, completion_model=None, embedding_model=None, query_cache_kv=None, embedding_cache_kv=None,
                 openai_api_key=None, db_path=None) -> None:
        """
        Initializes the OpenAiLlm instance with specified models and caches.
        """
        api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
        self.client = OpenAI(api_key=api_key)
        cache_db_path = db_path or SQLITE_DB_PATH
        self.query_cache_kv = query_cache_kv or SqliteKvStore(cache_db_path, "query_cache")
        self.embedding_cache_kv = embedding_cache_kv or SqliteKvStore(cache_db_path, "embedding_cache")
        self.completion_model = completion_model or DEFAULT_OPENAI_COMPLETION_MODEL
        self.embedding_model = embedding_model or DEFAULT_OPENAI_PROVIDER_EMBEDDING_MODEL
        self.reasoning_effort = _default_reasoning_effort_for_model(self.completion_model)
        self.usage_collector = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def _record_usage(self, operation: str, model: str, prompt_tokens: int,
                       completion_tokens: int, total_tokens: int, duration_ms: int, cached: bool = False):
        if self.usage_collector is None:
            return
        from app.usage import LlmUsageRecord
        self.usage_collector.record(LlmUsageRecord(
            timestamp=time.time(),
            category="unknown",
            operation=operation,
            model=model or self.completion_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            cached=cached,
        ))

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

    @staticmethod
    def _sanitize_tools(tools: List[dict]) -> List[dict]:
        """Drop function fields unsupported by OpenAI chat.completions."""
        sanitized = []
        for tool in tools:
            if tool.get("type") != "function":
                sanitized.append(tool)
                continue
            function = tool.get("function", {})
            clean_function = {
                key: function[key]
                for key in ("name", "description", "parameters", "strict")
                if key in function
            }
            sanitized.append({"type": "function", "function": clean_function})
        return sanitized

    @staticmethod
    def _responses_tools(tools: List[dict]) -> List[dict]:
        """Translate chat-completions function tools to Responses API tools."""
        translated = []
        for tool in OpenAiLlm._sanitize_tools(tools):
            if tool.get("type") != "function":
                translated.append(tool)
                continue
            function = tool.get("function", {})
            translated.append({
                key: function[key]
                for key in ("name", "description", "parameters", "strict")
                if key in function
            } | {"type": "function"})
        return translated

    @staticmethod
    def _responses_input(messages: List[Dict[str, Any]]) -> List[dict]:
        """Translate this harness' chat-style transcript to Responses input items."""
        items = []
        for message in messages:
            if message.get("response_items"):
                items.extend(message["response_items"])
                continue

            role = message.get("role")
            if role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id", ""),
                    "output": message.get("content") or "",
                })
                continue

            if role == "assistant" and message.get("tool_calls"):
                content = message.get("content")
                if content:
                    items.append({"role": "assistant", "content": content})
                for tool_call in message.get("tool_calls") or []:
                    function = tool_call.get("function", {})
                    items.append({
                        "type": "function_call",
                        "call_id": tool_call.get("id", ""),
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments") or "{}",
                    })
                continue

            items.append({
                "role": role,
                "content": message.get("content") or "",
            })
        return items

    @staticmethod
    def _field(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _responses_content(cls, response: Any) -> str | None:
        output_text = cls._field(response, "output_text")
        if output_text:
            return output_text

        parts = []
        for item in cls._field(response, "output", []) or []:
            if cls._field(item, "type") != "message":
                continue
            for part in cls._field(item, "content", []) or []:
                if cls._field(part, "type") == "output_text":
                    text = cls._field(part, "text")
                    if text:
                        parts.append(text)
        return "".join(parts) or None

    @classmethod
    def _plain_response_item(cls, item: Any) -> dict:
        if isinstance(item, dict):
            return item
        if hasattr(item, "model_dump"):
            return item.model_dump(exclude_none=True)
        return {
            key: value
            for key, value in vars(item).items()
            if not key.startswith("_")
        }

    @classmethod
    def _responses_passthrough_items(cls, response: Any) -> List[dict]:
        items = []
        for item in cls._field(response, "output", []) or []:
            if cls._field(item, "type") in {"reasoning", "function_call"}:
                items.append(cls._plain_response_item(item))
        return items

    @classmethod
    def _responses_tool_calls(cls, response: Any) -> List[dict] | None:
        tool_calls = []
        for item in cls._field(response, "output", []) or []:
            if cls._field(item, "type") != "function_call":
                continue
            arguments = cls._field(item, "arguments") or "{}"
            tool_calls.append({
                "id": cls._field(item, "call_id") or cls._field(item, "id"),
                "name": cls._field(item, "name"),
                "arguments": json.loads(arguments),
            })
        return tool_calls or None

    @staticmethod
    def _usage_counts(usage: Any, *, responses_api: bool = False) -> tuple[int, int, int]:
        if responses_api:
            return (
                getattr(usage, "input_tokens", 0),
                getattr(usage, "output_tokens", 0),
                getattr(usage, "total_tokens", 0),
            )
        return (
            getattr(usage, "prompt_tokens", 0),
            getattr(usage, "completion_tokens", 0),
            getattr(usage, "total_tokens", 0),
        )

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
            self._record_usage("completion", model, 0, 0, 0, 0, cached=True)
            return cache_data["result"]

        logger.info("New query")
        system_message = [{"role": "system", "content": context}] if context else []
        messages: List[Dict[str, str]] = [{"role": "user", "content": query}]

        from app.tracing import trace_llm_call
        try:
            with trace_llm_call("completion", model) as span:
                started = time.perf_counter()
                response = self.client.chat.completions.create(
                    model=model,
                    store=True,
                    messages=system_message + messages
                )
                duration_ms = int((time.perf_counter() - started) * 1000)
                result = response.choices[0].message.content
                usage = getattr(response, "usage", None)
                pt = getattr(usage, "prompt_tokens", 0)
                ct = getattr(usage, "completion_tokens", 0)
                tt = getattr(usage, "total_tokens", 0)
                span.set_attribute("llm.prompt_tokens", pt)
                span.set_attribute("llm.completion_tokens", ct)
                span.set_attribute("llm.total_tokens", tt)
                span.set_attribute("llm.duration_ms", duration_ms)
                self._record_usage("completion", model, pt, ct, tt, duration_ms)
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
        stream: bool = False,
        on_chunk: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Gets a completion that may include tool calls.

        :param messages: Full message list including system, history, user.
        :param tools: Optional list of tool schemas in OpenAI format.
        :param model: The model to use; if None, use self.completion_model.
        :param stream: If True, stream tokens via on_chunk callback.
        :param on_chunk: Async callback receiving text chunks during streaming.
        :return: Dict with 'content', 'tool_calls', 'has_tool_calls'.
        """
        model = model or self.completion_model
        kwargs = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = self._sanitize_tools(tools)
        reasoning_effort = self.reasoning_effort or _default_reasoning_effort_for_model(model)
        if reasoning_effort and _supports_reasoning_effort(model) and not tools:
            kwargs["reasoning_effort"] = reasoning_effort

        if _use_responses_for_tool_completion(model, tools, reasoning_effort):
            return await self._responses_tool_completion(
                messages=messages,
                tools=tools or [],
                model=model,
                reasoning_effort=reasoning_effort,
                on_chunk=on_chunk if stream and on_chunk else None,
            )

        if stream and on_chunk:
            return await self._stream_tool_completion(kwargs, model, on_chunk)

        from app.tracing import trace_llm_call
        try:
            with trace_llm_call("tool_completion", model) as span:
                started = time.perf_counter()
                response = self.client.chat.completions.create(**kwargs)
                duration_ms = int((time.perf_counter() - started) * 1000)
                message = response.choices[0].message
                tool_calls = message.tool_calls
                usage = getattr(response, "usage", None)
                pt, ct, tt = self._usage_counts(usage)
                span.set_attribute("llm.prompt_tokens", pt)
                span.set_attribute("llm.completion_tokens", ct)
                span.set_attribute("llm.total_tokens", tt)
                span.set_attribute("llm.duration_ms", duration_ms)
                span.set_attribute("llm.has_tool_calls", bool(tool_calls))
                self._record_usage("tool_completion", model, pt, ct, tt, duration_ms)
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

    async def _responses_tool_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[dict],
        model: str,
        reasoning_effort: str,
        on_chunk: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        from app.tracing import trace_llm_call

        try:
            with trace_llm_call("tool_completion", model) as span:
                started = time.perf_counter()
                response = self.client.responses.create(
                    model=model,
                    input=self._responses_input(messages),
                    tools=self._responses_tools(tools),
                    reasoning={"effort": reasoning_effort},
                )
                duration_ms = int((time.perf_counter() - started) * 1000)
                response_items = self._responses_passthrough_items(response)
                tool_calls = self._responses_tool_calls(response)
                content = self._responses_content(response)
                if on_chunk and content and not tool_calls:
                    await on_chunk(content)
                usage = getattr(response, "usage", None)
                pt, ct, tt = self._usage_counts(usage, responses_api=True)
                span.set_attribute("llm.prompt_tokens", pt)
                span.set_attribute("llm.completion_tokens", ct)
                span.set_attribute("llm.total_tokens", tt)
                span.set_attribute("llm.duration_ms", duration_ms)
                span.set_attribute("llm.has_tool_calls", bool(tool_calls))
                span.set_attribute("llm.endpoint", "responses")
                self._record_usage("tool_completion", model, pt, ct, tt, duration_ms)
                return {
                    "content": content,
                    "tool_calls": tool_calls,
                    "has_tool_calls": bool(tool_calls),
                    "response_items": response_items,
                }
        except Exception as e:
            logger.error(f"Error getting Responses tool completion: {e}")
            raise

    async def _stream_tool_completion(self, kwargs: dict, model: str, on_chunk: Callable) -> Dict[str, Any]:
        """Stream a tool completion, emitting text chunks via callback."""
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        try:
            started = time.perf_counter()
            content_parts = []
            tool_call_deltas: Dict[int, dict] = {}
            final_usage = None

            stream = self.client.chat.completions.create(**kwargs)
            for chunk in stream:
                if not chunk.choices:
                    # Final chunk with usage only
                    if chunk.usage:
                        final_usage = chunk.usage
                    continue

                delta = chunk.choices[0].delta

                # Stream text content
                if delta.content:
                    content_parts.append(delta.content)
                    await on_chunk(delta.content)

                # Accumulate tool call deltas
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_call_deltas:
                            tool_call_deltas[idx] = {"id": "", "name": "", "arguments": ""}
                        entry = tool_call_deltas[idx]
                        if tc_delta.id:
                            entry["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                entry["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                entry["arguments"] += tc_delta.function.arguments

                # Check for usage in final chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    final_usage = chunk.usage

            duration_ms = int((time.perf_counter() - started) * 1000)

            self._record_usage(
                "tool_completion", model,
                getattr(final_usage, "prompt_tokens", 0),
                getattr(final_usage, "completion_tokens", 0),
                getattr(final_usage, "total_tokens", 0),
                duration_ms,
            )

            # Build tool calls from accumulated deltas
            tool_calls = None
            if tool_call_deltas:
                tool_calls = []
                for idx in sorted(tool_call_deltas):
                    entry = tool_call_deltas[idx]
                    tool_calls.append({
                        "id": entry["id"],
                        "name": entry["name"],
                        "arguments": json.loads(entry["arguments"]) if entry["arguments"] else {},
                    })

            content = "".join(content_parts) or None
            return {
                "content": content,
                "tool_calls": tool_calls or None,
                "has_tool_calls": bool(tool_calls),
            }
        except Exception as e:
            logger.error(f"Error streaming tool completion: {e}")
            raise

    async def get_structured_completion(
        self, query: str, response_model, model: Optional[str] = None, context: str = "",
        use_cache: bool = True,
    ):
        """Get a completion parsed into a Pydantic model using OpenAI's structured output.

        :param query: The prompt text.
        :param response_model: A Pydantic BaseModel subclass.
        :param model: Model override.
        :param context: Optional system context.
        :param use_cache: Whether to use cache.
        :return: An instance of response_model.
        """
        model = model or self.completion_model
        query_hash = self._get_query_cache_key(
            query=f"structured:{response_model.__name__}:{query}", model=model, context=context,
        )
        if use_cache and await self.query_cache_kv.has(query_hash):
            try:
                cache_data = await self.query_cache_kv.get_by_key(query_hash)
                result = response_model.model_validate(cache_data["result"])
                logger.info("Structured query cache hit")
                self._record_usage("structured_completion", model, 0, 0, 0, 0, cached=True)
                return result
            except Exception:
                logger.warning("Structured cache entry invalid, fetching fresh")

        system_message = [{"role": "system", "content": context}] if context else []
        messages = system_message + [{"role": "user", "content": query}]

        try:
            started = time.perf_counter()
            response = self.client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=response_model,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            usage = getattr(response, "usage", None)
            self._record_usage(
                "structured_completion", model,
                getattr(usage, "prompt_tokens", 0),
                getattr(usage, "completion_tokens", 0),
                getattr(usage, "total_tokens", 0),
                duration_ms,
            )
            parsed = response.choices[0].message.parsed
            await self.query_cache_kv.add(query_hash, {
                "query": query, "model": model, "context": context,
                "result": parsed.model_dump(),
            })
            return parsed
        except Exception as e:
            logger.error(f"Error getting structured completion: {e}")
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
            self._record_usage("embedding", model, 0, 0, 0, 0, cached=True)
        else:
            logger.info("New embedding")
            try:
                started = time.perf_counter()
                response = self.client.embeddings.create(
                    model=model,
                    input=content,
                )
                duration_ms = int((time.perf_counter() - started) * 1000)
                embedding = response.data[0].embedding
                usage = getattr(response, "usage", None)
                self._record_usage(
                    "embedding", model,
                    getattr(usage, "prompt_tokens", 0), 0,
                    getattr(usage, "total_tokens", 0),
                    duration_ms,
                )
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
                started = time.perf_counter()
                response = self.client.embeddings.create(
                    model=model,
                    input=[content for content, _ in uncached_contents],
                )
                duration_ms = int((time.perf_counter() - started) * 1000)

                # Store new embeddings in cache and result
                for idx, (content, content_hash), embedding_data in zip(
                    uncached_indices, uncached_contents, response.data
                ):
                    embedding = embedding_data.embedding
                    embeddings[idx] = embedding
                    await self.embedding_cache_kv.add(content_hash, embedding)

                usage = getattr(response, "usage", None)
                self._record_usage(
                    "embeddings", model,
                    getattr(usage, "prompt_tokens", 0), 0,
                    getattr(usage, "total_tokens", 0),
                    duration_ms,
                )
            except Exception as e:
                logger.error(f"Error getting batch embeddings: {e}")
                raise
        else:
            logger.info(f"All {len(contents)} embeddings served from cache")
            self._record_usage("embeddings", model, 0, 0, 0, 0, cached=True)

        return embeddings

    async def close(self):
        seen = set()
        for store in (self.query_cache_kv, self.embedding_cache_kv):
            if store is None or id(store) in seen:
                continue
            seen.add(id(store))
            close_fn = getattr(store, "close", None)
            if callable(close_fn):
                await close_fn()
