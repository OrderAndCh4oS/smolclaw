# SmolClaw

SmolClaw is an agentic CLI with persistent, associative memory. It pairs a knowledge graph and vector retrieval backend (SmolRAG) with a multi-agent orchestration layer that can research, plan, write, and critique content autonomously.

The system was built to power Salable's marketing content pipeline, but the architecture is general-purpose. You can use it as an interactive chat assistant with long-term memory, run named agents for specialised tasks, or let the autopilot produce entire articles end-to-end without intervention.

## How It Works

SmolClaw has two layers. The bottom layer, SmolRAG, handles ingestion, embedding, entity extraction, and retrieval. The top layer provides an agent loop with tool use, session persistence, and multi-agent orchestration.

When you ingest a document, SmolRAG splits it into overlapping chunks that keep Markdown code blocks intact, summarises each chunk for context quality, embeds everything into a vector store, and extracts entities and relationships into a NetworkX knowledge graph. Obsidian wiki links and tags are parsed during ingestion and added as graph nodes, so your vault's structure becomes queryable.

When you ask a question, SmolClaw combines semantic vector search with knowledge graph traversal to build rich context for the LLM. Five query modes give you control over the retrieval strategy, from pure vector similarity to full hybrid search that merges both approaches.

Change detection is automatic. Every document is content-hashed on ingest. If a file's hash changes, the old embeddings and graph entries are cleaned up and the new content is reingested, so answers always reflect the latest state of your source material.

## Getting Started

SmolClaw requires Python 3.11 (3.14 has compatibility issues with pydantic-core and tiktoken). Set up with pyenv or your preferred version manager, then install dependencies into a virtual environment:

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

SmolClaw's CLI has three commands: `chat` for interactive sessions, `ingest` for loading documents into memory, and `autopilot` for autonomous content production.

### Interactive Chat

Start a conversation with the default SmolClaw agent. It has access to all tools and reads `AGENT.md` as its bootstrap context:

```bash
python -m cli.main chat
```

You can switch sessions, models, or run a named agent from `agents.yaml`:

```bash
python -m cli.main chat --session my-project --model gpt-4o
python -m cli.main chat --agent researcher
python -m cli.main chat --agent operator
```

Named agents receive both the shared `AGENT.md` bootstrap (so they all know about Salable's docs and memory classification) and their own agent-specific bootstrap from the `agents/` directory.

### Document Ingestion

Ingest a single file or an entire directory into the knowledge graph and vector store:

```bash
python -m cli.main ingest vault/docs/
python -m cli.main ingest path/to/specific-file.md
```

Unchanged files are skipped automatically thanks to content hashing.

### Autopilot

Run the autonomous content pipeline. This cycles through the article queue, spawning the researcher, planner, writer, and critic agents in sequence:

```bash
python -m cli.main autopilot
python -m cli.main autopilot --pause 60 --ideator-interval 3
```

The ideator agent runs periodically between articles to generate fresh ideas by mining the knowledge graph for connections and gaps in the content plan.

## Agent Pipeline

SmolClaw's content pipeline is a chain of specialised agents, each with its own model, persona, tool set, and bootstrap instructions. The six agents are defined in `agents.yaml`:

**Researcher** gathers authoritative sources on a topic, reads them fully, and stores structured findings in memory with source URLs, authors, dates, and key arguments. It rejects low-quality SEO content and prioritises industry research, academic papers, and primary documentation.

**Planner** reads the article template, pulls research from memory, and produces a structured outline that follows every field in the template exactly. Outlines are saved to the content outlines directory for the writer to pick up.

**Writer** reads the style guide before writing a single word, then works from the planner's outline and the researcher's stored findings to produce a 1,200 to 2,500 word article. It follows the prose-first philosophy, story spine structure, and Chicago Manual formatting.

**Critic** detects AI-generated content markers and style guide violations. It quotes exact text, explains why it reads as AI-generated, and provides specific rewrites. The critic checks for banned vocabulary, structural patterns like rule-of-three abuse, and the "it's not X, it's Y" construction that is the strongest AI signal.

**Ideator** runs alongside the other agents, exploring the knowledge graph for adjacent topics, cross-pillar intersections, and gaps between beginner and advanced content. It generates raw article ideas with enough shape for the planner to develop.

**Operator** orchestrates the full pipeline. When you ask it to produce an article, it spawns the researcher, waits for results, spawns the planner, waits again, then spawns the writer, without asking for permission between steps.

## Tools

Every agent draws from a shared tool registry, filtered to just the tools it needs. The available tools cover four categories.

**Memory** tools let agents search the knowledge graph with `memory_search` (hybrid vector and KG retrieval with optional memory type filtering), query specific entities and their relationships with `memory_graph_query`, store new memories with taxonomy classification via `memory_store`, and create explicit graph edges between entities with `memory_relate`.

**Filesystem** tools provide `read_file`, `write_file`, `edit_file`, and `list_dir` within a sandboxed workspace directory.

**Web** tools include `web_search` for internet queries and `web_fetch` for retrieving and reading web page content.

**Orchestration** tools let agents spawn subagents (`spawn_agent`), check on them (`get_result`), or block until they finish (`await_result`). A `SubagentManager` handles concurrency limits and session isolation.

A shell execution tool (`exec`) is also available for agents that need to run arbitrary commands.

## SmolRAG: The Memory Backend

SmolRAG is a lightweight retrieval-augmented generation system inspired by LightRAG. It combines vector similarity search with a structured knowledge graph to answer questions that require both semantic understanding and relational reasoning.

### Ingestion Pipeline

Documents are split into approximately 2,000-character overlapping chunks using a function optimised for code documentation. Markdown code blocks are preserved in their entirety, and text is segmented at sentence boundaries so words never split mid-chunk. Each chunk is individually summarised with the full document as context, which raises the quality of both embeddings and retrieval.

Entity extraction runs in parallel with embedding. SmolRAG identifies entities and relationships from each chunk, stores them as nodes and edges in the knowledge graph, and tracks provenance so that when a document is updated or removed, its contributions to the graph are cleanly unwound.

### Query Modes

SmolRAG supports five query methods that balance speed, precision, and reasoning depth.

**Vector search** (`query`) embeds your question and finds the most similar chunks by cosine distance. This is the fastest option and works well when the answer lives directly in document text.

**Local KG query** (`local_kg_query`) extracts low-level keywords from your question, searches for matching entities in the graph, and assembles context from their descriptions, relationships, and associated text chunks. Use this when you care about fine-grained entity-level information.

**Global KG query** (`global_kg_query`) focuses on high-level keywords, matching them against relationships in the graph to find broad thematic connections. This gives you a bird's-eye view of how topics interrelate.

**Hybrid KG query** (`hybrid_kg_query`) combines both local and global approaches, selecting top entities and relationships from each and presenting them together. Use this when your question blends specific terms with general concepts.

**Mix query** (`mix_query`) is the most comprehensive mode. It merges vector search results with hybrid KG context, giving the LLM both literal text excerpts and structured knowledge graph data. This is the default for `memory_search` and produces the richest answers. You can optionally filter results by memory type (fact, decision, preference, episode, task, journal, or reference) to narrow retrieval.

### Storage

SmolRAG uses NanoVectorDB for embeddings, NetworkX for the knowledge graph (persisted as GraphML), and JSON key-value stores for excerpt content, document mappings, and provenance tracking. Everything is file-based with no external database dependencies.

## Project Structure

```
app/
  agent_loop.py        # Core agent iteration engine
  agent_factory.py     # Builds configured agent loops
  agent_config.py      # AgentConfig dataclass and YAML loader
  context_builder.py   # System prompt assembly (shared + agent bootstrap)
  smol_rag.py          # RAG backend (ingestion, extraction, 5 query modes)
  graph_store.py       # NetworkX graph with async locking
  session.py           # JSONL session persistence
  subagent.py          # SubagentManager for multi-agent orchestration
  obsidian.py          # Wiki link, tag, and frontmatter parsing
  tools/
    memory_tools.py    # memory_search, memory_graph_query, memory_store, memory_relate
    filesystem.py      # read_file, write_file, edit_file, list_dir
    web.py             # web_search, web_fetch
    shell.py           # exec
    spawn.py           # spawn_agent, get_result, await_result
cli/
  main.py              # Typer CLI (chat, ingest, autopilot commands)
agents/
  write-marketing-content.md  # Style guide
  article-template.md         # Article outline template
  content-strategy.md         # Content pillars, personas, cadence
  critic.md                   # AI marker detection rules
  writer.md, researcher.md, planner.md, ideator.md  # Agent bootstraps
agents.yaml            # Named agent configurations
AGENT.md               # Shared bootstrap (loaded by all agents)
```

## Running Tests

The test suite covers the RAG backend, agent loop, tools, context builder, sessions, and more:

```bash
.venv/bin/python -m pytest
```

Tests use mock LLMs that return random embeddings, so they run without API keys and complete in under 20 seconds.
