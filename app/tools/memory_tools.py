import os
from datetime import datetime, timezone

from app.tools.base import Tool
from app.utilities import make_hash

MEMORY_TYPES = ["fact", "decision", "preference", "episode", "task", "journal", "reference"]


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


class MemorySearchTool(Tool):
    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Search memory using vector + knowledge graph retrieval."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
            },
            "required": ["query"],
        }

    def __init__(self, smol_rag):
        self.smol_rag = smol_rag

    async def execute(self, **kwargs) -> str:
        query = kwargs["query"]
        return await self.smol_rag.mix_query(query)


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

    def __init__(self, smol_rag, memory_docs_dir: str):
        self.smol_rag = smol_rag
        self.memory_docs_dir = memory_docs_dir

    async def execute(self, **kwargs) -> str:
        content = kwargs["content"]
        source_id = kwargs.get("source_id")
        memory_type = kwargs.get("memory_type")
        tags = kwargs.get("tags")

        formatted = format_memory_content(content, memory_type, tags, source_id)

        os.makedirs(self.memory_docs_dir, exist_ok=True)
        file_id = source_id or make_hash(content, "mem-")
        file_path = os.path.join(self.memory_docs_dir, f"{file_id}.md")
        with open(file_path, "w") as f:
            f.write(formatted)

        await self.smol_rag.ingest_text(formatted, source_id=source_id)
        return f"Stored memory: {file_id}"
