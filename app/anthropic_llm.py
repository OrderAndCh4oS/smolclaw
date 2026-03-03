import json
import os
from typing import Any, Dict, List, Optional

import anthropic
from dotenv import load_dotenv

from app.definitions import SQLITE_DB_PATH, COMPLETION_MODEL
from app.sqlite_store import SqliteKvStore
from app.logger import logger
from app.utilities import make_hash

load_dotenv()


class AnthropicLlm:
    def __init__(self, completion_model=None, query_cache_kv=None) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.query_cache_kv = query_cache_kv or SqliteKvStore(SQLITE_DB_PATH, "query_cache")
        self.completion_model = completion_model or COMPLETION_MODEL

    def _get_query_cache_key(self, query: str, model: str, context: str) -> str:
        key_payload = {
            "query": query,
            "model": model,
            "context": context,
        }
        return make_hash(json.dumps(key_payload, sort_keys=True), "qry-")

    async def get_completion(self, query: str, model: Optional[str] = None, context: str = "",
                             use_cache: bool = True) -> str:
        model = model or self.completion_model
        query_hash = self._get_query_cache_key(query=query, model=model, context=context)
        if use_cache and await self.query_cache_kv.has(query_hash):
            logger.info("Query cache hit")
            cache_data = await self.query_cache_kv.get_by_key(query_hash)
            return cache_data["result"]

        logger.info("New query")
        kwargs = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": query}],
        }
        if context:
            kwargs["system"] = context

        try:
            response = self.client.messages.create(**kwargs)
            result = response.content[0].text
        except Exception as e:
            logger.error(f"Error getting completion: {e}")
            raise

        await self.query_cache_kv.add(query_hash, {
            "query": query,
            "model": model,
            "context": context,
            "result": result,
        })

        return result

    async def get_tool_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[dict]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        model = model or self.completion_model
        anthropic_messages, system = self._translate_messages(messages)
        anthropic_tools = self._translate_tools(tools) if tools else []

        kwargs = {
            "model": model,
            "max_tokens": 8192,
            "messages": anthropic_messages,
        }
        if system:
            kwargs["system"] = system
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        try:
            response = self.client.messages.create(**kwargs)
            return self._normalize_response(response)
        except Exception as e:
            logger.error(f"Error getting tool completion: {e}")
            raise

    async def get_embedding(self, content: Any, model: Optional[str] = None) -> List[float]:
        raise NotImplementedError("Anthropic does not provide an embeddings API. Use CompositeLlm.")

    async def get_embeddings(self, contents: List[Any], model: Optional[str] = None) -> List[List[float]]:
        raise NotImplementedError("Anthropic does not provide an embeddings API. Use CompositeLlm.")

    @staticmethod
    def _translate_messages(messages: List[dict]) -> tuple:
        system_parts = []
        converted = []

        for msg in messages:
            role = msg.get("role")

            if role == "system":
                system_parts.append(msg["content"])

            elif role == "assistant":
                content_blocks = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    args_raw = func.get("arguments", "{}")
                    if isinstance(args_raw, str):
                        try:
                            args = json.loads(args_raw)
                        except json.JSONDecodeError:
                            args = {}
                    else:
                        args = args_raw
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": func["name"],
                        "input": args,
                    })
                converted.append({"role": "assistant", "content": content_blocks})

            elif role == "tool":
                converted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg["tool_call_id"],
                            "content": msg["content"],
                        }
                    ],
                })

            else:
                converted.append({"role": role, "content": msg["content"]})

        # Merge consecutive same-role messages
        merged = []
        for msg in converted:
            if merged and merged[-1]["role"] == msg["role"]:
                prev_content = merged[-1]["content"]
                curr_content = msg["content"]
                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{"type": "text", "text": curr_content}]
                merged[-1]["content"] = prev_content + curr_content
            else:
                merged.append(msg)

        system = "\n\n".join(system_parts) if system_parts else None
        return merged, system

    @staticmethod
    def _translate_tools(tools: List[dict]) -> List[dict]:
        anthropic_tools = []
        for tool in tools:
            func = tool.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    @staticmethod
    def _normalize_response(response) -> Dict[str, Any]:
        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        content = "\n".join(text_parts) if text_parts else None
        return {
            "content": content,
            "tool_calls": tool_calls or None,
            "has_tool_calls": bool(tool_calls),
        }
