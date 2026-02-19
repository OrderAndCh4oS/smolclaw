from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.tools.web import WebSearchTool, WebFetchTool


class TestWebSearchTool:
    @pytest.mark.asyncio
    async def test_web_search_returns_results(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "web": {
                "results": [
                    {"title": "Python", "url": "https://python.org", "description": "Programming language"},
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.web.httpx.AsyncClient", return_value=mock_client):
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

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.web.httpx.AsyncClient", return_value=mock_client):
            tool = WebFetchTool()
            result = await tool.execute(url="https://example.com")
            assert "Hello World" in result

    @pytest.mark.asyncio
    async def test_web_fetch_bad_url(self):
        tool = WebFetchTool()
        result = await tool.execute(url="not-a-url")
        assert result.startswith("Error:")
