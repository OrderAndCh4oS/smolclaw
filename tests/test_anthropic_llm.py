import os
from unittest.mock import MagicMock

import pytest

from app.anthropic_llm import AnthropicLlm


def _make_text_block(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(tool_id, name, input_data):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = input_data
    return block


def _make_response(content_blocks):
    response = MagicMock()
    response.content = content_blocks
    return response


class TestAnthropicGetCompletion:
    @pytest.mark.asyncio
    async def test_get_completion_basic(self, temp_dir):
        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(return_value=_make_response([_make_text_block("Hello there")]))
        async with AnthropicLlm(
            completion_model="claude-sonnet-4-20250514",
            db_path=os.path.join(temp_dir, "anthropic.db"),
            client=mock_client,
        ) as llm:
            result = await llm.get_completion("Hi", use_cache=False)
        assert result == "Hello there"
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_completion_with_context(self, temp_dir):
        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(return_value=_make_response([_make_text_block("response")]))
        async with AnthropicLlm(
            completion_model="claude-sonnet-4-20250514",
            db_path=os.path.join(temp_dir, "anthropic.db"),
            client=mock_client,
        ) as llm:
            await llm.get_completion("query", context="You are helpful", use_cache=False)
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful"

    @pytest.mark.asyncio
    async def test_get_completion_error(self, temp_dir):
        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(side_effect=RuntimeError("API error"))
        async with AnthropicLlm(
            completion_model="claude-sonnet-4-20250514",
            db_path=os.path.join(temp_dir, "anthropic.db"),
            client=mock_client,
        ) as llm:
            with pytest.raises(RuntimeError, match="API error"):
                await llm.get_completion("Hi", use_cache=False)


class TestAnthropicGetToolCompletion:
    @pytest.mark.asyncio
    async def test_tool_completion_with_tool_calls(self, temp_dir):
        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(return_value=_make_response([
            _make_text_block("Let me read that"),
            _make_tool_use_block("tu_1", "read_file", {"path": "/tmp/test"}),
        ]))
        async with AnthropicLlm(
            completion_model="claude-sonnet-4-20250514",
            db_path=os.path.join(temp_dir, "anthropic.db"),
            client=mock_client,
        ) as llm:
            result = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "read /tmp/test"}],
                tools=[{
                    "type": "function",
                    "function": {"name": "read_file", "description": "Read a file", "parameters": {}},
                }],
            )
        assert result["has_tool_calls"] is True
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "tu_1"
        assert result["tool_calls"][0]["name"] == "read_file"
        assert result["tool_calls"][0]["arguments"] == {"path": "/tmp/test"}
        assert result["content"] == "Let me read that"

    @pytest.mark.asyncio
    async def test_tool_completion_without_tools(self, temp_dir):
        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(return_value=_make_response([
            _make_text_block("Just a response"),
        ]))
        async with AnthropicLlm(
            completion_model="claude-sonnet-4-20250514",
            db_path=os.path.join(temp_dir, "anthropic.db"),
            client=mock_client,
        ) as llm:
            result = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hello"}],
            )
        assert result["has_tool_calls"] is False
        assert result["tool_calls"] is None
        assert result["content"] == "Just a response"

    @pytest.mark.asyncio
    async def test_tool_completion_error(self, temp_dir):
        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(side_effect=RuntimeError("API fail"))
        async with AnthropicLlm(
            completion_model="claude-sonnet-4-20250514",
            db_path=os.path.join(temp_dir, "anthropic.db"),
            client=mock_client,
        ) as llm:
            with pytest.raises(RuntimeError, match="API fail"):
                await llm.get_tool_completion(
                    messages=[{"role": "user", "content": "hi"}],
                )


class TestMessageTranslation:
    def test_system_extraction(self):
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
        ]
        converted, system = AnthropicLlm._translate_messages(messages)
        assert system == "You are helpful"
        assert len(converted) == 1
        assert converted[0]["role"] == "user"

    def test_tool_calls_to_tool_use(self):
        messages = [
            {"role": "user", "content": "read file"},
            {
                "role": "assistant",
                "content": "Sure",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "/tmp"}'},
                    }
                ],
            },
        ]
        converted, system = AnthropicLlm._translate_messages(messages)
        assert system is None
        assert len(converted) == 2
        assistant_content = converted[1]["content"]
        assert len(assistant_content) == 2
        assert assistant_content[0]["type"] == "text"
        assert assistant_content[0]["text"] == "Sure"
        assert assistant_content[1]["type"] == "tool_use"
        assert assistant_content[1]["id"] == "call_1"
        assert assistant_content[1]["name"] == "read_file"
        assert assistant_content[1]["input"] == {"path": "/tmp"}

    def test_tool_role_to_tool_result(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"text": "hello"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "echo: hello"},
        ]
        converted, system = AnthropicLlm._translate_messages(messages)
        # tool result gets role=user, should merge with nothing since assistant is before
        tool_result_msg = converted[2]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["tool_use_id"] == "call_1"
        assert tool_result_msg["content"][0]["content"] == "echo: hello"

    def test_consecutive_same_role_merging(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]
        converted, system = AnthropicLlm._translate_messages(messages)
        assert len(converted) == 1
        assert converted[0]["role"] == "user"
        content = converted[0]["content"]
        assert len(content) == 2
        assert content[0]["text"] == "first"
        assert content[1]["text"] == "second"


class TestToolSchemaTranslation:
    def test_translate_tools(self):
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ]
        result = AnthropicLlm._translate_tools(openai_tools)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"
        assert result[0]["description"] == "Read a file"
        assert result[0]["input_schema"]["type"] == "object"
        assert "path" in result[0]["input_schema"]["properties"]


class TestEmbeddingNotImplemented:
    @pytest.mark.asyncio
    async def test_get_embedding_raises(self, temp_dir):
        async with AnthropicLlm(
            completion_model="claude-sonnet-4-20250514",
            db_path=os.path.join(temp_dir, "anthropic.db"),
            client=MagicMock(),
        ) as llm:
            with pytest.raises(NotImplementedError):
                await llm.get_embedding("test")

    @pytest.mark.asyncio
    async def test_get_embeddings_raises(self, temp_dir):
        async with AnthropicLlm(
            completion_model="claude-sonnet-4-20250514",
            db_path=os.path.join(temp_dir, "anthropic.db"),
            client=MagicMock(),
        ) as llm:
            with pytest.raises(NotImplementedError):
                await llm.get_embeddings(["test"])
