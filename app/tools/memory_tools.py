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
        return await self.smol_rag.mix_query(query, memory_type=memory_type)


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
        return "Read a memory file by its path or identifier from the memory directory."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File name or path within the memory directory (e.g. 'mem-abc123.md')",
                },
            },
            "required": ["path"],
        }

    def __init__(self, memory_docs_dir: str):
        self.memory_docs_dir = memory_docs_dir

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        # If it's just a filename, resolve relative to memory dir
        if not os.path.isabs(path):
            path = os.path.join(self.memory_docs_dir, path)
        if not os.path.exists(path):
            return f"Not found: {path}"
        with open(path) as f:
            return f.read()
