# SmolClaw Project Outline

Generated on 2026-06-22 from the local working tree in this repository.

## Scope

This outline covers the project files returned by `rg --files` from the repo
root. That is the source-controlled project surface: 156 files, about 31,687
lines at the time of inspection. It intentionally excludes `.git`, `.venv`,
runtime stores, caches, and generated `__pycache__` files.

The working tree is not pristine. This document describes the local state,
including the recent coding-harness changes (`smolcode`, command tools,
project instruction loading, and packaging metadata). Earlier verification for
that local state completed with `723 passed`.

## Purpose

SmolClaw is a memory-first agent runtime. It combines:

- a persistent RAG layer (`SmolRag`) with SQLite vector/KV/mapping stores,
  BM25, and a NetworkX knowledge graph;
- an agent loop that supports tool calls, streaming, session persistence,
  hooks, usage tracking, and context assembly from memory;
- multiple runtime surfaces: a Typer CLI, a `smolcode` coding harness entry
  point, and a WebSocket gateway;
- a dynamic tool system where capabilities define what can exist and agent
  configs define what is immediately visible.

## Architecture

### Entry Points

- `cli/main.py` owns the user-facing Typer commands: `chat`,
  `research-loop`, `ingest`, `watch`, `serve`, `recall`, `index-sessions`,
  `reset`, and `clear-logs`.
- `cli/main.py` also defines `code_entrypoint()`, exposed by `pyproject.toml`
  as `smolcode`, which starts the `coder` agent.
- `app/gateway.py` exposes a WebSocket chat interface and constructs agents
  through the same runtime path as the CLI, but with MCP-backed tools.
- `scripts/*.py` provide live gateway smoke, regression, and integration
  checks.

### Runtime Assembly

- `app/runtime_builder.py` builds `WorkspaceContext`, `SmolRag`,
  `SessionManager`, and `RuntimeEnvironment`.
- `app/runtime.py` resolves capabilities, builds the master registry,
  constructs context builders, and wires project instructions from:
  `~/.config/smolclaw/AGENTS.md`, workspace `AGENTS.md` or `CLAUDE.md`, and
  workspace `.smolclaw/instructions.md`.
- `app/agent_factory.py` builds agent loops, projects tool registries by
  capability/tool config, binds runtime context into tools, and creates child
  agents through `ChildAgentFactory`.
- `app/agent_loop.py` is the central LLM/tool loop. It builds prompts, streams
  output, executes tool calls, persists sessions, records usage, fires hooks,
  and performs memory consolidation.

### Workspace Model

`WorkspaceContext` is the local ownership boundary. Relative tool paths resolve
inside the workspace root. Mutable state lives under:

```text
workspace/
  stores/
    smolclaw.db
    kg_db.graphml
    sessions/
    logs/
    cache/
  memory/
  research/
```

`reset_workspace()` clears derived state while preserving `research/`.

### Memory And Retrieval

- `app/smol_rag.py` is the facade around ingestion, querying, store access, and
  contradiction detection.
- `app/ingestion.py` chunks documents, summarises excerpts, embeds them, stores
  BM25/vector rows, extracts graph entities/relationships, parses Obsidian
  links/tags, and tracks provenance.
- `app/query_engine.py` supports vector search, local/global/hybrid KG search,
  BM25 search, and mixed retrieval.
- `app/context_assembly.py` builds memory context with scoring by importance,
  confidence, recency, memory type, and tier.
- `app/document_manager.py` removes documents and prunes associated vector,
  BM25, graph, and provenance data.
- `app/contradiction.py`, `app/lifecycle.py`, and `app/taxonomy.py` add belief
  revision, memory promotion, expiry, and memory type classification.

### Stores

- `app/vector_store.py` stores normalized vectors in SQLite and keeps an
  in-memory matrix for fast cosine queries.
- `app/sqlite_store.py` provides async JSON KV storage.
- `app/sqlite_mapping_store.py` provides many-to-many mapping tables.
- `app/bm25_store.py` provides durable BM25 indexing with an in-memory scoring
  structure.
- `app/graph_store.py` wraps NetworkX graph persistence and async write locks.
- `app/store_bundle.py` groups all stores for the RAG pipeline.

### LLM Layer

- `app/openai_llm.py` implements completions, tool completions, streaming,
  structured output, embedding calls, caching, and usage recording.
- `app/anthropic_llm.py` implements Anthropic completions/tool calls and
  schema-prompt structured output. It does not provide embeddings.
- `app/llm.py` chooses providers and can compose Anthropic completion with an
  OpenAI embedding provider.
- `app/schemas.py` contains Pydantic schemas used for structured outputs.
- `app/prompts.py` contains ingestion, query, classification, contradiction,
  consolidation, and journal prompts.

### Tool System

- `app/tools/base.py` defines tool descriptors, call policy, runtime context,
  and normalized results.
- `app/tools/registry.py` registers tools, applies middleware, exposes deferred
  tools, and projects a registry per agent.
- `app/tools/factory.py` maps capabilities to direct or MCP providers.
- `app/tools/permissions.py` enforces permission modes (`full`, `plan`,
  `execute`, `research`, `delegate_only`).
- `app/tools/middleware.py` provides logging, retry, timeout, cache, hook, and
  tracing middleware.
- Filesystem tools include `read_file`, `write_file`, `edit_file`, `list_dir`,
  `find_files`, `grep_search`, and `apply_patch`.
- Command tools include `git_status`, `git_diff`, and constrained
  `run_command`.
- Memory, web, MCP, orchestration, subagent, and deferred tool search providers
  live under `app/tools/`.

Direct local shell execution through the `shell` capability is intentionally
disabled in the direct runtime until a real sandbox backend exists. The newer
`command` capability is narrower and allowlisted.

### Sessions, Hooks, And Observability

- `app/session.py` persists sessions as JSONL plus usage sidecars.
- `app/session_export_hook.py`, `app/session_indexer.py`, and `app/journal.py`
  export sessions into memory as episode and journal records.
- `app/hooks.py` is the lifecycle hook runner.
- `app/usage.py` tracks token and duration usage by turn/category.
- `app/tracing.py` provides optional OpenTelemetry spans.
- `app/logger.py` manages rotating file logs and log cleanup.

### Multi-Agent Support

- Agent definitions live in `agents.yaml` with bootstrap markdown in
  `agents/`.
- `app/orchestration.py` implements sequential, fanout, and route patterns.
- `app/subagent.py` manages spawned background subagents.
- `app/tools/orchestration_tools.py` and `app/tools/spawn.py` expose these
  flows as tools.

## File Inventory

### Root And Product Notes

- `AGENT.md` - shared agent bootstrap.
- `Dockerfile` - container image definition.
- `LICENSE` - project license.
- `README.md` - main user documentation.
- `about.txt` - short project/about note.
- `agentic-framework-research.md` - research note.
- `agentscope-vs-smolclaw.md` - comparative research note.
- `architecture.excalidraw` - architecture diagram source.
- `diagram.md` - older class-oriented sketch.
- `docker-compose.yml` - local container composition.
- `pyproject.toml` - packaging and console script metadata.
- `pytest.ini` - pytest configuration.
- `requirements.txt` - pinned dependency list.
- `smolclaw-spec.md` - broader product/spec draft.

### Agent And Skill Config

- `agents.yaml` - agent configs, tools, capabilities, permission modes.
- `agents/coder.md` - coding agent bootstrap.
- `agents/orchestrator.md` - orchestration agent bootstrap.
- `agents/researcher.md` - research agent bootstrap.
- `agents/smolclaw.md` - default agent bootstrap.
- `skills/memory-hygiene.md` - memory storage guidance.

### Application Package

- `app/__init__.py`
- `app/agent_config.py`
- `app/agent_factory.py`
- `app/agent_loop.py`
- `app/anthropic_llm.py`
- `app/behaviors.py`
- `app/bm25_store.py`
- `app/chunking.py`
- `app/context_assembly.py`
- `app/context_builder.py`
- `app/contradiction.py`
- `app/definitions.py`
- `app/document_manager.py`
- `app/gateway.py`
- `app/graph_store.py`
- `app/hooks.py`
- `app/ingestion.py`
- `app/journal.py`
- `app/lifecycle.py`
- `app/lifecycle_hooks.py`
- `app/llm.py`
- `app/logger.py`
- `app/mcp_client.py`
- `app/obsidian.py`
- `app/openai_llm.py`
- `app/orchestration.py`
- `app/prompts.py`
- `app/query_engine.py`
- `app/reset.py`
- `app/runtime.py`
- `app/runtime_builder.py`
- `app/runtime_capabilities.py`
- `app/schemas.py`
- `app/session.py`
- `app/session_export_hook.py`
- `app/session_indexer.py`
- `app/smol_rag.py`
- `app/sqlite_mapping_store.py`
- `app/sqlite_store.py`
- `app/store_bundle.py`
- `app/subagent.py`
- `app/taxonomy.py`
- `app/tracing.py`
- `app/usage.py`
- `app/utilities.py`
- `app/vector_store.py`
- `app/watcher.py`
- `app/workspace.py`

### Tools Package

- `app/tools/__init__.py`
- `app/tools/base.py`
- `app/tools/command.py`
- `app/tools/factory.py`
- `app/tools/filesystem.py`
- `app/tools/mcp_tools.py`
- `app/tools/memory_tools.py`
- `app/tools/middleware.py`
- `app/tools/orchestration_tools.py`
- `app/tools/permissions.py`
- `app/tools/registry.py`
- `app/tools/shell.py`
- `app/tools/spawn.py`
- `app/tools/tool_search.py`
- `app/tools/web.py`

### CLI And Docs

- `cli/__init__.py`
- `cli/main.py`
- `docs/architecture-runtime.md`
- `docs/workspaces.md`

### Scripts

- `scripts/integration_test.py`
- `scripts/regression_test.py`
- `scripts/smoke_test.py`
- `scripts/test_all.sh`
- `scripts/ws_helpers.py`

### Tests

- `tests/README.md`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_agent_config.py`
- `tests/test_agent_factory.py`
- `tests/test_agent_loop.py`
- `tests/test_agent_loop_gateway_flow.py`
- `tests/test_anthropic_llm.py`
- `tests/test_bm25_store.py`
- `tests/test_bugfix_regressions.py`
- `tests/test_chunking.py`
- `tests/test_cli_logs.py`
- `tests/test_cli_multiagent.py`
- `tests/test_cli_research_loop.py`
- `tests/test_context_assembly.py`
- `tests/test_context_builder.py`
- `tests/test_contradiction.py`
- `tests/test_contradiction_integration.py`
- `tests/test_contradiction_resolution.py`
- `tests/test_gateway.py`
- `tests/test_graph_concurrency.py`
- `tests/test_graph_store.py`
- `tests/test_hooks.py`
- `tests/test_ingest_text.py`
- `tests/test_journal.py`
- `tests/test_keep_existing_regressions.py`
- `tests/test_lifecycle.py`
- `tests/test_llm_factory.py`
- `tests/test_logger.py`
- `tests/test_mcp_client.py`
- `tests/test_mcp_tools.py`
- `tests/test_obsidian.py`
- `tests/test_orchestration.py`
- `tests/test_orchestration_tools.py`
- `tests/test_permissions.py`
- `tests/test_project_instructions.py`
- `tests/test_reset.py`
- `tests/test_runtime.py`
- `tests/test_schemas.py`
- `tests/test_session.py`
- `tests/test_session_export_hook.py`
- `tests/test_session_indexer.py`
- `tests/test_smol_rag.py`
- `tests/test_sqlite_mapping_store.py`
- `tests/test_sqlite_store.py`
- `tests/test_structured_output.py`
- `tests/test_subagent.py`
- `tests/test_taxonomy.py`
- `tests/test_tool_completion.py`
- `tests/test_tool_middleware.py`
- `tests/test_tool_registry.py`
- `tests/test_tool_search.py`
- `tests/test_tools_command.py`
- `tests/test_tools_filesystem.py`
- `tests/test_tools_memory.py`
- `tests/test_tools_shell.py`
- `tests/test_tools_web.py`
- `tests/test_tracing.py`
- `tests/test_usage.py`
- `tests/test_utilities.py`
- `tests/test_utilities_new.py`
- `tests/test_vector_store.py`
- `tests/test_watcher.py`
- `tests/test_workspace_paths.py`

## Issues And Concerns

1. The working tree is dirty. The outline reflects local changes that are not
   committed or pushed.
2. `pyproject.toml` lists `smolclaw` in `[tool.setuptools].packages`, but no
   `smolclaw/` package exists in the project file list. Normal package builds
   are likely to fail until this is corrected.
3. README documents the general CLI well, but it does not yet document
   `smolcode` as the primary coding harness entrypoint.
4. `AGENT.md` is stale relative to the current tool surface. It mentions older
   file tools and does not describe `find_files`, `grep_search`, `apply_patch`,
   `git_status`, `git_diff`, or `run_command`.
5. `tests/README.md` is stale in places. It references removed filenames,
   `NanoVectorStore`, older project paths, and says some behaviours are not
   implemented even though the codebase has moved on.
6. Direct local shell remains disabled by design. The `command` capability is
   useful but intentionally much narrower than a general shell, so the harness
   cannot yet run arbitrary project setup or mutation commands through the
   agent.
7. `run_command` is allowlisted and denies tokens such as `add`, `checkout`,
   `install`, `reset`, and `restore`. That is safer, but it will block many
   real coding workflows unless an approval/sandbox model is added.
8. `WorkspaceContext` correctly defaults to the current directory for fresh CLI
   invocations, but the default workspace root is computed at import time in
   `app/definitions.py`. Long-lived processes should pass workspace roots
   explicitly if they change directories.
9. Project instruction loading is wired through `app/runtime.py`'s context
   builder factory. Direct lower-level calls to `build_agent_loop()` without a
   supplied context builder do not receive those instruction paths.
10. Anthropic-only setups cannot run embedding-backed memory operations.
    `CompositeLlm` with an OpenAI embedding provider is required for those
    paths.
11. `extract_json_from_text()` uses a greedy JSON-object regex. It is simple
    and tested, but brittle when LLM output contains multiple JSON-like blocks.
12. Several ingestion and lifecycle paths intentionally swallow/log failures
    for resilience: frontmatter parse failures, journal/session export
    failures, memory promotion failures, and hook failures. That keeps the
    agent running but can hide degraded memory quality unless logs are checked.
13. Store table names and columns are interpolated into SQL. Current inputs are
    internal constants; keep them that way.
14. Local generated directories exist under source/test paths:
    `app/__pycache__`, `app/tools/__pycache__`, `cli/__pycache__`,
    `tests/__pycache__`, and `tests/v2/__pycache__`. They are ignored but add
    local clutter.
15. `architecture.excalidraw`, `diagram.md`, `smolclaw-spec.md`, and research
    notes appear partly historical. `docs/architecture-runtime.md` is the
    maintained runtime source of truth.

## Useful Next Fixes

1. Fix package metadata so editable/global installs work without manual
   launchers.
2. Add README coverage for `smolcode` and its current workspace behavior.
3. Refresh `AGENT.md` and `tests/README.md`.
4. Decide whether the coding harness needs an approval-backed command executor
   beyond the current read/test allowlist.
5. Add a short architecture note explaining the difference between the disabled
   `shell` capability and the constrained `command` capability.
