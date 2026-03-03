# SmolClaw

SmolClaw is an agentic CLI with persistent, associative memory. It pairs a knowledge graph and vector retrieval backend (SmolRAG) with a tool-using agent loop that can search the web, read/write files, execute shell commands, and maintain long-term memory across sessions.

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

This deletes the SQLite database, vector and entity JSON files, the knowledge graph, and all files in `sessions/`, `memory/`, `logs/`, and `cache/`. After a reset, stores are recreated automatically the next time you run any command.

## Tools

Every agent draws from a shared tool registry. The available tools cover four categories.

**Memory** tools let agents search the knowledge graph with `memory_search` (hybrid vector and KG retrieval with optional memory type filtering), query specific entities and their relationships with `memory_graph_query`, store new memories with taxonomy classification via `memory_store`, and create explicit graph edges between entities with `memory_relate`.

**Filesystem** tools provide `read_file`, `write_file`, `edit_file`, and `list_dir` within a sandboxed workspace directory.

**Web** tools include `web_search` for internet queries and `web_fetch` for retrieving and reading web page content.

A shell execution tool (`exec`) is also available for running arbitrary commands.

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

SmolRAG uses SQLite for excerpt content, document mappings, provenance tracking, and LLM caches. NanoVectorDB handles embeddings, and NetworkX persists the knowledge graph as GraphML.

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
  lifecycle.py         # Memory lifecycle (promote, decay, consolidate)
  context_assembly.py  # Budget-aware context builder with scoring
  taxonomy.py          # Memory type classification
  hooks.py             # Event hooks (session, turn, compaction, file change)
  journal.py           # Session reflection journal generation
  watcher.py           # File change detection and re-ingestion
  gateway.py           # WebSocket server
  tools/
    memory_tools.py    # memory_search, memory_graph_query, memory_store, memory_relate
    filesystem.py      # read_file, write_file, edit_file, list_dir
    web.py             # web_search, web_fetch
    shell.py           # exec
    spawn.py           # spawn_agent, get_result, await_result
  reset.py             # Full store wipe (reset command)
cli/
  main.py              # Typer CLI (chat, ingest, watch, serve, recall, reset)
store/                 # All persistent data (gitignored)
  smolclaw.db          # SQLite (excerpts, mappings, caches, BM25)
  embeddings_db.json   # NanoVectorDB embeddings
  entities_db.json     # Entity data
  relationships_db.json # Relationship data
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

Tests use mock LLMs that return random embeddings, so they run without API keys.
