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
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "read_file"
        tool_call.function.arguments = '{"path": "/tmp/test"}'

        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response(
            content=None, tool_calls=[tool_call]
        ))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            result = await llm.get_tool_completion(
                messages=[{"role": "user", "content": "read /tmp/test"}],
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            )
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
    async def test_get_tool_completion_omits_reasoning_effort_when_tools_are_present(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = MagicMock(return_value=_make_mock_response("ok"))
        with patch("app.openai_llm.OpenAI", return_value=mock_client):

            llm = OpenAiLlm(openai_api_key="test-key")
            llm.completion_model = "gpt-5.5"
            llm.reasoning_effort = "high"
            await llm.get_tool_completion(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            )
            call_kwargs = mock_client.chat.completions.create.call_args
            assert call_kwargs.kwargs["model"] == "gpt-5.5"
            assert "tools" in call_kwargs.kwargs
            assert "reasoning_effort" not in call_kwargs.kwargs

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
