# SmolClaw

SmolClaw is a memory-first agent with persistent, associative memory. It pairs a knowledge graph and vector retrieval backend (SmolRAG) with a tool-using agent loop that can search the web, read and write workspace files, and maintain long-term memory across sessions. Both a CLI and a WebSocket gateway are available as interfaces.

For the maintained runtime architecture view, see [docs/architecture-runtime.md](docs/architecture-runtime.md). For the user-facing workspace model, see [docs/workspaces.md](docs/workspaces.md).

## Installation

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

## Quick Start

Use one workspace per topic, client, or project. A workspace keeps research material, exported memory, sessions, logs, and indexes isolated from every other run.

```bash
export WS=~/smolclaw-workspaces/acme-research
mkdir -p "$WS"/research
cp ~/notes/acme-brief.md "$WS"/research/

python -m cli.main ingest "$WS"/research --workspace "$WS"
python -m cli.main chat --workspace "$WS" --session acme
python -m cli.main recall "acme" --workspace "$WS"
```

That gives you:

- `research/` for source material you want to ingest and preserve
- `memory/` for exported memory and session documents
- `stores/` for derived runtime state such as the SQLite DB, graph, sessions, logs, and caches

If you want continuous re-ingestion while you add files to `research/`, run:

```bash
python -m cli.main watch --workspace "$WS"
```

If you want the built-in recurring research loop, run:

```bash
python -m cli.main research-loop "Track Acme competitors and notable product changes." --workspace "$WS"
```

The loop keeps reusing the same workspace memory and session until you stop it with `Ctrl+C` or `Esc`.

## What Is a Workspace?

Every CLI and gateway command accepts `--workspace`. That directory becomes the root for local state and file access.

```text
your-workspace/
  stores/
    smolclaw.db
    kg_db.graphml
    sessions/
    logs/
    cache/
  memory/
  research/
```

- `stores/` is derived runtime state. It can be rebuilt.
- `memory/` stores exported markdown memories and indexed session docs.
- `research/` is your source material and is preserved by `reset`.

Recommended usage: create one workspace per research stream, codebase, customer, or internal project. That keeps recall, memory promotion, logs, and sessions from bleeding across unrelated work.

See [docs/workspaces.md](docs/workspaces.md) for the full workspace guide.

## CLI Usage

SmolClaw's CLI exposes nine commands: `chat`, `research-loop`, `ingest`, `watch`, `serve`, `recall`, `index-sessions`, `reset`, and `clear-logs`.

All of them accept `--workspace` and operate on that workspace's isolated state.

### Interactive Chat

Start a conversation with the default SmolClaw agent. It has access to all tools and reads `AGENT.md` as its bootstrap context:

```bash
python -m cli.main chat --workspace "$WS"
```

You can switch sessions, models, or run a named agent from `agents.yaml`:

```bash
python -m cli.main chat --workspace "$WS" --session my-project --model gpt-4o
python -m cli.main chat --workspace "$WS" --agent researcher
```

### Document Ingestion

Ingest a single file or an entire directory into the knowledge graph and vector store. The usual pattern is to keep source material in `research/`.

```bash
python -m cli.main ingest "$WS"/research --workspace "$WS"
python -m cli.main ingest "$WS"/research/acme-brief.md --workspace "$WS"
```

Unchanged files are skipped automatically thanks to content hashing.

### Watch Mode

Watch a workspace directory for changes and re-ingest automatically. With no `--path`, SmolClaw watches `<workspace>/research`.

```bash
python -m cli.main watch --workspace "$WS"
python -m cli.main watch --workspace "$WS" --path "$WS"/research
```

### Automated Research Loop

Run a recurring research cycle against one workspace and one agent. The default agent is `researcher`.

```bash
python -m cli.main research-loop "Track Acme competitors and notable product changes." --workspace "$WS"
python -m cli.main research-loop "Track Acme competitors and notable product changes." --workspace "$WS" --interval 900 --max-runs 4
```

The loop reuses the same session and memory between cycles. Stop it with `Ctrl+C` or `Esc`.

### WebSocket Server

Start the WebSocket gateway for programmatic access against a specific workspace:

```bash
python -m cli.main serve --workspace "$WS"
```

### Reset

Wipe all derived persistent data for a full reset. `research/` is preserved.

```bash
python -m cli.main reset --workspace "$WS"
```

You'll be prompted for confirmation. Pass `--force` to skip it (useful for scripts):

```bash
python -m cli.main reset --workspace "$WS" --force
```

This deletes the SQLite database, the knowledge graph, and all files in `stores/sessions/`, `memory/`, `stores/logs/`, and `stores/cache/`. The workspace `research/` directory is preserved. After a reset, stores are recreated automatically the next time you run any command.

### Session Recall

Search past sessions by topic or time range:

```bash
python -m cli.main recall "what did we discuss about auth?" --workspace "$WS"
python -m cli.main recall "last week" --mode temporal --days 7 --workspace "$WS"
```

### Session Indexing

Index all past sessions into SmolRAG for retrieval:

```bash
python -m cli.main index-sessions --workspace "$WS"
```

### Clear Logs

Delete log files without touching data stores:

```bash
python -m cli.main clear-logs --workspace "$WS"
```

## How It Works

SmolClaw has two layers. The bottom layer, SmolRAG, handles ingestion, embedding, entity extraction, and retrieval. The top layer provides an agent loop with tool use, session persistence, and multi-agent orchestration.

When you ingest a document, SmolRAG splits it into overlapping chunks that keep Markdown code blocks intact, summarises each chunk for context quality, embeds everything into a vector store, and extracts entities and relationships into a NetworkX knowledge graph.

When you ask a question, SmolClaw combines semantic vector search with knowledge graph traversal to build rich context for the LLM. Five query modes give you control over the retrieval strategy, from pure vector similarity to full hybrid search that merges both approaches.

Change detection is automatic. Every document is content-hashed on ingest. If a file's hash changes, the old embeddings and graph entries are cleaned up and the new content is reingested, so answers always reflect the latest state of your source material.

## Tools

Every agent draws from a shared tool registry. The available tools cover several categories.

**Memory** tools let agents search the knowledge graph with `memory_search` (hybrid vector + KG retrieval with optional memory type filtering), query specific entities and their relationships with `memory_graph_query`, store new memories with taxonomy classification via `memory_store`, create explicit graph edges between entities with `memory_relate`, retrieve past sessions with `memory_recall`, fetch a specific excerpt with `memory_get`, and review contradictions with `contradiction_review`.

**Filesystem** tools provide `read_file`, `write_file`, `edit_file`, and `list_dir` within the active workspace root.

**Web** tools include `web_search` for internet queries and `web_fetch` for retrieving and reading web page content.

**Shell** execution is transport-dependent. Direct local shell execution is currently disabled until a real sandbox backend exists; MCP-backed runtimes may still expose `exec` through the remote provider.

**Multi-agent** tools (`spawn_agent`, `get_result`, `await_result`) allow orchestrating sub-agents from within a conversation.

**Orchestration** tools provide higher-level patterns: `sequential_pipeline` chains agents so the output of one becomes the input of the next, `fanout_pipeline` runs agents in parallel on the same input, and `route` directs input to the best-matching agent via pattern matching or LLM classification.

Tools are extensible at two levels. For a single capability, implement the `Tool` base class and declare its per-call policy (`mutates_state`, `delegates`) plus optional deferred exposure. For a reusable bundle, add a capability provider to the shared registry factory so the capability can be enabled, replaced, or omitted cleanly by runtime transport. `capabilities` define the supply boundary for an agent, while `tools` define which immediate tools are exposed at startup. Deferred tools from enabled capabilities stay discoverable at runtime, and `tool_search` is exposed automatically when an agent has hidden deferred tools to discover. Agent configs can also opt into higher-level loop behavior with `behaviors` in `agents.yaml` (`plan`, `reflect`) without hardcoding those prompts into the loop itself.

### Tool Middleware

All tool executions pass through a composable middleware chain. Middleware wraps `tool.execute()` in an onion model — each layer can inspect/modify arguments, short-circuit, retry, or add instrumentation.

Built-in middleware:

- **LoggingMiddleware** — logs tool name, args summary, duration, and success/failure (registered by default)
- **RetryMiddleware** — retries when the result starts with `"Error:"` (configurable max retries and prefixes)
- **TimeoutMiddleware** — wraps execution in `asyncio.wait_for()` with a configurable timeout
- **CacheMiddleware** — in-memory cache with TTL, keyed on tool name + arguments
- **TracingMiddleware** — creates OpenTelemetry spans for tool execution (see Observability below)

Register middleware globally or per-tool:

```python
from app.tools.middleware import RetryMiddleware, CacheMiddleware

registry.use(RetryMiddleware(max_retries=2))           # all tools
registry.use_for("web_search", CacheMiddleware(ttl_seconds=600))  # specific tool
```

Filtered registries (via `filter_by_names`) inherit middleware from their parent.

## Structured Output

SmolClaw uses Pydantic models to enforce structured responses from LLMs where reliable parsing matters. Both LLM providers support `get_structured_completion()`:

- **OpenAI** — uses native structured output via `response_format` (the model is constrained to match the schema)
- **Anthropic** — injects the JSON schema into the system prompt and validates the response with Pydantic

Structured output is used for memory classification, contradiction adjudication, and keyword extraction. All call sites include a text-parsing fallback so the system degrades gracefully if structured output fails.

Schemas are defined in `app/schemas.py`: `MemoryClassification`, `ContradictionVerdict`, `HighLowKeywords`, `EntityExtractionResult`, and `RouteDecision`.

## Observability

SmolClaw has opt-in OpenTelemetry tracing. When OTEL packages are installed and an exporter endpoint is configured, spans are created for:

| Span | Attributes |
|------|-----------|
| `llm.completion` / `llm.tool_completion` | model, prompt_tokens, completion_tokens, total_tokens, duration_ms |
| `tool.{name}` | tool.name, tool.arguments, tool.success, tool.duration_ms |
| `context.retrieval` | retrieval.included_count, retrieval.excluded_count, retrieval.tokens_used |

### Jaeger Setup (Quickstart)

```bash
# Start Jaeger
docker run -d --name jaeger -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one:latest

# Add to .env
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

# Run SmolClaw — traces are exported automatically
python -m cli.main chat
```

Open http://localhost:16686 to view traces. Search for service `smolclaw`.

### How It Works

Tracing is initialized on startup in both the CLI (`cli/main.py`) and gateway (`app/gateway.py`). The `app/tracing.py` module provides:

- `init_tracing()` — configures the OTEL SDK with an OTLP HTTP exporter. Reads `OTEL_EXPORTER_OTLP_ENDPOINT` from the environment.
- `get_tracer()` — returns the real tracer or a zero-cost `NoOpTracer` if OTEL is not installed.
- `trace_llm_call()`, `trace_agent_turn()`, `trace_retrieval()` — context managers for common span types.
- `TracingMiddleware` — tool middleware that creates spans (registered via the tool factory).

If the `opentelemetry-*` packages are not installed, all tracing is a no-op with zero overhead. No conditionals are scattered across the codebase — the no-op tracer handles it.

### Other Exporters

Any OTLP-compatible backend works. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to your collector:

- **Grafana Tempo** — `http://tempo:4318`
- **Arize Phoenix** — `pip install arize-phoenix && phoenix serve` → `http://localhost:6006`
- **Langfuse** — configure via their OTLP integration docs

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
  schemas.py           # Pydantic models for structured LLM responses
  tracing.py           # OpenTelemetry tracing (opt-in, no-op fallback)
  orchestration.py     # Pipeline and routing patterns (sequential, fanout, route)
  tools/
    base.py            # Tool ABC (name, description, parameters, execute)
    registry.py        # Tool registry with filtering and middleware
    factory.py         # Mode-aware tool builder (direct/MCP)
    middleware.py       # Composable tool middleware (logging, retry, timeout, cache, tracing)
    memory_tools.py    # memory_search, memory_graph_query, memory_store, memory_relate, memory_recall, contradiction_review
    filesystem.py      # read_file, write_file, edit_file, list_dir
    web.py             # web_search, web_fetch
    shell.py           # exec
    spawn.py           # spawn_agent, get_result, await_result
    orchestration_tools.py  # sequential_pipeline, fanout_pipeline, route
    mcp_tools.py       # MCP-delegating tool wrappers (gateway mode)
  reset.py             # Full store wipe (reset command)
cli/
  main.py              # Typer CLI (chat, ingest, watch, serve, recall, index-sessions, reset, clear-logs)
docs/
  architecture-runtime.md  # Maintained runtime architecture and flow diagrams
  workspaces.md            # Workspace model, layout, and usage guide
stores/                # Derived persistent runtime data (gitignored)
  smolclaw.db          # SQLite (vectors, excerpts, mappings, caches, BM25)
  kg_db.graphml        # NetworkX knowledge graph
  sessions/            # JSONL session files
  logs/                # Log files
  cache/               # Cache files
memory/                # Exported memory/session markdown docs
research/              # User source material (preserved by reset)
agents.yaml            # Named agent configurations
AGENT.md               # Shared bootstrap (loaded by all agents)
```

## Running Tests

```bash
python -m pytest
```

Tests use mock LLMs that return random embeddings, so they run without API keys. Current suite: ~700 tests, ~6-8 seconds.

## What's Here

- Agent loop with tool execution and LLM orchestration (OpenAI + Anthropic)
- Persistent memory: knowledge graph (NetworkX), vector search (SQLite), BM25 full-text
- Memory lifecycle: promote on access, decay on session end, contradiction detection
- Session management with LLM-summarised consolidation
- Multi-agent orchestration: spawn/await, sequential pipeline, fanout, routing
- Structured output via Pydantic models (OpenAI native + Anthropic prompt-based)
- Composable tool middleware: logging, retry, timeout, cache, tracing
- OpenTelemetry tracing: opt-in spans on LLM calls, tools, and retrieval (Jaeger, Grafana, etc.)
- WebSocket gateway for remote clients with authentication
- Token usage tracking and audit trail across all LLM calls
- Extensible tool system with 17 tools across 7 categories
- CLI and gateway as dual interfaces
- Docker support

## How SmolClaw Compares to NanoClaw

[NanoClaw](https://github.com/qwibitai/nanoclaw) is a lightweight alternative to OpenClaw built on Anthropic's Agents SDK. Both projects aim to be small, ownable agent systems, but they make different bets.

**SmolClaw is a knowledge system.** Its core investment is in memory — a knowledge graph, vector search, and BM25 full-text retrieval working together with taxonomy-weighted scoring, promote/decay lifecycle, and contradiction detection. It has five query modes and budget-aware context assembly. It tracks every token spent and where.

**NanoClaw is an integration hub.** Its core investment is in connectivity — WhatsApp, Telegram, Slack, Discord, and Gmail out of the box, with scheduled cron jobs and container-level security isolation per group. Memory is filesystem-based (`CLAUDE.md` per group), with semantic RAG being added.

| | SmolClaw | NanoClaw |
|---|---|---|
| Memory depth | KG + vector + BM25 hybrid, 5 query modes, lifecycle | CLAUDE.md files, basic RAG (in progress) |
| Messaging channels | CLI + WebSocket | WhatsApp, Telegram, Slack, Discord, Gmail |
| Scheduled jobs | Not yet | Built-in cron with memory context |
| Security model | Path-sandboxed tools | Linux container isolation per group |
| Multi-user | Single-user | Multi-group with isolated filesystems |
| Token tracking | Full audit trail, per-category breakdown | Not a focus |
| LLM support | OpenAI + Anthropic (direct clients) | Anthropic Agents SDK |
| Language | Python | Node.js |

The gaps listed below map closely to NanoClaw's strengths.

## What's Missing

- **Streaming responses** — gateway sends complete responses, not token-by-token
- **Cost controls** — tracks tokens but doesn't enforce budget limits or spend caps
- **External integrations** — no Slack, email, calendar, or webhook tools
- **Multi-user / multi-tenant** — single-user only, no auth beyond basic gateway token
- **Observability dashboard** — OTEL traces go to Jaeger/Grafana, but no built-in UI for browsing memory state or sessions
- **Deployment** — Dockerfile exists but no CI/CD, health checks, or managed deployment story
