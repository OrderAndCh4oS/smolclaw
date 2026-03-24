# SmolClaw

SmolClaw is a memory-first agent with persistent, associative memory. It pairs a knowledge graph and vector retrieval backend (SmolRAG) with a tool-using agent loop that can search the web, read/write files, execute shell commands, and maintain long-term memory across sessions. Both a CLI and a WebSocket gateway are available as interfaces.

## How It Works

SmolClaw has two layers. The bottom layer, SmolRAG, handles ingestion, embedding, entity extraction, and retrieval. The top layer provides an agent loop with tool use, session persistence, and multi-agent orchestration.

When you ingest a document, SmolRAG splits it into overlapping chunks that keep Markdown code blocks intact, summarises each chunk for context quality, embeds everything into a vector store, and extracts entities and relationships into a NetworkX knowledge graph.

When you ask a question, SmolClaw combines semantic vector search with knowledge graph traversal to build rich context for the LLM. Five query modes give you control over the retrieval strategy, from pure vector similarity to full hybrid search that merges both approaches.

Change detection is automatic. Every document is content-hashed on ingest. If a file's hash changes, the old embeddings and graph entries are cleaned up and the new content is reingested, so answers always reflect the latest state of your source material.

## Getting Started

SmolClaw requires Python 3.11+. Set up with pyenv or your preferred version manager, then install dependencies into a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with your API keys. SmolClaw supports both OpenAI and Anthropic models:

```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

## CLI Usage

SmolClaw's CLI has six commands: `chat`, `ingest`, `watch`, `serve`, `recall`, and `reset`.

### Interactive Chat

Start a conversation with the default SmolClaw agent. It has access to all tools and reads `AGENT.md` as its bootstrap context:

```bash
python -m cli.main chat
```

You can switch sessions, models, or run a named agent from `agents.yaml`:

```bash
python -m cli.main chat --session my-project --model gpt-4o
python -m cli.main chat --agent default
```

### Document Ingestion

Ingest a single file or an entire directory into the knowledge graph and vector store:

```bash
python -m cli.main ingest memory/
python -m cli.main ingest path/to/specific-file.md
```

Unchanged files are skipped automatically thanks to content hashing.

### Watch Mode

Watch the memory directory for file changes and re-ingest automatically:

```bash
python -m cli.main watch
```

### WebSocket Server

Start the WebSocket gateway for programmatic access:

```bash
python -m cli.main serve
```

### Reset

Wipe all persistent data — memories, sessions, indexes, and caches — for a full reset. The `input_docs/` directory (your source material) is preserved.

```bash
python -m cli.main reset
```

You'll be prompted for confirmation. Pass `--force` to skip it (useful for scripts):

```bash
python -m cli.main reset --force
```

This deletes the SQLite database, the knowledge graph, and all files in `sessions/`, `memory/`, `logs/`, and `cache/`. After a reset, stores are recreated automatically the next time you run any command.

### Session Recall

Search past sessions by topic or time range:

```bash
python -m cli.main recall "what did we discuss about auth?"
python -m cli.main recall "last week" --mode temporal --days 7
```

### Session Indexing

Index all past sessions into SmolRAG for retrieval:

```bash
python -m cli.main index-sessions
```

### Clear Logs

Delete log files without touching data stores:

```bash
python -m cli.main clear-logs
```

## Tools

Every agent draws from a shared tool registry. The available tools cover four categories.

**Memory** tools let agents search the knowledge graph with `memory_search` (hybrid vector + KG retrieval with optional memory type filtering), query specific entities and their relationships with `memory_graph_query`, store new memories with taxonomy classification via `memory_store`, create explicit graph edges between entities with `memory_relate`, retrieve past sessions with `memory_recall`, and review contradictions with `contradiction_review`.

**Filesystem** tools provide `read_file`, `write_file`, `edit_file`, and `list_dir` within a sandboxed workspace directory.

**Web** tools include `web_search` for internet queries and `web_fetch` for retrieving and reading web page content.

**Shell** execution via `exec` runs arbitrary commands with dangerous-pattern blocking and timeout.

**Multi-agent** tools (`spawn_agent`, `get_result`, `await_result`) allow orchestrating sub-agents from within a conversation.

Tools are extensible — implement the `Tool` base class (name, description, parameters, async execute), register in the factory, and add the name to `agents.yaml`. See `app/tools/base.py` for the interface.

## Token Usage Tracking

Every LLM API call is tracked with real provider-reported token counts and timing. Usage data is available in three ways:

**Real-time** — the CLI shows `thinking...` when the LLM is working and `thought: 1,234 tokens (2.3s)` when it finishes, interleaved with tool activity.

**Persisted** — each session writes a `{session_key}.usage.json` sidecar file with a full breakdown:

```json
{
  "session_key": "default",
  "started_at": 1711234567.89,
  "ended_at": 1711234600.00,
  "totals": { "prompt_tokens": 12500, "completion_tokens": 3200, "total_tokens": 15700, "duration_ms": 32450, "llm_calls": 8 },
  "by_category": {
    "agent_turn": { "prompt_tokens": 11000, "completion_tokens": 3000, "total_tokens": 14000, "count": 5, "duration_ms": 28000 },
    "consolidation": { "...": "..." },
    "context_retrieval": { "...": "..." }
  },
  "turns": [ { "iteration": 0, "total_tokens": 2800, "llm_duration_ms": 5600, "tool_duration_ms": 1200 } ]
}
```

**WebSocket** — the gateway streams `agent.activity` events per LLM/tool call and includes the full usage summary in the lifecycle `phase: "end"` payload.

Categories distinguish where tokens are spent: `agent_turn` (main LLM reasoning), `consolidation` (session memory compression), and `context_retrieval` (embeddings and queries triggered by tools).

## SmolRAG: The Memory Backend

SmolRAG is a lightweight retrieval-augmented generation system inspired by LightRAG. It combines vector similarity search with a structured knowledge graph to answer questions that require both semantic understanding and relational reasoning.

### Ingestion Pipeline

Documents are split into approximately 2,000-character overlapping chunks. Markdown code blocks are preserved in their entirety, and text is segmented at sentence boundaries. Each chunk is individually summarised with the full document as context, which raises the quality of both embeddings and retrieval.

Entity extraction runs in parallel with embedding. SmolRAG identifies entities and relationships from each chunk, stores them as nodes and edges in the knowledge graph, and tracks provenance so that when a document is updated or removed, its contributions to the graph are cleanly unwound.

### Query Modes

SmolRAG supports five query methods that balance speed, precision, and reasoning depth.

**Vector search** (`query`) embeds your question and finds the most similar chunks by cosine distance.

**Local KG query** (`local_kg_query`) extracts low-level keywords from your question and searches for matching entities in the graph.

**Global KG query** (`global_kg_query`) focuses on high-level keywords, matching them against relationships in the graph to find broad thematic connections.

**Hybrid KG query** (`hybrid_kg_query`) combines both local and global approaches.

**Mix query** (`mix_query`) merges vector search results with hybrid KG context. This is the default for `memory_search`.

### Storage

SmolRAG uses SQLite for excerpt content, vector indexes, document mappings, provenance tracking, BM25 state, and LLM caches. NetworkX persists the knowledge graph as GraphML.

## Project Structure

```
app/
  agent_loop.py        # Core agent iteration engine
  agent_factory.py     # Builds configured agent loops
  agent_config.py      # AgentConfig dataclass and YAML loader
  context_builder.py   # System prompt assembly
  smol_rag.py          # RAG backend (ingestion, extraction, 5 query modes)
  sqlite_store.py      # Async KV store backed by SQLite
  sqlite_mapping_store.py  # Relational many-to-many mapping store
  graph_store.py       # NetworkX graph with async locking
  session.py           # JSONL session persistence
  subagent.py          # SubagentManager for multi-agent orchestration
  lifecycle.py         # Memory lifecycle (promote, decay)
  lifecycle_hooks.py   # Decay and contradiction expiry hooks
  context_assembly.py  # Budget-aware context builder with taxonomy-weighted scoring
  taxonomy.py          # Memory type classification
  contradiction.py     # Contradiction detection between entities/relationships
  hooks.py             # Event hooks (session start/end, before/after turn)
  journal.py           # Session reflection journal generation
  session_export_hook.py # Auto-export sessions to memory on close
  session_indexer.py   # Index sessions into SmolRAG
  usage.py             # Token usage tracking, audit trail, persistence
  watcher.py           # File change detection and re-ingestion
  gateway.py           # WebSocket server
  tools/
    base.py            # Tool ABC (name, description, parameters, execute)
    registry.py        # Tool registry with filtering
    factory.py         # Mode-aware tool builder (direct/MCP)
    memory_tools.py    # memory_search, memory_graph_query, memory_store, memory_relate, memory_recall, contradiction_review
    filesystem.py      # read_file, write_file, edit_file, list_dir
    web.py             # web_search, web_fetch
    shell.py           # exec
    spawn.py           # spawn_agent, get_result, await_result
    mcp_tools.py       # MCP-delegating tool wrappers (gateway mode)
  reset.py             # Full store wipe (reset command)
cli/
  main.py              # Typer CLI (chat, ingest, watch, serve, recall, index-sessions, reset, clear-logs)
store/                 # All persistent data (gitignored)
  smolclaw.db          # SQLite (vectors, excerpts, mappings, caches, BM25)
  kg_db.graphml        # NetworkX knowledge graph
  sessions/            # JSONL session files
  memory/              # Journal and session markdown docs
  logs/                # Log files
  cache/               # Cache files
  input_docs/          # User source material (preserved by reset)
agents.yaml            # Named agent configurations
AGENT.md               # Shared bootstrap (loaded by all agents)
```

## Running Tests

```bash
python -m pytest
```

Tests use mock LLMs that return random embeddings, so they run without API keys. 504 tests, ~6 seconds.

## What's Here

- Agent loop with tool execution and LLM orchestration (OpenAI + Anthropic)
- Persistent memory: knowledge graph (NetworkX), vector search (SQLite), BM25 full-text
- Memory lifecycle: promote on access, decay on session end, contradiction detection
- Session management with LLM-summarised consolidation
- Multi-agent orchestration (spawn/await pattern)
- WebSocket gateway for remote clients with authentication
- Token usage tracking and audit trail across all LLM calls
- Extensible tool system with 14 tools across 6 categories
- CLI and gateway as dual interfaces
- Docker support

## What's Missing

- **Streaming responses** — gateway sends complete responses, not token-by-token
- **Cost controls** — tracks tokens but doesn't enforce budget limits or spend caps
- **External integrations** — no Slack, email, calendar, or webhook tools
- **Multi-user / multi-tenant** — single-user only, no auth beyond basic gateway token
- **Observability dashboard** — usage data is persisted as JSON but there's no UI to view it
- **Workflow orchestration** — no chains, DAGs, or conditional routing between agents
- **Deployment** — Dockerfile exists but no CI/CD, health checks, or managed deployment story
