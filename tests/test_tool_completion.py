from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.openai_llm import OpenAiLlm


def _make_mock_response(content="Hello", tool_calls=None):
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_responses_response(output=None, output_text=None, usage=None):
    return SimpleNamespace(
        output=output or [],
        output_text=output_text,
        usage=usage or SimpleNamespace(input_tokens=0, output_tokens=0, total_tokens=0),
    )


class TestGetToolCompletion:
    @pytest.mark.asyncio
    async def test_get_tool_completion_no_tools(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response("answer"))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            result = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hi"}],
            )
            assert result["content"] == "answer"
            assert result["has_tool_calls"] is False

    @pytest.mark.asyncio
    async def test_get_tool_completion_with_tool_calls(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock()
        mock_client.responses.create = MagicMock(return_value=_make_responses_response(
            output=[
                SimpleNamespace(
                    type="function_call",
                    id="fc_123",
                    call_id="call_123",
                    name="read_file",
                    arguments='{"path": "/tmp/test"}',
                )
            ]
        ))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            result = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "read /tmp/test"}],
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            )
            mock_client.chat.completions.create.assert_not_called()
            mock_client.responses.create.assert_called_once()
            assert result["has_tool_calls"] is True
            assert len(result["tool_calls"]) == 1
            tc = result["tool_calls"][0]
            assert tc["name"] == "read_file"
            assert tc["id"] == "call_123"
            assert tc["arguments"] == {"path": "/tmp/test"}
            assert isinstance(tc["arguments"], dict)

    @pytest.mark.asyncio
    async def test_get_tool_completion_no_tool_calls(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response("just text"))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            result = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hello"}],
                tools=[{"type": "function", "function": {"name": "dummy"}}],
                model="gpt-4o",
            )
            assert result["has_tool_calls"] is False
            assert result["content"] == "just text"
            assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_get_tool_completion_uses_model(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response("ok"))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-4o",
            )
            call_kwargs = mock_client.chat.completions.create.call_args
            assert call_kwargs.kwargs["model"] == "gpt-4o"
            assert "reasoning_effort" not in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_get_tool_completion_defaults_to_medium_effort_for_gpt_55(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response("ok"))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hi"}],
            )
            call_kwargs = mock_client.chat.completions.create.call_args
            assert call_kwargs.kwargs["model"] == "gpt-5.5"
            assert call_kwargs.kwargs["reasoning_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_get_tool_completion_sends_reasoning_effort_when_set(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response("ok"))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            llm.completion_model = "gpt-5.5"
            llm.reasoning_effort = "high"
            await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hi"}],
            )
            call_kwargs = mock_client.chat.completions.create.call_args
            assert call_kwargs.kwargs["model"] == "gpt-5.5"
            assert call_kwargs.kwargs["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_get_tool_completion_uses_responses_for_reasoning_tool_turns(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock()
        mock_client.responses.create = MagicMock(return_value=_make_responses_response(
            output=[
                SimpleNamespace(
                    type="function_call",
                    id="fc_123",
                    call_id="call_123",
                    name="read_file",
                    arguments='{"path": "README.md"}',
                )
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        ))
        tools = [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {}},
                "examples": [{"description": "ignored", "arguments": {"path": "README.md"}}],
            },
        }]
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            llm.completion_model = "gpt-5.5"
            llm.reasoning_effort = "high"
            result = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hi"}],
                tools=tools,
            )

        mock_client.chat.completions.create.assert_not_called()
        call_kwargs = mock_client.responses.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-5.5"
        assert call_kwargs["reasoning"] == {"effort": "high"}
        assert call_kwargs["input"] == [{"role": "user", "content": "hi"}]
        assert call_kwargs["tools"] == [{
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {}},
        }]
        assert result["has_tool_calls"] is True
        assert result["tool_calls"][0]["id"] == "call_123"
        assert result["tool_calls"][0]["arguments"] == {"path": "README.md"}

    @pytest.mark.asyncio
    async def test_get_tool_completion_carries_responses_reasoning_items_into_next_turn(self):
        reasoning_item = {"type": "reasoning", "id": "rs_123", "content": [], "summary": []}
        function_item = {
            "type": "function_call",
            "id": "fc_123",
            "call_id": "call_123",
            "name": "read_file",
            "arguments": '{"path": "README.md"}',
            "status": "completed",
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock()
        mock_client.responses.create = MagicMock(side_effect=[
            _make_responses_response(output=[reasoning_item, function_item]),
            _make_responses_response(output_text="done"),
        ])

        with patch("app.openai_llm.OpenAI", return_value=mock_client):
            llm = OpenAiLlm(openai_api_key="test-key")
            llm.reasoning_effort = "high"
            first = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "read"}],
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            )
            second = await llm.get_tool_completion(
                messages=[
                    {"role": "user", "content": "read"},
                    {
                        "role": "assistant",
                        "content": None,
                        "response_items": first["response_items"],
                        "tool_calls": [{
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "README.md"}',
                            },
                        }],
                    },
                    {"role": "tool", "tool_call_id": "call_123", "content": "README contents"},
                ],
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            )

        assert second["content"] == "done"
        second_input = mock_client.responses.create.call_args_list[1].kwargs["input"]
        assert second_input == [
            {"role": "user", "content": "read"},
            reasoning_item,
            function_item,
            {
                "type": "function_call_output",
                "call_id": "call_123",
                "output": "README contents",
            },
        ]

    @pytest.mark.asyncio
    async def test_get_tool_completion_sanitizes_unsupported_function_fields(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response("ok"))
        tools = [{
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Search memory",
                "parameters": {"type": "object", "properties": {}},
                "strict": True,
                "examples": [{"description": "Search pricing", "arguments": {"query": "pricing"}}],
                "x-extra": "ignored",
            },
        }]
        with patch("app.openai_llm.OpenAI", return_value=mock_client):
            llm = OpenAiLlm(openai_api_key="test-key")
            await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hi"}],
                tools=tools,
                model="gpt-4o",
            )

        sent_tools = mock_client.chat.completions.create.call_args.kwargs["tools"]
        assert sent_tools == [{
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Search memory",
                "parameters": {"type": "object", "properties": {}},
                "strict": True,
            },
        }]
        assert "examples" in tools[0]["function"]

    @pytest.mark.asyncio
    async def test_get_tool_completion_error_handling(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(side_effect=RuntimeError("API error"))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            with pytest.raises(RuntimeError, match="API error"):
                await llm.get_tool_completion(
                    messages=[{"role": "user", "content": "hi"}],
                )

    @pytest.mark.asyncio
    async def test_get_tool_completion_multiple_tool_calls(self):
        tc1 = MagicMock()
        tc1.id = "call_1"
        tc1.function.name = "read_file"
        tc1.function.arguments = '{"path": "/a"}'

        tc2 = MagicMock()
        tc2.id = "call_2"
        tc2.function.name = "write_file"
        tc2.function.arguments = '{"path": "/b", "content": "hello"}'

        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response(
            content=None, tool_calls=[tc1, tc2]
        ))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            result = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "do stuff"}],
                tools=[],
            )
            assert len(result["tool_calls"]) == 2
            assert result["tool_calls"][0]["name"] == "read_file"
            assert result["tool_calls"][1]["name"] == "write_file"
            assert result["tool_calls"][1]["arguments"] == {"path": "/b", "content": "hello"}
