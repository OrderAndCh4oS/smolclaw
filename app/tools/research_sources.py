"""Tools for preserving research source material."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.base import Tool, ToolCallPolicy
from app.tools.permissions import MUTATES_STATE


def _slugify(value: str, *, fallback: str = "source") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:80] or fallback


def _coerce_urls(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _format_research_source_note(
    *,
    title: str,
    url: str,
    summary: str,
    extracted_text: str,
    topic: str,
    related_urls: list[str],
    captured_at: str,
) -> str:
    lines = [
        f"Title: {title}",
        f"URL: {url}",
        f"Topic: {topic}" if topic else "Topic:",
        f"Captured at: {captured_at}",
        "",
        "Summary:",
        summary.strip(),
        "",
        "Links:",
        f"- {url}",
    ]
    lines.extend(f"- {item}" for item in related_urls if item != url)
    lines.extend([
        "",
        "Extracted text:",
        extracted_text.strip() if extracted_text.strip() else "(not captured)",
        "",
    ])
    return "\n".join(lines)


class ResearchSourceStoreTool(Tool):
    """Persist source-backed research notes under the workspace research directory."""

    def __init__(self, research_dir: str, smol_rag=None):
        self.research_dir = research_dir
        self.smol_rag = smol_rag

    @property
    def name(self) -> str:
        return "research_source_store"

    @property
    def description(self) -> str:
        return (
            "Store source material that backs a research finding. Use this after fetching or reading "
            "a useful source. It writes a plain text source note under .smolclaw/research/ with the "
            "page URL, summary, related links, and extracted text for future recall."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Canonical URL for the source page"},
                "title": {"type": "string", "description": "Source title or page heading"},
                "summary": {"type": "string", "description": "Short summary of what this source supports"},
                "extracted_text": {
                    "type": "string",
                    "description": "Relevant extracted plain text from the source page",
                },
                "topic": {"type": "string", "description": "Research topic this source supports"},
                "related_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional source links cited or compared with this page",
                },
                "source_id": {
                    "type": "string",
                    "description": "Optional stable source id used as the filename stem",
                },
                "ingest": {
                    "type": "boolean",
                    "description": "Whether to index the saved source note into SmolRAG memory",
                    "default": True,
                },
            },
            "required": ["url", "summary"],
        }

    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({"memory", "research", MUTATES_STATE}))

    async def execute(self, **kwargs) -> str:
        url = str(kwargs.get("url") or "").strip()
        summary = str(kwargs.get("summary") or "").strip()
        if not url:
            return "Error: url is required"
        if not re.match(r"^https?://", url):
            return f"Error: invalid URL: {url}"
        if not summary:
            return "Error: summary is required"

        title = str(kwargs.get("title") or url).strip()
        topic = str(kwargs.get("topic") or "").strip()
        extracted_text = str(kwargs.get("extracted_text") or "").strip()
        related_urls = _coerce_urls(kwargs.get("related_urls"))
        captured_at = datetime.now(timezone.utc).isoformat()
        content = _format_research_source_note(
            title=title,
            url=url,
            summary=summary,
            extracted_text=extracted_text,
            topic=topic,
            related_urls=related_urls,
            captured_at=captured_at,
        )

        requested_id = str(kwargs.get("source_id") or "").strip()
        if requested_id:
            stem = _slugify(requested_id)
        else:
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
            stem = f"{datetime.now(timezone.utc).strftime('%Y%m%d')}-{_slugify(title)}-{digest}"

        research_dir = Path(self.research_dir)
        research_dir.mkdir(parents=True, exist_ok=True)
        path = research_dir / f"{stem}.txt"
        counter = 2
        while path.exists():
            path = research_dir / f"{stem}-{counter}.txt"
            counter += 1
        path.write_text(content, encoding="utf-8")

        if kwargs.get("ingest", True) and self.smol_rag is not None:
            await self.smol_rag.ingest_text(
                content,
                source_id=f"research/{path.stem}",
                source="research",
            )

        display_path = Path("research") / path.name if research_dir.name == "research" else Path(path.name)
        return f"Stored research source: {display_path}"
