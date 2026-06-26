import os
import re
from collections.abc import Callable
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.tools.base import Tool


def _load_web_env():
    load_dotenv(Path.cwd() / ".env", override=False)
    config_dir = os.getenv("SMOLCLAW_CONFIG_DIR", "~/.config/smolclaw")
    load_dotenv(Path(config_dir).expanduser() / ".env", override=False)


class WebSearchTool(Tool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. Use this when memory doesn't have the answer, "
            "or when you need up-to-date information beyond what's stored. "
            "Always check memory_search first before searching the web."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        }

    def __init__(self, api_key: str = None, http_client_factory: Callable[..., object] | None = None):
        _load_web_env()
        self.api_key = api_key or os.getenv("BRAVE_SEARCH_API_KEY")
        self.http_client_factory = http_client_factory or httpx.AsyncClient

    async def execute(self, **kwargs) -> str:
        if not self.api_key:
            return "Error: BRAVE_SEARCH_API_KEY not set"

        query = kwargs["query"]
        try:
            async with self.http_client_factory() as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": 5},
                    headers={"X-Subscription-Token": self.api_key},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return f"Error: {e}"

        results = data.get("web", {}).get("results", [])
        if not results:
            return "No results found."

        lines = []
        for r in results[:5]:
            title = r.get("title", "")
            url = r.get("url", "")
            desc = r.get("description", "")
            lines.append(f"**{title}**\n{url}\n{desc}\n")
        return "\n".join(lines)


class WebFetchTool(Tool):
    def __init__(self, http_client_factory: Callable[..., object] | None = None):
        self.http_client_factory = http_client_factory or httpx.AsyncClient

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch and extract text content from a specific URL. "
            "Use this to read a web page you already have the URL for. "
            "For discovering pages, use web_search first."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs) -> str:
        url = kwargs["url"]
        if not re.match(r'^https?://', url):
            return f"Error: invalid URL: {url}"

        try:
            async with self.http_client_factory(follow_redirects=True) as client:
                resp = await client.get(url, timeout=10.0)
                resp.raise_for_status()
                content = resp.text
        except Exception as e:
            return f"Error: {e}"

        # Simple HTML tag stripping
        text = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) > 10000:
            text = text[:10000] + "\n... (truncated)"

        return text
