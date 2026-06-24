import time
from datetime import datetime, timezone

from app.memory_documents import MemoryDocumentService
from app.tools.base import Tool, ToolCallPolicy, ToolResult, ToolRuntimeContext

from app.lifecycle import MemoryLifecycleManager

MEMORY_TYPES = ["fact", "decision", "preference", "episode", "task", "journal", "reference"]


async def _promote_accessed_excerpts(smol_rag, excerpt_ids: list[str], boost: float = 0.05):
    """Promote the excerpts a memory tool actually surfaced to the agent."""
    try:
        mgr = MemoryLifecycleManager(smol_rag)
        seen = set()
        for excerpt_id in excerpt_ids:
            if not excerpt_id or excerpt_id in seen:
                continue
            seen.add(excerpt_id)
            await mgr.promote(excerpt_id, boost=boost)
    except Exception:
        pass  # Promotion is best-effort


RECALL_MODES = ["topic", "temporal"]


def _memory_query_result(result: str | dict) -> ToolResult:
    if isinstance(result, dict):
        excerpt_ids = []
        seen = set()
        for excerpt_id in result.get("excerpt_ids", []):
            if not excerpt_id or excerpt_id in seen:
                continue
            seen.add(excerpt_id)
            excerpt_ids.append(excerpt_id)
        return ToolResult(
            status="ok",
            content=result.get("content", ""),
            metadata={"accessed_excerpt_ids": excerpt_ids},
        )
    return ToolResult(
        status="ok",
        content=str(result),
        metadata={"accessed_excerpt_ids": []},
    )


def format_memory_content(
    content: str,
    memory_type: str | None = None,
    tags: list[str] | None = None,
    source_id: str | None = None,
    tier: int | None = None,
) -> str:
    """Format memory content with YAML frontmatter and inline tags when taxonomy is provided."""
    if not memory_type and not tags and tier is None:
        return content

    fm_lines = ["---"]
    if memory_type:
        fm_lines.append(f"memory_type: {memory_type}")
    if tier is not None:
        fm_lines.append(f"tier: {tier}")
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
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(
            effects=frozenset({"memory_write"}),
            mutates_state=True,
            tags=frozenset({"memory"}),
        )

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
    def examples(self) -> list[dict]:
        return [
            {"description": "Connect two concepts", "arguments": {"source_entity": "SmolClaw", "target_entity": "SQLite", "relationship": "uses"}},
            {"description": "Relate with description", "arguments": {"source_entity": "auth-service", "target_entity": "JWT", "relationship": "depends_on", "description": "Uses JWT for session tokens"}},
        ]

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

    async def execute(self, **kwargs) -> ToolResult:
        source = kwargs["source_entity"]
        target = kwargs["target_entity"]
        relationship = kwargs["relationship"]
        description = kwargs.get("description", relationship)

        # Ensure both entity nodes exist
        if not self.smol_rag.get_graph_node(source):
            await self.smol_rag.add_graph_node(source, category="entity", description=source)
        if not self.smol_rag.get_graph_node(target):
            await self.smol_rag.add_graph_node(target, category="entity", description=target)
        # Create the edge
        await self.smol_rag.add_graph_edge(source, target, description=description, keywords=relationship, weight=1.0)
        return f"Related: {source} --[{relationship}]--> {target}"


class MemorySearchTool(Tool):
    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search memory using hybrid retrieval (vector similarity + knowledge graph + full-text). "
            "Best for broad questions, finding related concepts, or when you don't know the exact entity name. "
            "Use this first when answering questions — check what you already know before searching the web. "
            "Supports filtering by memory_type (fact, decision, preference, episode, task, journal, reference)."
        )

    @property
    def examples(self) -> list[dict]:
        return [
            {"description": "Broad search across all memory types", "arguments": {"query": "Python web frameworks"}},
            {"description": "Filter to decisions only", "arguments": {"query": "pricing strategy", "memory_type": "decision"}},
            {"description": "Find preferences", "arguments": {"query": "coding style", "memory_type": "preference"}},
        ]

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

    async def execute(self, **kwargs) -> ToolResult:
        query = kwargs["query"]
        memory_type = kwargs.get("memory_type")
        result = await self.smol_rag.mix_query(
            query,
            memory_type=memory_type,
            return_metadata=True,
        )
        return _memory_query_result(result)


class MemoryGraphQueryTool(Tool):
    @property
    def name(self) -> str:
        return "memory_graph_query"

    @property
    def description(self) -> str:
        return (
            "Look up a specific entity in the knowledge graph and see its relationships. "
            "Use this when you know the exact entity name and want to explore its connections. "
            "For broader searches where you don't know the entity name, use memory_search instead."
        )

    @property
    def examples(self) -> list[dict]:
        return [
            {"description": "Look up a known entity", "arguments": {"entity": "SmolClaw"}},
            {"description": "Explore a concept's connections", "arguments": {"entity": "pricing-engine"}},
        ]

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

    async def execute(self, **kwargs) -> ToolResult | str:
        entity = kwargs["entity"]
        node = self.smol_rag.get_graph_node(entity)
        if node is None:
            return f"No entity found: {entity}"

        lines = [f"Entity: {entity}"]
        for key, value in node.items():
            lines.append(f"  {key}: {value}")

        edges = self.smol_rag.get_graph_edges(entity)
        if edges:
            lines.append("Relationships:")
            for src, tgt in edges:
                edge_data = self.smol_rag.get_graph_edge((src, tgt))
                desc = edge_data.get("description", "") if edge_data else ""
                lines.append(f"  {src} -> {tgt}: {desc}")

        return "\n".join(lines)


class MemoryStoreTool(Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(
            effects=frozenset({"memory_write"}),
            mutates_state=True,
            tags=frozenset({"memory"}),
        )

    @property
    def name(self) -> str:
        return "memory_store"

    @property
    def description(self) -> str:
        return (
            "Store content into long-term memory (ingests into knowledge graph + vectors). "
            "Use this to save important facts, decisions, preferences, or findings for future sessions. "
            "Classify with memory_type (fact, decision, preference, task, reference) and tags for better retrieval. "
            "If memory_type is omitted, it will be auto-classified."
        )

    @property
    def examples(self) -> list[dict]:
        return [
            {"description": "Store a fact with tags", "arguments": {"content": "The API rate limit is 100 req/s", "memory_type": "fact", "tags": ["api", "limits"]}},
            {"description": "Store an identity-tier core memory", "arguments": {"content": "User prefers concise responses", "memory_type": "preference", "tier": 0}},
            {"description": "Auto-classify with source", "arguments": {"content": "Decided to use PostgreSQL for the new service", "source_id": "meeting-2026-03-15"}},
        ]

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
                "tier": {
                    "type": "integer",
                    "enum": [0, 1, 2],
                    "description": (
                        "Memory tier: 0=identity (always in context, never decays), "
                        "1=core (high priority, slow decay), "
                        "2=working (default, normal decay). "
                        "Use tier 0 for essential knowledge the agent must always have. "
                        "Use tier 1 for important facts and decisions. "
                        "Default tier 2 for session observations."
                    ),
                },
            },
            "required": ["content"],
        }

    def __init__(self, smol_rag, memory_docs_dir: str, llm=None):
        self.smol_rag = smol_rag
        self.memory_docs_dir = memory_docs_dir
        self.llm = llm

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return MemoryStoreTool(
            self.smol_rag,
            self.memory_docs_dir,
            llm=runtime_ctx.llm or self.llm,
        )

    async def execute(self, **kwargs) -> str:
        content = kwargs["content"]
        source_id = kwargs.get("source_id")
        memory_type = kwargs.get("memory_type")
        tags = kwargs.get("tags")
        tier = kwargs.get("tier")

        # Auto-classify if no memory_type provided and LLM is available
        if not memory_type and self.llm:
            from app.taxonomy import classify_chunk
            classified_type, confidence = await classify_chunk(content, self.llm)
            memory_type = classified_type.value

        service = MemoryDocumentService(
            self.smol_rag,
            memory_dir=self.memory_docs_dir,
        )
        final_source_id = service.memory_source_id(content, source_id)
        formatted = format_memory_content(content, memory_type, tags, final_source_id, tier=tier)
        stored = await service.store_document(
            formatted,
            kind="memory",
            source_id=final_source_id,
        )
        return f"Stored memory: {stored.source_id}"


class MemoryGetTool(Tool):
    @property
    def exposure(self) -> str:
        return "deferred"

    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return "Retrieve a specific memory excerpt by its ID. Use when you have an exact excerpt ID from a previous search result."

    @property
    def examples(self) -> list[dict]:
        return [
            {"description": "Retrieve by ID from a search result", "arguments": {"excerpt_id": "exc-a1b2c3d4"}},
        ]

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
        data = await self.smol_rag.get_excerpt(excerpt_id)
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


class ContradictionReviewTool(Tool):
    def get_call_policy(self, arguments: dict | None = None) -> ToolCallPolicy:
        action = (arguments or {}).get("action")
        if action == "resolve":
            return ToolCallPolicy(
                effects=frozenset({"memory_write"}),
                mutates_state=True,
                tags=frozenset({"memory", "contradiction"}),
            )
        return ToolCallPolicy(tags=frozenset({"memory", "contradiction"}))

    @property
    def name(self) -> str:
        return "contradiction_review"

    @property
    def description(self) -> str:
        return (
            "Review and resolve contradictions detected in the knowledge graph. "
            "Use 'list' to see pending conflicts between entities or relationships. "
            "Use 'detail' with a contradiction_id to see full context. "
            "Use 'resolve' to apply a resolution (keep_existing, keep_new, merge, dismiss). "
            "Check this when you encounter conflicting information or after ingesting updated content."
        )

    @property
    def examples(self) -> list[dict]:
        return [
            {"description": "List pending contradictions", "arguments": {"action": "list"}},
            {"description": "View full detail of a contradiction", "arguments": {"action": "detail", "contradiction_id": "ctr-abc123"}},
            {"description": "Resolve by keeping the newer value", "arguments": {"action": "resolve", "contradiction_id": "ctr-abc123", "resolution": "keep_new", "note": "Updated info from latest meeting"}},
        ]

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "resolve", "detail"],
                    "description": "Action to perform",
                },
                "contradiction_id": {
                    "type": "string",
                    "description": "ID of the contradiction (for resolve/detail)",
                },
                "resolution": {
                    "type": "string",
                    "enum": ["keep_existing", "keep_new", "merge", "dismiss"],
                    "description": "Resolution to apply (for resolve action)",
                },
                "note": {
                    "type": "string",
                    "description": "Optional explanation for the resolution",
                },
            },
            "required": ["action"],
        }

    def __init__(self, contradiction_detector):
        self.detector = contradiction_detector

    async def execute(self, **kwargs) -> str:
        action = kwargs["action"]

        if action == "list":
            pending = await self.detector.get_pending(limit=10)
            if not pending:
                return "No pending contradictions."
            lines = [f"**{len(pending)} pending contradiction(s):**\n"]
            for r in pending:
                entity = r.get("entity_name") or r.get("edge_key", "unknown")
                lines.append(
                    f"- `{r['id']}` [{r['kind']}] **{entity}**\n"
                    f"  Existing: {_truncate(r.get('existing_value', ''), 80)}\n"
                    f"  New: {_truncate(r.get('new_value', ''), 80)}\n"
                    f"  Verdict: {r.get('verdict')} (confidence: {r.get('confidence', 0):.2f})"
                )
            return "\n".join(lines)

        elif action == "detail":
            cid = kwargs.get("contradiction_id")
            if not cid:
                return "contradiction_id is required for detail action."
            record = await self.detector.store.get_by_key(cid)
            if not record:
                return f"No contradiction found with ID: {cid}"
            lines = [f"**Contradiction: {cid}**\n"]
            for key in ("kind", "entity_name", "edge_key", "existing_value",
                        "new_value", "verdict", "confidence", "status",
                        "source", "resolution_note", "existing_excerpt_id",
                        "new_excerpt_id", "created_at", "resolved_at"):
                val = record.get(key)
                if val is not None:
                    lines.append(f"- **{key}**: {val}")
            return "\n".join(lines)

        elif action == "resolve":
            cid = kwargs.get("contradiction_id")
            resolution = kwargs.get("resolution")
            if not cid or not resolution:
                return "Both contradiction_id and resolution are required."
            note = kwargs.get("note")
            result = await self.detector.resolve(cid, resolution, note=note)
            if not result:
                return f"No contradiction found with ID: {cid}"
            return f"Resolved {cid} as **{result['status']}**."

        return f"Unknown action: {action}"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


class MemoryRecallTool(Tool):
    @property
    def name(self) -> str:
        return "memory_recall"

    @property
    def description(self) -> str:
        return (
            "Recall past session content and memories. "
            "Use 'topic' mode for keyword+semantic search across all past sessions. "
            "Use 'temporal' mode with --days to find recent session memories by time range. "
            "Use this when you need to remember what was discussed in previous conversations."
        )

    @property
    def examples(self) -> list[dict]:
        return [
            {"description": "Search past sessions by topic", "arguments": {"query": "database migration", "mode": "topic"}},
            {"description": "Find recent memories from last 3 days", "arguments": {"query": "recent work", "mode": "temporal", "days": 3}},
        ]

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

    def __init__(self, smol_rag, return_tool_result: bool = False):
        self.smol_rag = smol_rag
        self.return_tool_result = return_tool_result

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return MemoryRecallTool(
            self.smol_rag,
            return_tool_result=True,
        )

    async def _format_return(self, result: ToolResult) -> ToolResult | str:
        if self.return_tool_result:
            return result
        excerpt_ids = result.metadata.get("accessed_excerpt_ids") or []
        if excerpt_ids:
            await _promote_accessed_excerpts(self.smol_rag, excerpt_ids)
        return result.content

    async def execute(self, **kwargs) -> ToolResult | str:
        query = kwargs["query"]
        mode = kwargs.get("mode", "topic")
        days = kwargs.get("days", 7)

        if mode == "topic":
            result = await self.smol_rag.mix_query(
                query,
                memory_type="episode",
                include_bm25=True,
                return_metadata=True,
            )
            return await self._format_return(_memory_query_result(result))
        elif mode == "temporal":
            return await self._format_return(await self._temporal_query(days))
        return "Unknown recall mode."

    async def _temporal_query(self, days: float) -> ToolResult:
        cutoff = time.time() - (days * 86400)
        all_excerpts = await self.smol_rag.get_all_excerpts()
        matches = []
        for excerpt_id, data in all_excerpts.items():
            if not isinstance(data, dict):
                continue
            if data.get("memory_type") != "episode":
                continue
            indexed_at = data.get("indexed_at", 0)
            if indexed_at >= cutoff:
                matches.append((indexed_at, excerpt_id, data))

        if not matches:
            return ToolResult(
                status="ok",
                content="No recent session memories found.",
                metadata={"accessed_excerpt_ids": []},
            )

        matches.sort(key=lambda x: x[0], reverse=True)
        parts = []
        excerpt_ids = []
        for _, excerpt_id, data in matches[:20]:
            excerpt_ids.append(excerpt_id)
            excerpt = data.get("excerpt", "")
            summary = data.get("summary", "")
            parts.append(f"## Excerpt\n{excerpt}\n\n## Summary\n{summary}")
        return ToolResult(
            status="ok",
            content="\n\n---\n\n".join(parts),
            metadata={"accessed_excerpt_ids": excerpt_ids},
        )
