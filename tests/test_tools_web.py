from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.tools.web import WebSearchTool, WebFetchTool


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False

    async def get(self, *args, **kwargs):
        return self._response


class _FakeJsonResponse:
    def __init__(self, payload):
        self._payload = payload
        self.raise_for_status = MagicMock()

    def json(self):
        return self._payload


class TestWebSearchTool:
    @pytest.mark.asyncio
    async def test_web_search_returns_results(self):
        mock_response = _FakeJsonResponse({
            "web": {
                "results": [
                    {"title": "Python", "url": "https://python.org", "description": "Programming language"},
                ]
            }
        })

        with patch("app.tools.web.httpx.AsyncClient", return_value=_FakeAsyncClient(mock_response)):
            tool = WebSearchTool(api_key="test-key")
            result = await tool.execute(query="python")
            assert "Python" in result
            assert "python.org" in result

    @pytest.mark.asyncio
    async def test_web_search_no_api_key(self):
        tool = WebSearchTool(api_key=None)
        # Clear env var too
        with patch.dict("os.environ", {}, clear=True):
            tool.api_key = None
            result = await tool.execute(query="test")
            assert result.startswith("Error:")


class TestWebFetchTool:
    @pytest.mark.asyncio
    async def test_web_fetch_returns_content(self):
        mock_response = MagicMock()
        mock_response.text = "<html><body><p>Hello World</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("app.tools.web.httpx.AsyncClient", return_value=_FakeAsyncClient(mock_response)):
            tool = WebFetchTool()
            result = await tool.execute(url="https://example.com")
            assert "Hello World" in result

    @pytest.mark.asyncio
    async def test_web_fetch_bad_url(self):
        tool = WebFetchTool()
        result = await tool.execute(url="not-a-url")
        assert result.startswith("Error:")
