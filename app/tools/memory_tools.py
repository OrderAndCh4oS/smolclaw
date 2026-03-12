import os
import time
from datetime import datetime, timezone

from app.tools.base import Tool
from app.utilities import make_hash

from app.lifecycle import MemoryLifecycleManager

MEMORY_TYPES = ["fact", "decision", "preference", "episode", "task", "journal", "reference"]


async def _promote_accessed_excerpts(smol_rag, query: str, boost: float = 0.05, top_k: int = 5):
    """Promote excerpts returned by a search to reinforce frequently accessed memories."""
    try:
        mgr = MemoryLifecycleManager(smol_rag)
        embedding = await smol_rag.rate_limited_get_embedding(query)
        results = await smol_rag.embeddings_db.query(embedding, top_k=top_k)
        for r in results:
            excerpt_id = r.get("__id__")
            if excerpt_id:
                await mgr.promote(excerpt_id, boost=boost)
    except Exception:
        pass  # Promotion is best-effort
RECALL_MODES = ["topic", "temporal"]


def format_memory_content(
    content: str,
    memory_type: str | None = None,
    tags: list[str] | None = None,
    source_id: str | None = None,
) -> str:
    """Format memory content with YAML frontmatter and inline tags when taxonomy is provided."""
    if not memory_type and not tags:
        return content

    fm_lines = ["---"]
    if memory_type:
        fm_lines.append(f"memory_type: {memory_type}")
    if tags:
        fm_lines.append("tags:")
        for tag in tags:
            fm_lines.append(f"  - {tag}")
    fm_lines.append(f"created_at: '{datetime.now(timezone.utc).isoformat()}'")
    if source_id:
        fm_lines.append(f"source_id: {source_id}")
    fm_lines.append("---")

    inline_tags = []
    if memory_type:
        inline_tags.append(f"#{memory_type}")
    for tag in (tags or []):
        tag_str = f"#{tag}"
        if tag_str not in inline_tags:
            inline_tags.append(tag_str)

    return "\n".join(fm_lines) + "\n\n" + " ".join(inline_tags) + "\n\n" + content


class MemoryRelateTool(Tool):
    @property
    def name(self) -> str:
        return "memory_relate"

    @property
    def description(self) -> str:
        return (
            "Create an explicit relationship between two entities in the knowledge graph. "
            "Use this to connect concepts, people, tools, or any named things that are related."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "source_entity": {"type": "string", "description": "Name of the source entity"},
                "target_entity": {"type": "string", "description": "Name of the target entity"},
                "relationship": {"type": "string", "description": "Type of relationship (e.g. 'uses', 'depends_on', 'related_to')"},
                "description": {"type": "string", "description": "Optional description of the relationship"},
            },
            "required": ["source_entity", "target_entity", "relationship"],
        }

    def __init__(self, smol_rag):
        self.smol_rag = smol_rag

    async def execute(self, **kwargs) -> str:
        source = kwargs["source_entity"]
        target = kwargs["target_entity"]
        relationship = kwargs["relationship"]
        description = kwargs.get("description", relationship)

        graph = self.smol_rag.graph
        # Ensure both entity nodes exist
        if not graph.get_node(source):
            await graph.async_add_node(source, category="entity", description=source)
        if not graph.get_node(target):
            await graph.async_add_node(target, category="entity", description=target)
        # Create the edge
        await graph.async_add_edge(source, target, description=description, keywords=relationship, weight=1.0)
        return f"Related: {source} --[{relationship}]--> {target}"


class MemorySearchTool(Tool):
    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Search memory using vector + knowledge graph retrieval. Optionally filter by memory type."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "memory_type": {
                    "type": "string",
                    "enum": MEMORY_TYPES,
                    "description": "Optional: filter results to only this memory type",
                },
            },
            "required": ["query"],
        }

    def __init__(self, smol_rag):
        self.smol_rag = smol_rag

    async def execute(self, **kwargs) -> str:
        query = kwargs["query"]
        memory_type = kwargs.get("memory_type")
        result = await self.smol_rag.mix_query(query, memory_type=memory_type)
        await _promote_accessed_excerpts(self.smol_rag, query)
        return result


class MemoryGraphQueryTool(Tool):
    @property
    def name(self) -> str:
        return "memory_graph_query"

    @property
    def description(self) -> str:
        return "Query the knowledge graph for a specific entity and its relationships."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name to look up"},
            },
            "required": ["entity"],
        }

    def __init__(self, smol_rag):
        self.smol_rag = smol_rag

    async def execute(self, **kwargs) -> str:
        entity = kwargs["entity"]
        graph = self.smol_rag.graph
        node = graph.get_node(entity)
        if node is None:
            return f"No entity found: {entity}"

        lines = [f"Entity: {entity}"]
        for key, value in node.items():
            lines.append(f"  {key}: {value}")

        edges = graph.get_node_edges(entity)
        if edges:
            lines.append("Relationships:")
            for src, tgt in edges:
                edge_data = graph.get_edge((src, tgt))
                desc = edge_data.get("description", "") if edge_data else ""
                lines.append(f"  {src} -> {tgt}: {desc}")

        return "\n".join(lines)


class MemoryStoreTool(Tool):
    @property
    def name(self) -> str:
        return "memory_store"

    @property
    def description(self) -> str:
        return (
            "Store content into long-term memory (ingests into knowledge graph + vectors). "
            "Optionally classify with memory_type and tags for better retrieval."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Content to store in memory"},
                "source_id": {"type": "string", "description": "Optional source identifier"},
                "memory_type": {
                    "type": "string",
                    "enum": MEMORY_TYPES,
                    "description": (
                        "fact=durable atomic knowledge, decision=choice with rationale, "
                        "preference=personal attribute/style, episode=session event summary, "
                        "task=active work in progress, journal=first-person session reflection, "
                        "reference=external knowledge/docs/links"
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topic tags for categorisation (e.g. pricing, stripe, trello)",
                },
            },
            "required": ["content"],
        }

    def __init__(self, smol_rag, memory_docs_dir: str, llm=None):
        self.smol_rag = smol_rag
        self.memory_docs_dir = memory_docs_dir
        self.llm = llm

    async def execute(self, **kwargs) -> str:
        content = kwargs["content"]
        source_id = kwargs.get("source_id")
        memory_type = kwargs.get("memory_type")
        tags = kwargs.get("tags")

        # Auto-classify if no memory_type provided and LLM is available
        if not memory_type and self.llm:
            from app.taxonomy import classify_chunk
            classified_type, confidence = await classify_chunk(content, self.llm)
            memory_type = classified_type.value

        formatted = format_memory_content(content, memory_type, tags, source_id)

        os.makedirs(self.memory_docs_dir, exist_ok=True)
        file_id = source_id or make_hash(content, "mem-")
        file_path = os.path.join(self.memory_docs_dir, f"{file_id}.md")
        with open(file_path, "w") as f:
            f.write(formatted)

        await self.smol_rag.ingest_text(formatted, source_id=source_id)
        return f"Stored memory: {file_id}"


class MemoryGetTool(Tool):
    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return "Retrieve a specific memory by its excerpt ID."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "excerpt_id": {"type": "string", "description": "The excerpt ID to retrieve"},
            },
            "required": ["excerpt_id"],
        }

    def __init__(self, smol_rag):
        self.smol_rag = smol_rag

    async def execute(self, **kwargs) -> str:
        excerpt_id = kwargs["excerpt_id"]
        data = await self.smol_rag.excerpt_kv.get_by_key(excerpt_id)
        if not data:
            return f"No memory found with ID: {excerpt_id}"
        lines = [f"## Memory: {excerpt_id}"]
        if data.get("excerpt"):
            lines.append(f"\n{data['excerpt']}")
        if data.get("summary"):
            lines.append(f"\n**Summary**: {data['summary']}")
        for field in ["memory_type", "importance", "confidence", "indexed_at"]:
            if field in data:
                lines.append(f"- {field}: {data[field]}")
        return "\n".join(lines)


class MemoryRecallTool(Tool):
    @property
    def name(self) -> str:
        return "memory_recall"

    @property
    def description(self) -> str:
        return (
            "Recall past session content and memories. "
            "Use 'topic' mode for keyword+semantic search over past sessions. "
            "Use 'temporal' mode to find recent session memories by time."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "mode": {
                    "type": "string",
                    "enum": RECALL_MODES,
                    "description": "topic: hybrid BM25+vector+KG search; temporal: recent memories by time",
                },
                "days": {
                    "type": "number",
                    "description": "For temporal mode: how many days back to search (default 7)",
                },
            },
            "required": ["query", "mode"],
        }

    def __init__(self, smol_rag):
        self.smol_rag = smol_rag

    async def execute(self, **kwargs) -> str:
        query = kwargs["query"]
        mode = kwargs.get("mode", "topic")
        days = kwargs.get("days", 7)

        if mode == "topic":
            result = await self.smol_rag.mix_query(
                query, memory_type="episode", include_bm25=True,
            )
            await _promote_accessed_excerpts(self.smol_rag, query)
            return result
        elif mode == "temporal":
            return await self._temporal_query(days)
        return "Unknown recall mode."

    async def _temporal_query(self, days: float) -> str:
        cutoff = time.time() - (days * 86400)
        all_excerpts = await self.smol_rag.excerpt_kv.get_all()
        matches = []
        for excerpt_id, data in all_excerpts.items():
            if not isinstance(data, dict):
                continue
            if data.get("memory_type") != "episode":
                continue
            indexed_at = data.get("indexed_at", 0)
            if indexed_at >= cutoff:
                matches.append((indexed_at, data))

        if not matches:
            return "No recent session memories found."

        matches.sort(key=lambda x: x[0], reverse=True)
        parts = []
        for _, data in matches[:20]:
            excerpt = data.get("excerpt", "")
            summary = data.get("summary", "")
            parts.append(f"## Excerpt\n{excerpt}\n\n## Summary\n{summary}")
        return "\n\n---\n\n".join(parts)


