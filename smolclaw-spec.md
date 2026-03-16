# SmolClaw: Graph-Augmented Memory for OpenClaw

**Product Specification — v0.1 Draft**
**February 2026**

---

## Problem

OpenClaw's memory system loads `MEMORY.md` and recent daily logs into the context window at session start. When the window fills, compaction summarises everything away. A silent flush writes durable notes to disk before compaction fires, but after the reset the agent can only run `memory_search` queries against chunked markdown and hope the right fragments surface.

The core failures are:

- **Compaction is destructive.** In-context memory is summarised away. Post-compaction retrieval depends entirely on search query quality.
- **Retrieval is single-hop.** The agent must know what to search for. If it doesn't form the right query, relevant memory never surfaces. There is no associative traversal.
- **No memory taxonomy.** `MEMORY.md` conflates atomic facts ("user prefers dark mode"), project decisions ("chose Postgres for auth"), episodic context ("refactored the API on Tuesday"), and personal preferences into a single unstructured file. Daily logs conflate scratchpad work with session notes.
- **No memory lifecycle.** There is no promotion, consolidation, expiration, or versioning. Memories are either in the file or they're not.
- **No relationships between memories.** Each chunk is an island. The only connection between memories is embedding similarity at query time.

The community has responded with plugins (Cognee, Graphiti, Mem0, Supermemory, Memory-X) that each solve a piece of this, but none compose the full stack: knowledge graph + taxonomy + efficient context assembly.

---

## Product

SmolClaw is an OpenClaw memory plugin (`kind: "memory"`) that replaces the default `memory-core` with a graph-augmented retrieval system built on SmolRAG. It indexes OpenClaw's existing markdown memory files into a knowledge graph with typed, taxonomised nodes, provides multi-modal retrieval (vector, local KG, global KG, hybrid, mix), and assembles context efficiently using summary-first loading with selective expansion.

SmolClaw is local-first. The graph, embeddings, and all memory data stay on the user's machine. No external API is required for core functionality — though users can optionally configure remote embedding providers for higher-quality vectors.

---

## Architecture

### Layer 1: Ingestion

SmolClaw watches the same files OpenClaw's default memory system uses:

- `MEMORY.md` — long-term curated memory
- `memory/YYYY-MM-DD.md` — daily logs
- `memory/**/*.md` — any additional markdown
- Session transcripts (when `sessionMemory` is enabled)

On change (debounced), SmolClaw:

1. **Chunks** the document using SmolRAG's `preserve_markdown_code_excerpts` — ~2,000-character overlapping chunks that keep code blocks intact, split at sentence boundaries.
2. **Summarises** each chunk with the full document as context, preserving positional information ("this excerpt covers the decision made mid-session about database choice").
3. **Classifies** each chunk into a memory type (see Taxonomy below) using a lightweight LLM classification pass.
4. **Extracts entities and relationships** into a NetworkX knowledge graph — the same entity/relationship extraction SmolRAG already performs, extended with type metadata.
5. **Embeds** both the chunk text and summary into the vector store.
6. **Hash-tracks** each source file for change detection. If a file's content hash changes, old entries are purged and new content is reingested.

Files remain the source of truth. SmolClaw never modifies the user's markdown. The graph and index are derived state that can be rebuilt from files at any time.

### Layer 2: Taxonomy

Every memory node in the graph carries a type. The initial taxonomy:

| Type | Description | Examples | Retention |
|------|-------------|----------|-----------|
| `fact` | Atomic, durable, rarely changes | "User prefers dark mode", "API runs on port 3000" | Persistent until contradicted |
| `decision` | A choice made with context | "Chose Postgres over SQLite for auth" | Persistent, linked to rationale |
| `preference` | Personal attribute or style | "Likes concise answers", "Uses Vim" | Persistent until updated |
| `episode` | Session-bounded event summary | "Refactored auth module on Tuesday" | Decays over time, consolidatable |
| `task` | Active work in progress | "Currently debugging the payment flow" | Short-lived, auto-expires |
| `journal` | First-person session recollection | "Spent the afternoon untangling auth — session tokens turned out way simpler than JWT, worth revisiting payments with the same approach" | Persistent, consolidatable |
| `reference` | External knowledge, docs, links | "Stripe API docs say X" | Persistent, source-linked |

Each node also carries metadata:

- `created_at` — timestamp
- `updated_at` — last modification
- `source_file` — originating markdown file and line range
- `confidence` — classification confidence score
- `tags` — user-defined or auto-extracted labels
- `importance` — derived from graph degree, recency, and access frequency

Types are used for filtered retrieval ("give me all decisions related to auth"), retention policies (episodes decay, facts persist), and context assembly prioritisation (active tasks and high-importance facts load first).

**Journal generation**: At session end, before compaction flush, SmolClaw prompts the agent to write a short first-person recollection of the session — a few sentences capturing what happened, why it mattered, what was learned, and any forward intent. The prompt is tuned for human cadence: reflective, interpretive, not clinical. The result is stored as a `journal` entry in the daily log alongside the system-generated `episode` entries.

The distinction matters for retrieval. Episodes answer "what happened" — they're mechanical session summaries. Journal entries answer "why it mattered" and "what should I do next" — they carry reasoning, surprise, intent, and opinion. When the agent later searches for context on a topic, journal entries surface the interpretive layer that episodes miss. Retrieval can weight journal entries higher for intent-bearing queries.

### Layer 3: Knowledge Graph

The graph stores two kinds of nodes:

- **Entity nodes** — extracted named entities (people, projects, technologies, concepts) with type metadata
- **Memory nodes** — the classified memory chunks themselves

And edges:

- **Entity-to-entity** — relationships extracted from text ("Postgres" → "auth module", relationship: "chosen for")
- **Memory-to-entity** — which memories mention which entities
- **Memory-to-memory** — temporal adjacency (same session), causal links (decision → rationale), and contradiction links

This enables associative retrieval: start from a query match, traverse to related entities, follow edges to memories the query wouldn't have found directly.

### Layer 4: Retrieval

SmolClaw exposes the same `memory_search` and `memory_get` tool interface OpenClaw expects, plus additional tools:

**`memory_search`** (drop-in replacement)
Runs SmolRAG's `mix_query` by default — combines vector similarity over summaries with hybrid KG traversal. Returns ranked results with snippets, source paths, memory types, and graph context.

Falls back gracefully: if the graph is empty or indexing is in progress, pure vector search over summaries still works.

**`memory_get`** (drop-in replacement)
Reads a specific markdown file by path. Unchanged from default behaviour.

**`memory_graph_query`** (new tool)
Accepts an entity name or memory ID and returns the local subgraph — connected entities, relationships, and associated memory chunks. Enables the agent to explore context associatively rather than formulating search queries.

**`memory_store`** (new tool)
Explicitly stores a classified memory with type, tags, and metadata. Writes to the appropriate markdown file (facts → `MEMORY.md`, episodes → daily log) and updates the graph index.

**`memory_relate`** (new tool)
Creates an explicit edge between two memories or entities. Lets the agent build connections it discovers during reasoning.

### Layer 5: Context Assembly

Between retrieval and the context window sits the assembly layer — the token efficiency strategy for getting more memory awareness into less context space.

When the agent's turn begins:

1. **Budget calculation** — determine available tokens after system prompt, session history, and tool definitions.
2. **Priority retrieval** — pull active tasks and high-importance facts first, then relevant episodic context, then supporting references. Type-based priority ensures the most actionable context loads first.
3. **Summary-first loading** — retrieved memories enter the context as their summaries (compact representations), not full text. Most chunks are represented compactly, only expanded when needed. This is a prompt-level optimisation: the agent sees more memories in fewer tokens.
4. **Selective expansion** — if the agent's response references a specific memory, the full chunk text is available via `memory_get`. The agent can pull full detail on demand rather than having everything expanded upfront.
5. **Manifest logging** — every assembly step is logged: what was retrieved, what was included, what was excluded and why, token budget consumed. This makes context assembly debuggable.

This approach means the agent can have awareness of 50+ relevant memories (via summaries) while only paying full token cost for the handful it actually needs.

### Layer 6: Lifecycle

Memories evolve through defined states:

```
[scratchpad] → [episode] → [fact/decision/preference]
     ↓              ↓              ↓
  [expired]     [archived]    [persistent]
```

**Promotion**: The agent or a background process can promote memories up the chain. A scratchpad note that proves durable becomes an episode. An episode that captures a lasting decision gets promoted to a fact. Each promotion is a logged, timestamped event.

**Consolidation**: Multiple related episodes can be consolidated into a single summary. The originals are archived (retained for audit) and the consolidated version takes their place in the active graph.

**Decay**: Episodes and tasks carry a decay score based on recency, access frequency, and graph connectivity. Low-scoring memories are archived — removed from the active graph but retained on disk and searchable.

**Contradiction detection**: When a new memory contradicts an existing fact (e.g., "user switched from Postgres to MySQL"), the system flags the conflict. The old fact is marked superseded with a link to the new one.

**Audit trail**: Every state transition (creation, promotion, consolidation, archival, contradiction) is logged with timestamp, trigger (agent action, background process, user edit), and before/after state. Users can diff memory evolution and inject corrections.

---

## OpenClaw Integration

### Plugin Manifest

```json
{
  "id": "memory-smolclaw",
  "name": "SmolClaw Memory",
  "kind": "memory",
  "configSchema": {
    "type": "object",
    "properties": {
      "embeddingProvider": {
        "type": "string",
        "enum": ["local", "openai", "gemini"],
        "default": "local",
        "description": "Embedding provider for vector search"
      },
      "localModelPath": {
        "type": "string",
        "description": "Path to local GGUF embedding model"
      },
      "graphStore": {
        "type": "string",
        "default": "~/.openclaw/smolclaw/{agentId}/graph.json",
        "description": "Path to the knowledge graph store"
      },
      "vectorStore": {
        "type": "string",
        "default": "~/.openclaw/smolclaw/{agentId}/vectors.db",
        "description": "Path to the vector store"
      },
      "decayIntervalHours": {
        "type": "number",
        "default": 168,
        "description": "Hours between decay evaluation passes"
      },
      "summaryModel": {
        "type": "string",
        "default": "auto",
        "description": "Model used for chunk summarisation and classification. 'auto' uses the agent's configured model."
      },
      "maxContextTokens": {
        "type": "number",
        "default": 4000,
        "description": "Token budget for memory context injection"
      }
    }
  }
}
```

### Lifecycle Hooks

SmolClaw registers for:

- **`onSessionStart`** — warm the index, run summary-first context assembly for initial injection
- **`onBeforeTurn`** — query graph for context relevant to the current message, assemble and inject
- **`onAfterTurn`** — extract and classify new memories from the exchange, update graph
- **`onCompactionFlush`** — enhanced flush that writes classified, typed memories rather than raw daily log entries. Generates a journal entry (first-person session recollection) before flushing.
- **`onFileChange`** — reindex modified markdown files

### Tool Registration

SmolClaw replaces the default `memory_search` and `memory_get` tools and adds `memory_graph_query`, `memory_store`, and `memory_relate`. The agent's system prompt is augmented with guidance on when to use graph traversal versus direct search.

### Backward Compatibility

SmolClaw reads the same markdown files as default OpenClaw memory. If the plugin is disabled, the user falls back to `memory-core` with zero data loss — the files were never modified. The graph and index are derived state stored separately under `~/.openclaw/smolclaw/`.

---

## Competitive Landscape

| Feature | Default Memory | Mem0 | Supermemory | Cognee | SmolClaw |
|---------|---------------|------|-------------|--------|----------|
| Local-first | ✅ | ❌ (cloud) | ❌ (cloud) | ✅ | ✅ |
| Knowledge graph | ❌ | ❌ | ❌ | ✅ | ✅ |
| Memory taxonomy | ❌ | Partial (long/short term) | Partial (profile) | ❌ | ✅ |
| Associative retrieval | ❌ | ❌ | ❌ | ✅ | ✅ |
| Summary layer | ❌ | ❌ | ❌ | ❌ | ✅ |
| Compaction-safe | ❌ | ✅ | ✅ | ✅ | ✅ |
| Lifecycle management | ❌ | Partial (dedup) | Partial (staleness) | ❌ | ✅ |
| Audit trail | ❌ | ❌ | ❌ | ❌ | ✅ |
| Context assembly | ❌ | Auto-recall | Auto-recall | ❌ | Budget-aware assembly |
| Files as source of truth | ✅ | ❌ | ❌ | ✅ | ✅ |
| No external API required | ✅ | ❌ | ❌ | ❌ | ✅ |
| Multiple query modes | ❌ | ❌ | ❌ | ❌ | ✅ (5 modes) |

SmolClaw's differentiators: the only local-first option that combines a knowledge graph with typed taxonomy, summary-based efficient context assembly, full lifecycle management, and audit logging — while keeping markdown files as the source of truth and requiring no external API.

---

## Monetisation

### Model: Freemium Plugin

**Free tier — SmolClaw Core**

- Full knowledge graph with entity/relationship extraction
- Vector + BM25 hybrid search (SmolRAG's existing query modes)
- Local embeddings (GGUF models, no API key required)
- Hash-based change detection and reindexing
- Drop-in replacement for `memory_search` / `memory_get`
- Basic memory classification (fact/episode/journal/task)

This tier is fully functional and solves the core problem: graph-augmented retrieval that survives compaction.

**Paid tier — SmolClaw Pro** (target: $9–15/month or $89–129/year)

- Full taxonomy with all seven types and custom user-defined types
- Lifecycle management (promotion, consolidation, decay, contradiction detection)
- Budget-aware context assembly with manifest logging
- `memory_graph_query`, `memory_store`, `memory_relate` tools
- Audit trail with diff history and version browsing
- Priority-based context injection (type-aware token budgeting)
- Multi-agent shared memory (graph partitioning across agents)
- Web dashboard for graph visualisation, memory browsing, and audit review
- Configurable retention policies per memory type

**Licensing**: License key validated locally. No cloud dependency. The key unlocks Pro features in the plugin binary. No telemetry, no data leaves the machine.

### Why Users Pay

The free tier already beats default OpenClaw memory. The paid tier is for users who:

- Run long-lived agents across weeks/months and need lifecycle management to prevent memory rot
- Work on multiple projects and need taxonomy + filtered retrieval to avoid cross-project noise
- Want debuggability — when the agent gets something wrong, they can trace what context it had
- Run multi-agent setups and need shared memory with proper partitioning
- Want a visual interface to browse and curate the knowledge graph

### Distribution

Published to ClawHub as a skill/plugin. Install via `openclaw plugins install smolclaw`. Configuration through `openclaw.json` with the plugin's config schema. Pro activation via `openclaw smolclaw activate <license-key>`.

Payment and license management through a simple web storefront (Stripe + license key generation). No account system beyond email for license delivery.

---

## Technical Foundation

SmolClaw is built on SmolRAG (`github.com/OrderAndCh4oS/smol-rag`), which provides:

- **Document ingestion** — async chunking with markdown-aware splitting, per-chunk summarisation with document context, hash-based change detection
- **Knowledge graph** — NetworkX-based entity and relationship extraction, stored locally
- **Vector store** — SQLite-backed vectors with OpenAI-compatible embeddings
- **Five query modes** — vector search, local KG, global KG, hybrid KG, and mix (vector + KG combined)
- **Graph visualisation** — existing visualisation tooling in the repo

SmolRAG is Python. OpenClaw plugins are TypeScript/Node. The integration path is either:

1. **SmolRAG as a sidecar process** — Python process managed by the plugin, communicating via JSON over stdin/stdout or a local HTTP API. Similar to how OpenClaw manages the QMD sidecar for its alternative memory backend.
2. **Port core logic to TypeScript** — rewrite the graph, vector, and query logic in TypeScript for native plugin integration. Higher upfront cost, simpler runtime.

Recommended: **Option 1** for initial release. OpenClaw already has precedent for sidecar processes (QMD). This lets us ship faster using proven SmolRAG code. Option 2 can follow if performance or distribution simplicity demands it.

---

## Implementation Phases

### Phase 1: Drop-in Replacement (Weeks 1–4)

Ship a working `kind: "memory"` plugin that replaces default memory with SmolRAG-backed retrieval.

- Watch and ingest markdown memory files
- Chunk, summarise, embed, extract entities/relationships
- Implement `memory_search` using SmolRAG's `mix_query`
- Implement `memory_get` passthrough
- Hash-based change detection
- Local embedding support (no API key required)
- Plugin manifest, config schema, installation via ClawHub

Outcome: users install one plugin and get graph-augmented memory search that survives compaction. This is the free tier.

### Phase 2: Taxonomy and New Tools (Weeks 5–8)

Add memory classification and the expanded tool surface.

- LLM-based chunk classification into the seven memory types
- Type metadata on graph nodes
- `memory_graph_query` tool for associative traversal
- `memory_store` tool for explicit classified memory creation
- `memory_relate` tool for explicit edge creation
- Filtered search by memory type
- System prompt augmentation guiding the agent on tool usage

### Phase 3: Context Assembly (Weeks 9–12)

Add the budget-aware assembly layer between retrieval and the context window.

- Token budget calculation based on window size and existing context
- Priority retrieval based on memory type and importance
- Summary-first loading (compact representations by default)
- Selective expansion via `memory_get`
- Manifest logging for every assembly step
- `onBeforeTurn` and `onAfterTurn` hooks wired up

### Phase 4: Lifecycle and Pro Features (Weeks 13–16)

Add memory lifecycle management and the paid tier.

- Promotion, consolidation, decay, contradiction detection
- Audit trail with timestamped state transitions
- Configurable retention policies per type
- Web dashboard for graph visualisation and audit browsing
- License key system and Pro activation
- Multi-agent shared memory support

---

## Areas to Explore

### Obsidian Integration (Optional, Additive)

Obsidian is not a requirement. SmolClaw's core product is the graph, the taxonomy, and the retrieval. Obsidian is one surface the graph can project to — users who don't use it lose nothing.

The config defaults to off:

```json
"obsidianSync": {
  "enabled": false,
  "vaultPath": null,
  "projectionFolder": "SmolClaw",
  "parseWikiLinks": true,
  "parseTags": true,
  "parseFrontmatter": true
}
```

**When disabled (default)**: SmolClaw reads any paths configured in OpenClaw's `extraPaths` and indexes them like any other markdown. The graph lives internally. No Obsidian awareness at all.

**When enabled**: Two additive behaviours activate.

**Inbound — richer graph from Obsidian-native structures**:

SmolClaw parses Obsidian-specific structures from files in the vault path and feeds them into the knowledge graph:

- `[[wiki links]]` between notes become graph edges between entity nodes
- `#tags` become taxonomy labels on the associated memory nodes
- YAML frontmatter properties map to node metadata (type, importance, custom fields)
- Folder hierarchy can optionally inform memory type classification

This means users who already maintain a heavily linked Obsidian vault get a richer knowledge graph without any extra work. Their existing structure becomes SmolClaw structure.

**Outbound — graph projection as browsable markdown**:

SmolClaw writes its knowledge graph back into a subfolder of the vault (default: `SmolClaw/`) as standard markdown files:

- One file per entity node
- Frontmatter carries type, metadata, timestamps, importance
- Body contains associated memory summaries with source links
- `[[wiki links]]` between files represent graph edges
- `#tags` match the taxonomy labels

Obsidian renders this natively — graph view shows the knowledge graph, search finds memories, Dataview can query frontmatter properties. Users browse, navigate, and understand the agent's memory through a tool they already know.

**Bidirectional editing**: Users can edit projected files from Obsidian. Add a `[[link]]` and SmolClaw picks it up as a new graph edge on next sync. Edit frontmatter and the taxonomy updates. Delete a file and the entity is flagged for review. The user's knowledge tool becomes a direct interface to the agent's memory.

**Key considerations**:

- **Write loop prevention**: SmolClaw ignores its own writes via timestamp tracking — standard debounce, not architecturally complex.
- **Conflict resolution**: If both SmolClaw and the user edit a projected file, last-write-wins with the previous version retained in the audit trail. User edits take priority when detected.
- **Projection scope**: Configurable — project the full graph, or filter by type, importance threshold, or recency. Large graphs shouldn't flood the vault.
- **Not Obsidian-specific**: The projection is just markdown files in a folder. Logseq, Notion local exports, or any markdown-based tool could consume the same output. Obsidian is the first target because the user base overlaps with OpenClaw's audience, but the mechanism is tool-agnostic.

**Monetisation fit**: Natural Pro feature. Free tier indexes Obsidian vaults (inbound). Paid tier adds the graph projection (outbound) and bidirectional sync.

---

## Open Questions

1. **Classification accuracy**: How reliable is LLM-based chunk classification across different memory types? Needs benchmarking against manually labelled memory files. Misclassification degrades filtered retrieval.

2. **Graph scale**: How large does the graph get after months of daily use? NetworkX is in-memory. At what point do we need to move to an on-disk graph store?

3. **Summarisation cost**: Per-chunk summarisation using the agent's model adds latency and token cost during ingestion. Is the quality improvement worth it, or should we offer a fast mode that skips summarisation?

4. **Sidecar vs native**: The Python sidecar approach adds a runtime dependency. How much friction does this create for users who just want to `npm install` and go?

5. **Compaction interaction**: SmolClaw's `onCompactionFlush` hook writes classified memories. Does this interact cleanly with OpenClaw's existing flush mechanism, or do we need to disable the default flush entirely?

6. **Embedding model choice**: Local GGUF embeddings are convenient but lower quality than OpenAI/Gemini. How much does retrieval quality degrade with local models, and is it worth the privacy tradeoff?

---

## Success Metrics

- **Retrieval accuracy**: Percentage of relevant memories surfaced in top-5 results, benchmarked against default `memory_search` on the same query set.
- **Compaction survival**: After compaction, can the agent recover context that default memory loses? Measured by task continuity across compaction boundaries.
- **Installation-to-value**: Time from `openclaw plugins install smolclaw` to first successful graph-augmented query. Target: under 5 minutes.
- **Free-to-paid conversion**: Percentage of free tier users who activate Pro. Target: 5–10% at steady state.
- **Graph coverage**: Percentage of memory file content represented in the graph after initial indexing. Target: >95%.
