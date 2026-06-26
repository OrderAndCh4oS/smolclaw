# SmolClaw System Design Specification

Status: source-derived design spec
Last reviewed: 2026-06-26

This document describes the current SmolClaw architecture as implemented in the
repository. It is intended for developers who need to modify the system safely,
add adapters, extend tools, or reason about the runtime. It also calls out
areas that do not fit the intended patterns cleanly.

Related maintained docs:

- `docs/architecture-runtime.md`: runtime and tool execution diagrams.
- `docs/workspaces.md`: workspace layout, reset behavior, and adapter config.
- `docs/next-phase-implementation-design.md`: reliability implementation notes.
- `docs/memory-evals.md`: memory evaluation design and operating guidance.

## 1. System Purpose

SmolClaw is an agentic coding and research harness. It provides:

- interactive CLI and TUI chat surfaces;
- one-shot CLI execution for automation;
- a WebSocket gateway surface for remote/MCP-backed tool execution;
- configurable multi-agent personalities;
- local and MCP-backed tools;
- persistent session, memory, trace, approval, checkpoint, and goal state;
- a SmolRAG memory subsystem with vector search, BM25, a knowledge graph, and
  contradiction detection;
- a Jira/GitHub-oriented autonomous work-loop;
- local evaluation harnesses for agent trajectories and memory retrieval.

The primary architectural pattern is a dependency-injected runtime built from
small adapters and services. Production defaults use local files, SQLite,
NetworkX, OpenAI/Anthropic/Voyage clients, httpx, git, `gh`, and Atlassian
`acli`. Tests should supply fakes through constructors, factories, protocol
objects, or the CLI dependency context instead of patching globals.

## 2. Top-Level Architecture

```text
+---------------------+        +-----------------------+
| Human / Automation  |        | WebSocket Client / MCP|
+----------+----------+        +-----------+-----------+
           |                               |
           v                               v
+----------+----------+        +-----------+-----------+
| CLI / TUI / run     |        | Gateway               |
| cli.main / cli.tui  |        | app.gateway           |
+----------+----------+        +-----------+-----------+
           |                               |
           +---------------+---------------+
                           |
                           v
              +------------+-------------+
              | RuntimeServices          |
              | workspace, SmolRag,      |
              | SessionManager, env      |
              +------------+-------------+
                           |
                           v
              +------------+-------------+
              | Agent Factory            |
              | LLM, registry, hooks,    |
              | policies, shared state   |
              +------------+-------------+
                           |
                           v
              +------------+-------------+
              | AgentLoop                |
              | prompt, LLM, tools,      |
              | traces, goals, usage     |
              +------------+-------------+
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
 +--------+------+ +-------+-------+ +------+-------+
 | Tool System   | | SmolRAG       | | State Stores |
 | local/MCP     | | memory graph  | | sessions,    |
 | middleware    | | vector/BM25   | | traces, etc. |
 +---------------+ +---------------+ +--------------+
```

The runtime has four main boundaries:

- Entrypoints: CLI/TUI, WebSocket gateway, work-loop commands, eval scripts.
- Runtime composition: workspace paths, adapter config, SmolRAG, sessions,
  runtime environment, agent configs.
- Agent execution: context building, LLM calls, tool calls, middleware, traces,
  goal ledgers, usage.
- External adapters: LLM providers, embeddings providers, HTTP clients, MCP
  client, command runners, Jira/GitHub CLIs, filesystem and git.

## 3. Source Layout

```text
app/
  agent_*.py                 Agent config, factory, loop, eval runner
  runtime*.py                Runtime service building, capability config, adapter config
  tools/                     Tool interface, registry, concrete tools, middleware
  smol_rag.py                Memory facade and SmolRAG service composition
  ingestion.py/query_engine.py/document_manager.py
                             RAG ingestion, retrieval, and document removal
  *_store.py/vector_store.py/graph_store.py
                             SQLite, BM25, vector, and graph persistence
  gateway.py/mcp_client.py   WebSocket gateway and MCP JSON-RPC client
  work_loop.py/worktree.py/coding_lifecycle.py
                             Coding lifecycle automation and isolated worktrees
  goal_ledger.py/run_trace.py/approvals.py/checkpoints.py/usage.py
                             Reliability and observability stores
  diagnostics.py/logger.py/tracing.py
                             Logging, JSONL diagnostics, OpenTelemetry wrapper
cli/
  main.py                    Typer commands and dependency container
  tui.py                     Prompt-toolkit full-screen UI
  commands.py                Slash-command parsing and render helpers
agents.yaml                 Declarative agent definitions
agents/*.md                 Agent bootstraps
docs/                       Architecture, workspace, reliability, eval docs
scripts/                    Smoke, regression, memory eval, agent eval scripts
plugins/                    Currently bytecode-only residue, not an active plugin API
```

## 4. Workspace, Paths, And State

### Workspace Service

`app.workspace.WorkspaceContext` is the source of truth for repository and state
paths. It wraps `WorkspacePaths` from `app.definitions`.

Responsibilities:

- resolve source root and state root;
- create required state directories;
- resolve relative paths inside the workspace;
- reject paths outside the workspace with `resolve_contained_path`;
- support isolated worktree mode where source root and state root differ.

Important paths:

- workspace root: source repository under operation;
- state root: defaults to `<workspace>/.smolclaw`;
- `stores/`: SQLite database, graph, traces, ledgers, approvals, checkpoints,
  eval reports;
- `memory/`: durable memory markdown documents;
- `research/`: durable research source notes;
- `sessions/`: chat session JSONL files and usage sidecars;
- `logs/`: rotating logs and diagnostics events;
- `work-loop/`: work-loop items, job controls, and run workspaces;
- `input_docs/`: imported documents for ingestion.

### Path Safety

`app.storage_paths` provides safe storage stems, containment for storage files,
backup paths, and atomic writes. State stores should use these helpers instead
of ad hoc file writes when writing durable JSON, text, or binary data.

Tool-facing path safety is enforced in three layers:

- filesystem tools resolve paths through `WorkspaceContext`;
- permission middleware rejects external paths and secret paths;
- checkpoint and safety middleware independently resolve mutation targets.

## 5. Configuration Model

### Runtime Adapter Config

`app.runtime_config.RuntimeAdapterConfig` contains:

- `llm.default`: main agent completion provider/model;
- `llm.memory_extract`: model/provider used for memory extraction;
- `llm.memory_query`: model/provider used for memory querying;
- `llm.embeddings`: embedding provider/model;
- `llm.subagents`: default child-agent completion provider/model;
- `task_source`: work-loop task discovery provider;
- `code_review`: work-loop review provider;
- `command`: intended generic command provider.

Config files are merged in order:

1. `SMOLCLAW_CONFIG`;
2. user config under `~/.config/smolclaw/config.yaml`;
3. user config under `~/.smolclaw/config.yaml`;
4. workspace state config files;
5. `.smolclaw/config.*` under state root and source root.

Later files are applied over earlier values through `RuntimeAdapterConfig.from_dict`.
The loader accepts either a top-level adapter mapping or an `adapters:` wrapper.
For `task_source`, `code_review`, and `command`, it also accepts a nested
`default:` adapter shape.

Adapter config consumption status:

| Config section | Consumed by | Current status |
| --- | --- | --- |
| `llm.default` | `build_agent_loop` | Respected for default agent model/provider unless explicit model override is passed. |
| `llm.memory_extract` | `build_runtime_services` -> `create_smol_rag` | Respected for memory extraction completion. |
| `llm.memory_query` | `build_runtime_services` -> `create_smol_rag` | Respected for memory query completion. |
| `llm.embeddings` | `build_runtime_services` -> `create_smol_rag` | Respected for memory/vector embeddings. |
| `llm.subagents` | `RuntimeModelSettings`, `build_agent_loop` | Respected for child-agent defaults. |
| `task_source` | `cli.main._load_work_loop_config` | Respected unless work-loop config explicitly sets task-source type. |
| `code_review` | `cli.main._load_work_loop_config` | Respected unless work-loop config explicitly sets code-review type. |
| `command` | Parsed and stored | Not globally consumed by command runners or tool factories. This is a gap. |

### Agent Config

`agents.yaml` is loaded by `AgentConfigLoader`. Each `AgentConfig` declares:

- name;
- model or `default`;
- persona;
- explicit tool names;
- capability names;
- behaviors;
- bootstrap file;
- skills;
- permission mode;
- max iterations;
- memory window;
- context budget;
- timeout.

Capabilities are validated against:

- `filesystem`;
- `web`;
- `memory`;
- `orchestration`;
- `subagents`;
- `shell`;
- `command`;
- `goal`.

Transport is not declared in agent configs. Transport is runtime-selected:
direct local transport builds local tools, while MCP transport swaps supported
filesystem, web, and shell tools to MCP wrappers.

Current default agents:

- `default`: plan-mode assistant with filesystem read/search, git status/diff,
  web, memory, and goal tools.
- `researcher`: research-mode assistant with web, memory write/source storage,
  read/search, and goal tools.
- `coder`: execute-mode engineer with read/write filesystem tools, git tools,
  `run_command`, web, memory, and goal tools.
- `reviewer`: plan-mode read-only reviewer with memory and git inspection.
- `orchestrator`: delegate-only coordinator with memory lookup, orchestration,
  and subagent tools.

### Permission Policy Config

`app.tools.policy.load_permission_policy` merges:

- explicit paths;
- `SMOLCLAW_PERMISSION_POLICY`;
- user policy files;
- workspace policy files.

The default action is merged conservatively by action rank:
`deny` > `ask` > `allow`. Rules are appended in load order, and resolution uses
first matching rule. The docstring says user/explicit rules can override project
rules; because resolution is first-match, that is true for matching rules, while
default action remains conservative.

## 6. Runtime Composition

### Runtime Builder

`app.runtime_builder.build_runtime_services` creates `RuntimeServices`:

- `workspace`: `WorkspaceContext`, ensured on disk;
- `smol_rag`: `SmolRag` or injected instance;
- `session_manager`: `SessionManager` or injected instance;
- `env`: `RuntimeEnvironment`.

Inputs:

- workspace root or `WorkspaceContext`;
- transport, token issuer URL, gateway URL;
- agent configs and subagent enablement;
- optional LLM, RAG, and session manager;
- optional adapter config.

Runtime builder effects:

- loads adapter config if not injected;
- configures diagnostics under workspace log dir;
- creates SmolRAG with adapter-configured memory models and embedding provider;
- builds `RuntimeModelSettings` from subagent model/provider config;
- returns a `RuntimeEnvironment` that carries all runtime-level dependencies.

### Runtime Environment

`app.runtime.RuntimeEnvironment` is the dependency object used by agent
construction. It carries:

- SmolRAG instance;
- session manager;
- workspace context;
- transport;
- token issuer and gateway URLs;
- agent configs;
- subagent enablement;
- optional fixed LLM;
- optional LLM factory;
- runtime model settings;
- runtime adapter config.

Runtime helper functions:

- resolve capability names from agent config and available services;
- suppress memory for agents without memory capability;
- build context builder factories;
- build master tool registry;
- validate that configured tools exist;
- build an agent with `build_configured_agent`.

## 7. Agent Construction

`app.agent_factory.build_agent_loop` is the main composition function for an
agent loop.

Inputs:

- `AgentConfig`;
- master `ToolRegistry`;
- SmolRAG or `None`;
- `SessionManager`;
- session key or prefix;
- optional hook configurers;
- optional child loop registrar;
- optional model override;
- optional runtime model settings;
- optional LLM or LLM factory;
- optional adapter config;
- optional context builder factory;
- optional existing runtime shared state.

Main responsibilities:

- choose the completion model and provider from explicit model, runtime model
  settings, adapter config, or config model;
- create or reuse an LLM;
- resolve memory availability from capabilities;
- create a session;
- create durable stores:
  - `GoalLedgerStore`;
  - `RunTraceStore`;
  - `ApprovalRequestStore`;
  - `CheckpointStore`;
- create per-loop shared state via `RuntimeSharedState`;
- create `SafetyState`;
- create `ToolRuntimeContext`;
- create `ChildAgentFactory`;
- project the master registry to the configured agent tools and capabilities;
- install runtime middleware;
- create `ContextBuilder` or `ContextAssembler`;
- return an `AgentLoop`.

### Runtime Middleware Order

The per-agent projected registry is wrapped in this order after registry-level
logging/tracing middleware:

1. `HookFiringMiddleware`;
2. `PolicyPermissionMiddleware`;
3. `SafetyMiddleware`;
4. `EvidenceMiddleware`;
5. `CheckpointMiddleware`, when a workspace exists.

Because middleware is onion-style, developer changes must preserve the intended
semantics:

- hook events surround policy/safety/evidence/checkpoint behavior;
- permission blocks occur before safety and mutation execution;
- safety checks occur before evidence/checkpoint recording;
- evidence records tool outcomes and verification;
- checkpoints capture filesystem state around successful filesystem mutations.

### Child Agent Factory

`ChildAgentFactory` builds child loops for orchestration and subagents while
preserving:

- master registry;
- SmolRAG resolver;
- workspace;
- session manager;
- parent session key;
- LLM factory and model settings;
- adapter config;
- registry/context factories;
- hook configurers;
- child loop registrar.

Child sessions use stable parent-derived prefixes with a purpose slug and
counter. Child loops are flagged as child agents, which makes subagent model
config apply.

## 8. Agent Loop Runtime

`app.agent_loop.AgentLoop` is the execution engine for one session.

### Runtime State Owned By The Loop

The loop owns:

- LLM instance;
- projected tool registry;
- context builder;
- session and session manager;
- hook runner;
- SmolRAG reference;
- goal ledger store;
- safety state;
- runtime model settings;
- trace store;
- runtime shared state;
- usage collector and session usage summary;
- owned closeable resources.

### Turn Flow

```text
process(user_content)
  record diagnostics event
  start run trace
  mark goal loop running
  append turn.started
  _process_impl
    fire session-start hooks once
    begin safety task
    append user message
    increment active goal turn count
    consolidate old session messages into memory when the window is exceeded
    build context messages
    inject active goal prompt
    for iteration in max_iterations:
      fire before-turn hooks
      append behavior prompts on first iteration
      call LLM with visible tool schemas
      record usage, trace, events
      if no tool calls:
        stream/final assistant response
        save session
        fire after-turn hooks
        return
      append assistant tool-call message
      for each tool call:
        append tool.started
        set active tool ids in RuntimeSharedState
        invoke registry
        record tool duration/status
        append tool.ended / denied / safety events
        append tool result message
      drain tool-initiated LLM usage
      append behavior after-tools prompts
      fire after-turn hooks
    finalization pass without tools
  append turn.ended
  mark goal loop finished
  finish run trace
```

### Session Start And End

On first turn, the loop wires `UsageCollector` into the agent LLM and SmolRAG
LLM when available, then fires `ON_SESSION_START`.

On close:

- drain background usage;
- set session usage end time;
- fire `ON_SESSION_END`;
- close the LLM and owned resources, deduplicated by object identity.

Session-end hooks commonly include:

- `UsagePersistHook`;
- `SessionExportHook`;
- `ContradictionExpiryHook`.

### Memory Consolidation

When unconsolidated session messages exceed `memory_window`, the loop
summarizes that chunk using the agent LLM and ingests the summary into SmolRAG
as `session-<session_key>`. If summarization fails, raw text is ingested.

## 9. Context And Prompt Assembly

### ContextBuilder

`app.context_builder.ContextBuilder` builds the base prompt:

- persona or default SmolClaw identity;
- current timestamp;
- shared bootstrap;
- agent bootstrap;
- project instructions from `AGENTS.md`, `CLAUDE.md`, and state/source
  `.smolclaw/instructions.md`;
- latest memory eval summary if available;
- preloaded skill markdown.

It then appends session history and the current user message.

### ContextAssembler

`app.context_assembly.ContextAssembler` extends `ContextBuilder` when memory is
enabled. It retrieves relevant memories and appends them to the system prompt.

Retrieval sources:

- tier-0 identity memories from all current excerpts;
- vector search over excerpt embeddings;
- KG low-level and high-level retrieval;
- BM25 keyword search.

Scoring:

```text
score = importance * confidence * recency_decay * type_weight * tier_boost
```

Memory tiers:

- tier 0: identity, always included outside the normal budget;
- tier 1: core, boosted;
- tier 2: working, normal priority.

The assembler records an `AssemblyManifest` with included/excluded excerpts and
token usage. It also adds a lightweight prompt notice when unresolved memory
contradictions exist.

Important caveat: tier-0 memories are outside the token budget. That is useful
for identity invariants but can exceed prompt expectations if too many tier-0
items are stored.

### Behaviors

`app.behaviors` defines optional loop behaviors:

- `plan`: adds internal planning instructions before first LLM call and after
  tool results;
- `reflect`: adds internal sufficiency/checking instructions after tool results.

Agent config may use explicit `behaviors` or legacy booleans `planning` and
`reflection`.

## 10. LLM And Embedding Adapters

### LLM Protocols

`app.llm_base` defines protocol interfaces:

- `CompletionAdapter`;
- `ToolCompletionAdapter`;
- `StructuredCompletionAdapter`;
- `EmbeddingAdapter`;
- `LlmAdapter`.

Implementations are expected to be async from the harness perspective, even
where the underlying SDK is synchronous.

### LLM Factory

`app.llm.create_llm` chooses providers by explicit provider or model prefix:

- `claude-*` -> Anthropic;
- `voyage-*` -> Voyage embeddings;
- otherwise OpenAI.

It can return:

- `OpenAiLlm`;
- `AnthropicLlm`;
- `VoyageEmbeddingLlm` for embedding-only usage;
- `CompositeLlm`, pairing one completion provider with another embedding
  provider.

Factory seams:

- `openai_factory`;
- `anthropic_factory`;
- `voyage_factory`.

### OpenAI Adapter

`app.openai_llm.OpenAiLlm` supports:

- chat completions;
- Responses API translation for models/tool/reasoning settings that require it;
- tool calls;
- streaming chat output;
- structured output through `client.beta.chat.completions.parse`;
- single and batched embeddings;
- query and embedding caching in `SqliteKvStore`;
- usage recording.

Constructor seams:

- concrete `client`;
- `client_factory`;
- cache stores;
- API key;
- DB path.

### Anthropic Adapter

`app.anthropic_llm.AnthropicLlm` supports:

- Anthropic Messages API completion;
- tool calls;
- streaming;
- structured completion through schema-in-prompt plus parsing;
- query caching;
- usage recording.

It does not provide embeddings. Embedding requests raise
`NotImplementedError`, and Anthropic completion with embeddings should be
wrapped in `CompositeLlm`.

Constructor seams:

- concrete `client`;
- `client_factory`;
- query cache;
- DB path.

### Voyage Adapter

`app.voyage_llm.VoyageEmbeddingLlm` provides async embedding calls to Voyage,
embedding caching, usage recording, and closeable HTTP client ownership.

### Model Switching

`app.model_settings` supports runtime model selection and subagent model
selection. It intentionally disallows switching completion provider families on
an existing LLM instance; switching from OpenAI to Anthropic, for example,
requires rebuilding the runtime/agent.

## 11. Tool System

### Tool Contract

`app.tools.base.Tool` defines the tool interface:

- `name`;
- `description`;
- JSON-schema `parameters`;
- examples;
- deferred exposure flag;
- default call policy;
- runtime binding;
- dynamic call policy;
- async `execute`;
- OpenAI-compatible `to_schema`.

Tool return values are normalized into `ToolResult` with:

- `status`;
- content;
- metadata.

`ToolCallPolicy` describes side effects:

- effects;
- exploration requirements;
- approval requirements;
- reversibility;
- evidence recording;
- mutation state;
- delegation state;
- tags.

### Tool Runtime Context

`ToolRuntimeContext` carries:

- projected registry;
- LLM;
- hook runner;
- session manager;
- SmolRAG;
- workspace;
- session key;
- goal store;
- child-agent factory;
- loop registrar;
- shared runtime state;
- owned resources list.

Tools receive this context through `bind`.

### Tool Registry

`app.tools.registry.ToolRegistry` owns:

- registered tools;
- tool capability metadata;
- global middleware;
- per-tool middleware;
- dynamically exposed deferred tools.

Important operations:

- `register`;
- `get_definitions`;
- `search_tools`;
- `expose_tool`;
- `invoke`;
- `filter_by_names`;
- `project_for_agent`.

`project_for_agent` is central to least-privilege behavior. It exposes only:

- explicitly enabled non-deferred tools;
- deferred tools that match allowed capabilities;
- `tool_search` when hidden deferred tools exist.

### Tool Discovery

`ToolSearchTool` lets the model search and expose deferred tools at runtime.
Search is currently simple case-insensitive substring matching over name and
description, not semantic retrieval.

### Tool Factory

`app.tools.factory.build_tool_registry` maps capabilities and transport to tool
implementations.

Direct transport:

- filesystem: local read/write/edit/list/find/apply-patch/grep tools;
- web: direct Brave/httpx web search/fetch;
- command: direct git tools and `run_command`;
- memory: direct SmolRAG tools;
- goal: local goal tools;
- orchestration: local child-loop orchestration tools;
- subagents: local background subagent tools.

MCP transport:

- filesystem: MCP file read/write/edit wrappers;
- web: MCP HTTP fetch and web search wrappers;
- shell: MCP shell exec wrapper.

Direct shell is explicitly rejected until a real sandbox backend exists.

### Filesystem Tools

`app.tools.filesystem` provides:

- `ReadFileTool`;
- `WriteFileTool`;
- `EditFileTool`;
- `ListDirTool`;
- `FindFilesTool`;
- `ApplyPatchTool`;
- `GrepSearchTool`.

All operate relative to `WorkspaceContext`. Mutation tools declare filesystem
write effects and accept optional `reason` metadata for trace/ledger records.

`ApplyPatchTool` parses structured patch operations, plans changes, applies all
operations, and restores original state on errors. It is separate from Codex's
developer `apply_patch` tool.

### Command And Git Tools

`app.tools.command` provides agent-facing command tools:

- `GitStatusTool`;
- `GitDiffTool`;
- `GitBranchTool`;
- `GitCheckoutTool`;
- `GitPullTool`;
- `GitAddTool`;
- `GitCommitTool`;
- `GitPushTool`;
- `RunCommandTool`.

These tools use their own injected runner seam, defaulting to `subprocess.run`.
This is deliberately separate from `app.command_runner.CommandRunner`, which is
for harness infrastructure such as work-loop and worktree operations.

`RunCommandTool` is allowlist-based. It allows common verification commands and
read-only commands, denies known risky tokens by default, formats stdout/stderr,
handles timeouts, and supports a narrow approval bypass when policy middleware
has approved an exact command once.

### Infrastructure Command Runner

`app.command_runner` defines:

- `CommandResult`;
- `CommandRunner` protocol;
- `SubprocessCommandRunner`;
- active process registry and termination helpers.

This runner is used by work-loop, worktree, Jira/GitHub adapters, and eval live
runs. It uses `subprocess.Popen`, captures output, handles timeouts, and starts
its own process group on POSIX except inside managed work-loop jobs.

### Web Tools

`app.tools.web` provides:

- `WebSearchTool`, using Brave Search API;
- `WebFetchTool`, using httpx to fetch and strip HTML.

Both accept HTTP client factory seams. Search API configuration is loaded from
environment, the current working directory `.env`, or `SMOLCLAW_CONFIG_DIR/.env`
(defaulting to `~/.config/smolclaw/.env`).

### MCP Tools

`app.mcp_client.McpClient` supports:

- token issuer JSON-RPC flow;
- legacy one-hop direct execution response;
- token + gateway execution flow;
- injected async HTTP client factory.

`app.tools.mcp_tools` wraps MCP tools for:

- file read;
- file write;
- edit file as read/write composite;
- shell exec;
- HTTP fetch;
- web search.

MCP edit is not remote-atomic; it reads, replaces, then writes.

### Memory Tools

`app.tools.memory_tools` provides:

- `MemorySearchTool`;
- `MemoryGraphQueryTool`;
- `MemoryStoreTool`;
- `ResearchSourceStoreTool`;
- `MemoryRelateTool`;
- `MemoryRecallTool`;
- `MemoryGetTool`;
- `ContradictionReviewTool`.

Important behaviors:

- memory search and recall can return accessed excerpt IDs;
- agent factory installs a hook that promotes accessed excerpts;
- `MemoryStoreTool` writes durable markdown through `MemoryDocumentService` and
  then ingests into SmolRAG;
- `MemoryStoreTool` can classify memory type through the runtime LLM when the
  type is omitted;
- `ContradictionReviewTool` resolves pending contradictions through the
  contradiction detector.

### Research Source Tool

`ResearchSourceStoreTool` writes source-backed research notes under the
workspace research directory. It stores URL, title, summary, related URLs,
extracted text, topic, and captured timestamp. It can also ingest the note into
SmolRAG.

### Goal Tools

`app.tools.goal` provides:

- `goal_start`;
- `goal_status`;
- `goal_update`;
- `goal_record_evidence`.

They bind to the session-specific `GoalLedgerStore`. Completion is validated by
the ledger store: all acceptance criteria must be satisfied or not applicable,
and changed files require verification evidence or an explicit no-verification
reason.

### Orchestration Tools

`app.tools.orchestration_tools` wraps:

- `sequential_pipeline`;
- `fanout_pipeline`;
- `route`.

Each wrapper accepts a runner function seam and binds the runtime
`ChildAgentFactory`. The underlying `app.orchestration` functions build child
loops, run them, close them, and return results. Route uses structured LLM
classification when available and falls back to regex matching, then to the
first configured route.

### Subagent Tools

`app.tools.spawn` provides:

- `spawn_agent`;
- `get_result`;
- `await_result`.

They bind a `SubagentManager` into shared runtime state. The manager limits
concurrency, creates background asyncio tasks, stores results, and cancels
unfinished subagents when closed.

## 12. Tool Middleware And Safety Systems

### Logging And Tracing Middleware

`app.tools.middleware` provides:

- `MiddlewareChain`;
- `logging_middleware`;
- `RetryMiddleware`;
- `TimeoutMiddleware`;
- `CacheMiddleware`;
- `HookFiringMiddleware`;
- `TracingMiddleware`.

Registry-level middleware logs and traces all tool calls. Runtime-level
middleware adds policy, safety, evidence, and checkpoint behavior.

### Permission Modes

`app.tools.permissions` defines static permission modes:

- `full`;
- `plan`;
- `execute`;
- `research`;
- `delegate_only`.

Modes block tools and/or capability tags such as:

- `mutates_state`;
- `command_execution`;
- `workspace_write`;
- `memory_write`;
- `runtime_state_write`;
- `command_write`;
- `delegation`.

Hard path denies reject:

- `.env` and `.env.*` secret paths, excluding examples/templates;
- paths outside the workspace.

### Policy Permission Middleware

`PolicyPermissionMiddleware` layers configurable rules on top of hard path and
mode denies. Rule subjects:

- `tool`;
- `capability`;
- `path`;
- `command`.

Actions:

- `allow`;
- `ask`;
- `deny`.

`ask` creates an exact-call approval request. Approval can be consumed once. For
`run_command`, approved requests set a scoped bypass so the command tool can
execute a command that would otherwise be denied by its internal token filter.

### Safety Middleware

`SafetyMiddleware` is task-scoped and blocks workspace mutations until the agent
has explored the workspace.

Tracked evidence:

- git status;
- workspace search/list/diff;
- read paths;
- repeated identical tool calls.

Mutation gates require:

- git status or equivalent `run_command git status`;
- workspace search through find/grep/list/diff;
- relevant exploration of target path or parent;
- reading existing files before editing/deleting/updating.

### Evidence Middleware

`EvidenceMiddleware` records tool evidence into the active goal ledger and run
trace.

Evidence kinds:

- read;
- search;
- status;
- diff;
- command;
- test;
- memory;
- checkpoint.

Verification commands are detected from common test/check/lint command shapes.
Non-verification commands are recorded separately.

### Checkpoint Middleware

`CheckpointMiddleware` snapshots filesystem mutation targets before and after
successful `write_file`, `edit_file`, and `apply_patch` calls.

`CheckpointStore` stores JSON records with base64 snapshots up to
`MAX_SNAPSHOT_BYTES` (1 MB). Undo is refused if:

- no checkpoint exists;
- snapshots were skipped;
- original content is missing;
- current files no longer match the checkpoint's after-snapshot.

Checkpoint events update both traces and goal ledgers.

## 13. SmolRAG Memory System

### SmolRag Facade

`app.smol_rag.SmolRag` composes:

- LLM/embedding provider;
- store bundle;
- query engine;
- document manager;
- ingestion pipeline;
- rate limiter.

Constructor seams:

- LLM;
- LLM factory;
- individual stores;
- graph store;
- contradiction detector;
- document source provider;
- models/providers;
- DB paths;
- input docs dir;
- log dir.

The default `create_smol_rag` additionally wires a `ContradictionDetector` with
graph store, contradiction KV store, embedding function, and LLM adjudication
function.

### Store Bundle

`StoreBundle` groups:

- excerpt embeddings vector store;
- entity vector store;
- relationship vector store;
- source-doc mapping store;
- doc-excerpt mapping store;
- doc-entity mapping store;
- doc-relationship mapping store;
- excerpt KV store;
- BM25 store;
- NetworkX graph store;
- contradiction detector;
- provenance lock.

### Vector Store

`SqliteVectorStore` persists vectors in SQLite and maintains an in-memory
normalized matrix for fast cosine queries.

Key behaviors:

- WAL mode;
- table per vector domain;
- embedding model and dimension compatibility metadata;
- incompatible persisted rows ignored on load;
- upsert/delete update SQLite and in-memory matrix under a lock.

### BM25 Store

`BM25Store` is a SQLite-backed in-memory Okapi BM25 index. It uses NLTK
stopwords and Snowball stemming, with a fallback empty stopword set when NLTK
data is unavailable.

### KV And Mapping Stores

`SqliteKvStore` provides JSON value storage per table.

`SqliteMappingStore` provides relational left/right mapping tables for:

- source -> doc;
- doc -> excerpts;
- doc -> entities;
- doc -> relationships.

### Graph Store

`NetworkXGraphStore` stores the knowledge graph in GraphML. It provides
async-locked writes for nodes/edges and relationship upserts. It merges
multi-value fields using the KG separator.

Synchronous `save()` uses `nx.write_graphml` directly and blocks. `async_save()`
uses `asyncio.to_thread`.

### Ingestion Pipeline

`IngestionPipeline` handles:

- document source discovery;
- text ingestion;
- markdown/code-aware excerpting;
- frontmatter parsing;
- excerpt summaries;
- batched excerpt embeddings;
- BM25 indexing;
- LLM entity/relationship extraction;
- entity/relationship embeddings;
- graph upserts;
- Obsidian wiki links and tags;
- provenance mapping;
- contradiction checks;
- stale document replacement.

Document discovery uses an injected `document_source_provider`, defaulting to
`utilities.get_docs`.

Recognized frontmatter includes:

- memory type;
- tags;
- confidence;
- importance;
- source id;
- tier;
- title/kind/source URL/author;
- trust/evidence/captured metadata;
- entities;
- relationships;
- claims;
- supersedes.

### Query Engine

`QueryEngine` supports:

- vector RAG query;
- local KG query;
- global KG query;
- hybrid KG query;
- BM25 keyword query;
- mixed query combining vector, KG, and optional BM25.

It uses extract-model calls for keyword extraction and query-model calls for
answer synthesis. It filters stale vector rows when graph nodes/edges are
missing and filters excerpts by embedding model/dimension metadata.

### Document Manager

`DocumentManager` removes documents by ID or source. It cleans:

- source mappings;
- excerpt KV rows;
- BM25 rows;
- excerpt vectors;
- doc-excerpt mappings;
- entity/relationship mappings;
- graph node/edge excerpt references;
- orphaned entity/relationship vectors.

KG cleanup is protected by the store bundle provenance lock.

### Contradiction Detection

`ContradictionDetector` checks new entity and relationship facts before graph
upsert.

Detection phases:

1. structural embedding similarity check;
2. LLM adjudication only for candidates.

Resolution strategy:

- agreement merges silently;
- extraction-source contradictions are usually dismissed;
- user-source contradictions become pending;
- ambiguous cases become pending.

Records are stored in a SQLite KV table. Resolutions can keep existing, keep
new, merge, or dismiss. `ContradictionExpiryHook` auto-dismisses stale pending
records on session end.

### Memory Lifecycle

`MemoryLifecycleManager` promotes accessed excerpts by increasing importance.
Tier 2 memories auto-promote to tier 1 at importance >= 0.8. Recency is handled
at query/context scoring time rather than by decreasing importance.

### Memory Documents

`MemoryDocumentService` owns durable memory and research document files and
their SmolRAG source lifecycle.

Supported kinds:

- memory;
- journal;
- session;
- research;
- external.

It writes non-external documents through atomic storage helpers, optionally
removes prior indexed source content, then ingests the new content.

Important caveat: file write and RAG ingestion are not one database
transaction. A failure after writing but before full ingestion can leave the
document and index temporarily inconsistent.

### Session Export And Indexing

`SessionExportHook` runs on session end when enabled:

- generates a first-person journal through `journal.generate_journal`;
- indexes user/assistant session content through `session_indexer.index_session`.

Journal and session memories are written as markdown and ingested into SmolRAG.
Journal generation failure does not block session indexing.

### Memory Watcher

`MemoryFileWatcher` is a poll-based watcher. It hashes memory directory files,
detects created/modified/deleted documents, ingests changed files, removes
deleted files from SmolRAG, and fires `ON_FILE_CHANGE`.

## 14. Persistence And Observability

### Sessions

`app.session.SessionManager` stores sessions as JSONL sidecars under
`sessions/`. The first line is session metadata, followed by messages. Loading
uses containment checks.

### Goal Ledgers

`GoalLedgerStore` stores one structured JSON ledger per session. It tracks:

- objective;
- status;
- loop status;
- run ID;
- turn count;
- pending approvals;
- acceptance criteria;
- plan steps;
- inspected files;
- changed files;
- command evidence;
- verification evidence;
- blockers;
- notes.

The ledger is also rendered into the prompt for active goals.

### Run Traces

`RunTraceStore` stores append-only JSONL events plus summary JSON per run.

Events include:

- run started/ended;
- turn started/ended;
- LLM started/ended;
- tool started/ended/denied;
- safety blocks;
- permission decisions;
- approval requests/resolutions;
- checkpoints;
- ledger updates;
- verification records;
- errors.

Summaries track model, tool counts, denied calls, files changed, commands run,
checkpoints, verification, status, and stop reason.

### Approvals

`ApprovalRequestStore` stores exact-call approval requests per session.

Approval identity is based on:

- session key;
- tool name;
- hash of redacted, JSON-safe arguments.

Only `scope="once"` exists today. Approved requests are consumed and marked
`used` on the next matching call.

### Usage And Pricing

`UsageCollector` records LLM usage from provider adapters. The loop groups usage
by turn and background category.

Usage categories include:

- agent turn;
- consolidation;
- context retrieval;
- ingestion;
- journal;
- session index.

`UsagePersistHook` writes a `.usage.json` sidecar on session end.

`app.pricing` estimates costs for known models. Pricing values are static and
must be updated when provider pricing changes.

### Diagnostics

`app.diagnostics` configures workspace-local logging:

- rotating `smolclaw.log`;
- structured `events.jsonl`;
- error incidents with IDs;
- redaction of common secret keys and token-shaped values.

`app.logger` configures the `smolclaw.rag` logger and log cleanup.

### OpenTelemetry

`app.tracing` provides a no-op-by-default OpenTelemetry wrapper. When OTEL SDK
is installed and configured, it can export spans to an OTLP endpoint. Agent,
retrieval, and LLM span helpers are provided.

### Run Views

`app.run_views` builds and renders combined trace/ledger views for CLI and TUI:

- goal status;
- trace status;
- trace list;
- event tail;
- replay;
- run status view.

## 15. CLI And TUI Surfaces

### CLI Dependency Container

`cli.main.CliDependencies` is the CLI service container. It includes:

- console;
- prompt session factory;
- async runner;
- runtime builder;
- agent builder;
- tool registry builder;
- worktree runner factory;
- default chat agent builder;
- multiagent builder;
- memory store tool factory;
- session export hook factory;
- goal store factory;
- checkpoint store factory;
- approval store factory;
- TUI factory;
- run-once runner;
- TUI chat loop runner;
- research loop runner;
- work-loop supervisor factory;
- work-loop runner factory;
- research stop controller factory.

`override_cli_dependencies` is a scoped `ContextVar` override. It is the
preferred seam for CLI tests and alternate embeddings.

### CLI Commands

Primary Typer commands:

- `chat`: interactive chat, TUI by default;
- `run`: one-shot JSON-producing execution;
- `work-loop ...`: task/review automation and background job management;
- `init`: write/update project guidance;
- `doctor`: environment and dependency checks;
- `memory-eval`: memory eval suite runner;
- `research-loop`: repeated research runs;
- `ingest`: ingest documents into SmolRAG;
- `watch`: watch memory docs and re-ingest changes;
- `serve`: start gateway;
- `recall`: query memory;
- `index-sessions`: index existing session files;
- `reset`: clear derived state;
- `clear-logs`: remove log files.

### One-Shot Run

`_run_once` builds runtime, optionally creates an isolated worktree, builds the
requested agent, runs a prompt or goal loop, closes resources, and returns JSON
with:

- session key;
- status;
- loop status;
- goal run ID;
- pending approvals;
- response(s);
- trace path;
- trace summary path;
- ledger path;
- stop reason;
- worktree path/diff when applicable.

### Interactive Chat

There are two interactive paths:

- `_tui_chat_loop`: full-screen prompt-toolkit TUI;
- `_chat_loop`: prompt-toolkit prompt loop.

Both build runtime, stores, memory tools, session export hooks, slash commands,
and agent loops through dependency seams.

Slash commands cover:

- help;
- quit;
- logs;
- clear;
- init;
- undo;
- trace;
- approval;
- memory;
- worktree;
- work-loop;
- model;
- goal;
- remember;
- remember-thread.

### TUI

`cli.tui.CoderTui` is UI-only orchestration around an already-built agent. It
takes callbacks/providers for:

- goal store;
- session manager;
- memory store;
- session export hook;
- SmolRAG;
- checkpoint store;
- approval store;
- trace formatter;
- approval resolver;
- memory resolver;
- worktree resolver;
- work-loop resolver;
- project initializer;
- action-event formatter;
- terminal size provider;
- shutdown phase timeout;
- git state provider.

The TUI owns UI state, transcript/activity rendering, key bindings, worker loop
coordination, git/goal refresh tasks, slash command dispatch, streaming output,
and graceful shutdown.

### Research Loop

`research-loop` repeatedly runs a research agent against an ongoing goal. It
uses:

- runtime builder;
- agent builder;
- configurable interval;
- optional max runs;
- stop controller;
- optional Escape-key watcher on POSIX TTYs.

Each cycle asks the agent to search memory first, use web when needed, store
verified findings, and return deltas.

## 16. Gateway And MCP Transport

`app.gateway.Gateway` is the WebSocket surface.

Security:

- requires `SMOLCLAW_GATEWAY_TOKEN` or injected validator;
- remote bind requires `allow_remote`;
- sends challenge then expects `connect` request with token.

Runtime:

- initializes diagnostics in workspace log dir;
- initializes shared runtime in `mcp` transport;
- shares SmolRAG and SessionManager across session agents;
- builds default agent per session key;
- registers usage and contradiction-expiry hooks;
- supports `chat.send` and `chat.abort`;
- streams lifecycle, message, and activity events.

Gateway dependency seams:

- config loader;
- runtime builder;
- agent builder;
- token validator.

MCP transport changes tool implementation but not the agent loop. Unsupported
capabilities are rejected by `runtime_capabilities`.

## 17. Worktree Isolation

`app.worktree.WorktreeRunner` creates isolated execution workspaces.

Modes:

- clean git worktree from `HEAD`;
- dirty copy mode that copies the repository excluding `.git`, initializes a
  new git repo, and commits a baseline.

`WorktreeContext` supports:

- diffing isolated changes while excluding state paths;
- applying diff back to base repo;
- cleanup through git worktree removal or directory deletion.

Worktree commands go through `SubprocessCommandRunner`.

In CLI worktree mode, the active source root is the worktree path, while the
state root remains the original workspace state root. This keeps sessions,
memory, traces, and ledgers in the original workspace.

## 18. Coding Lifecycle And Work-Loop

### Generic Lifecycle Contracts

`app.coding_lifecycle` defines provider-neutral domain contracts:

- `LifecycleSourceRef`;
- `PublicationRef`;
- `ReviewFeedbackRef`;
- `CodingLifecycleWork`;
- `CodingPassResult`;
- `PublicationResult`;
- `WorkDiscoveryAdapter`;
- `SourceControlReviewAdapter`;
- `PublicationAdapter`;
- `CodingPassExecutor`.

These types represent the desired generic coding lifecycle independent of Jira
or GitHub.

### Current Work-Loop Implementation

`app.work_loop` is still Jira/GitHub-oriented. It has two modes:

- first-pass task intake from Jira to PR creation;
- follow-up handling for review comments/check failures on open PRs.

Main services:

- `WorkLoopConfig`: configuration for providers, project, statuses, models,
  task profiles, verification commands, internal review, concurrency;
- `TaskCandidate`: generic-ish task candidate with a `JiraCandidate` alias;
- `WorkItem`: persisted work item state;
- `WorkLoopLedger`: durable item storage;
- `WorkLoopControl`: STOP/PAUSE/heartbeat files;
- `WorkLoopJobStore`: background job metadata;
- `WorkLoopJobSupervisor`: starts/stops/pauses/resumes worker processes;
- `JiraAdapter`: Atlassian `acli` integration;
- `GitHubAdapter`: GitHub `gh` integration;
- `DoneGateRunner`: verification discovery and execution;
- `RunWorkspaceManager`: per-item worktree paths and cleanup;
- `GitOperations`: git status/fetch/worktree/commit/push;
- `InternalReviewRunner`: runs reviewer agent through CLI;
- `CliAgentTaskExecutor`: runs coder agent through CLI with goal loop and
  verification/repair attempts;
- `WorkLoopRunner`: orchestrates preflight, task runs, review runs, and item
  state transitions.

### Work-Loop First-Pass Flow

```text
preflight
  task-source auth
  code-review auth
  clean git status
  fetch base branch
  discover verification commands
search backlog
filter eligible candidates
select candidates
for each candidate:
  view detailed source item
  select execution profile
  create WorkItem
  create branch worktree
  transition source item
  run coder CLI goal loop
  run verification
  optionally run internal reviewer
  optionally repair review findings
  commit and push
  create PR
  transition source item to review
  comment with PR link/status
  save ledger
  cleanup run workspace
```

### Work-Loop Review Flow

```text
preflight without task-source requirement
for each open-pr WorkItem:
  view PR
  detect new actionable comments/check failures
  recreate branch workspace if needed
  run coder CLI with review feedback
  run verification
  commit and push
  comment on PR
  record processed review comments
  save ledger
```

### Adapter Config In Work-Loop

`cli.main._load_work_loop_config` applies runtime adapter config:

- `task_source.provider` overrides work-loop task source type unless config
  explicitly declares it;
- `code_review.provider` overrides work-loop code review type unless config
  explicitly declares it.

Only `jira` and `github` builders exist today. Other provider names will parse
but fail at adapter construction.

## 19. Eval Harnesses

### Agent Eval

`app.agent_eval.AgentEvalRunner` supports:

- mock mode;
- recorded mode;
- live mode.

It loads task fixtures, copies fixture repos, creates workspace state, records
mock or live evidence, scores ledger/trace/diff artifacts, writes reports, and
can run verification commands. Live mode uses an injected command runner seam,
defaulting to `subprocess.run`.

### Memory Eval

`app.memory_eval` defines deterministic and live-ish memory suites:

- corpus sources;
- expected entities;
- expected relationships;
- expected claims;
- retrieval questions;
- staleness expectations;
- contradiction expectations.

Modes include deterministic, RAG retrieval, and answer generation. Reports are
written as JSON and used by context building as optional memory eval summaries.

### Memory Coding Eval

`app.memory_coding_eval` compares coding task performance with memory off/on
for fixture tasks and patch expectations.

## 20. Bootstrap, Doctor, Reset, Utilities

### Bootstrap

`app.bootstrap.init_project_guidance` writes or updates a marked block in
`AGENTS.md`. It includes:

- project name;
- local workflow reminders;
- detected verification commands.

It currently writes with direct file I/O, not atomic storage helpers.

### Doctor

`app.doctor.run_doctor` checks:

- state root writability;
- OpenAI key;
- Anthropic key;
- NLTK stopwords;
- NLTK punkt_tab;
- gateway token.

It accepts injected environment and NLTK resource checker seams.

### Reset

`app.reset` clears derived workspace state. It can reset:

- logs;
- memories;
- journals;
- RAG stores;
- KG stores.

Research source notes are intentionally preserved.

### Utilities

`app.utilities` contains text/file/hash/token helper functions. Some memory and
ingestion paths still use simple file helpers from this module; newer durable
state writers should prefer `storage_paths`.

## 21. External Dependencies And Boundaries

| Boundary | Production implementation | Injection seam |
| --- | --- | --- |
| OpenAI completion/embedding | `OpenAiLlm` with OpenAI SDK | `client`, `client_factory`, `openai_factory` |
| Anthropic completion | `AnthropicLlm` with Anthropic SDK | `client`, `client_factory`, `anthropic_factory` |
| Voyage embeddings | `VoyageEmbeddingLlm` with httpx | `voyage_factory`, owned client/cache |
| LLM factory | `create_llm` | runtime `llm_factory`, provider factories |
| Web search/fetch | httpx async clients | `http_client_factory` |
| MCP execution | `McpClient` | client instance/factory, HTTP client factory |
| Harness commands | `SubprocessCommandRunner` | `CommandRunner` protocol |
| Agent command tool | `subprocess.run` callback | per-tool `command_runner` callable |
| Work-loop task source | `JiraAdapter` using `acli` | `TaskSourceAdapter`, `task_source` constructor arg |
| Work-loop code review | `GitHubAdapter` using `gh` | `CodeReviewAdapter`, `code_review` constructor arg |
| CLI runtime | default functions/classes | `CliDependencies` and `override_cli_dependencies` |
| Gateway runtime | default loaders/builders | constructor `config_loader`, `runtime_builder`, `agent_builder` |
| Document discovery | `utilities.get_docs` | `document_source_provider` |
| Doctor environment | `os.environ`, NLTK | `env`, `nltk_resource_checker` |
| aiosqlite close join | `asyncio.to_thread` | `to_thread` callable |

## 22. Current Architectural Strengths

- Runtime construction is centralized in `RuntimeServices` and
  `RuntimeEnvironment`.
- Agent config is declarative and transport-independent.
- Capability projection creates a least-privilege tool surface per agent.
- External boundaries have explicit seams for LLMs, HTTP clients, command
  runners, runtime builders, gateway builders, and CLI dependencies.
- Tool behavior is composed with middleware instead of embedded directly in
  every tool.
- Permission, safety, evidence, and checkpointing are cross-cutting concerns
  with separate modules.
- Workspace and state roots are explicit, enabling isolated worktrees while
  preserving shared state.
- Durable run traces and goal ledgers make agent behavior inspectable.
- Approval requests are exact-call and persisted, reducing accidental broad
  authorization.
- Memory persistence separates durable source documents from derived indexes.
- SmolRAG stores track embedding model/dimensions to avoid mixing incompatible
  vectors.
- Tests can avoid monkeypatching through constructors, factories, protocols, and
  context override managers.

## 23. Problem Areas And Design Gaps

### Runtime Adapter Config Is Not Fully Honored

`RuntimeAdapterConfig.command` is parsed and preserved but not consumed by:

- `build_tool_registry`;
- `RunCommandTool`;
- infrastructure `CommandRunner`;
- worktree;
- work-loop;
- eval live runners.

This means command provider config is currently documentation/config surface
without runtime effect.

Recommended fix:

- introduce a command-runner provider factory keyed by adapter config;
- thread it through `RuntimeEnvironment`;
- pass agent-facing runners into command tools;
- pass infrastructure runners into work-loop/worktree/eval services;
- keep policy and allowlist behavior separate from process execution.

### Work-Loop Is Partially Generic But Still Jira/GitHub Shaped

`coding_lifecycle.py` defines provider-neutral contracts, but `work_loop.py`
still exposes:

- `JiraCandidate` alias;
- `jira_key`;
- `jira_url`;
- `jira`/`github` constructor aliases;
- Jira/GitHub prompt and comment names;
- builders that support only Jira and GitHub.

Recommended fix:

- migrate persisted schema toward `source_ref` and `publication_refs`;
- keep backward-compatible readers for old work items;
- replace provider-specific field names in prompts and renderers;
- introduce adapter registries for task source, code review, and publication.

### Some Subprocess Usage Bypasses The CommandRunner Abstraction

Most infrastructure commands use `CommandRunner`, but exceptions remain:

- `RunWorkspaceManager.cleanup` uses raw `subprocess.run`;
- `WorkLoopJobSupervisor` directly uses `subprocess.Popen` because it owns
  background process creation;
- TUI `_git_state` defaults to `subprocess.run`, though it has a provider seam.

Recommended fix:

- make cleanup use injected `CommandRunner`;
- keep supervisor process creation separate but document it as process lifecycle
  rather than command execution;
- use `SubprocessCommandRunner` or a small git-state provider in production TUI.

### Async Interfaces Wrap Synchronous Provider SDK Calls

OpenAI and Anthropic adapters expose async methods but call synchronous SDK
clients inside those methods. This can block the event loop during provider
calls. Voyage uses async HTTP.

Recommended fix:

- migrate to async provider clients where available; or
- use bounded `to_thread` execution around sync calls; and
- add concurrency tests for TUI/gateway responsiveness.

### Memory Document Writes And Indexing Are Not Atomic Together

`MemoryDocumentService` writes a durable file and then mutates SmolRAG indexes.
Those operations span filesystem, SQLite, graph, and vector stores without a
single transaction.

Recommended fix:

- add ingestion job records with status;
- make startup/watch repair reconcile documents and index state;
- store source document version/hash consistently before and after indexing.

### Graph Persistence Is A Scalability And Consistency Hotspot

`NetworkXGraphStore` stores the graph in GraphML. It locks writes but sync
`save()` blocks. GraphML is simple but not ideal for high-concurrency or large
graphs.

Recommended fix:

- consistently use `async_save`;
- evaluate SQLite edge/node tables or a graph-native store if memory grows;
- add graph integrity checks and migration/version metadata.

### Best-Effort Exception Handling Can Hide Data Quality Problems

Several paths intentionally swallow or degrade errors:

- frontmatter parse failures;
- context retrieval fallbacks;
- memory promotion hooks;
- session export journal/indexing failures;
- contradiction hooks.

This is good for user-facing robustness but can obscure memory quality issues.

Recommended fix:

- emit structured diagnostics for every degraded path;
- add counters in run summaries or memory health reports;
- distinguish expected parse misses from unexpected exceptions.

### Tool Search Is Simple Substring Matching

Deferred tool discovery is name/description substring matching. This is
predictable but weak once the tool catalog grows.

Recommended fix:

- add ranked lexical search or embedding-backed discovery;
- keep deterministic fallback for tests.

### Checkpoint Coverage Is Bounded

Checkpoints skip non-files and files larger than 1 MB. Undo is impossible for
skipped snapshots. That is safer than partial restore, but users need to know
large-file mutations are not protected.

Recommended fix:

- surface skipped checkpoint paths in UI and final run status;
- consider configurable max snapshot size.

### Direct Command Tool And Direct Shell Capability Are Easy To Confuse

Direct local shell capability is disabled. The `command` capability still
provides git tools and allowlisted `run_command` execution. These are different
security surfaces.

Recommended fix:

- keep capability naming explicit in docs/UI;
- consider renaming `command` to `safe_command` or documenting the distinction
  in agent/tool descriptions.

### Runtime Shared State Is Still A Dict Compatibility Layer

`RuntimeSharedState` is a typed facade, but the underlying wire format remains a
mutable dict for compatibility. Unknown string keys can still collide.

Recommended fix:

- move all known shared values to typed fields or a dataclass;
- keep dict adapter only at tool boundary.

### Plugin Directory Is Not An Active Extension System

`plugins/` currently contains only bytecode files and no source manifests wired
into runtime. Developers should not assume a plugin architecture exists.

Recommended fix:

- remove bytecode residue from the repo; or
- define a real plugin manifest/loader and document the extension lifecycle.

### Pricing Data Is Static

`app.pricing` contains static pricing with an effective date. Costs can become
incorrect as provider pricing changes.

Recommended fix:

- make pricing table versioned and easy to update;
- mark estimates clearly in UI;
- add tests that only validate shape/math, not market currency truth.

## 24. Recommended Engineering Standards Going Forward

- All external boundaries should be protocols, factories, or constructor
  dependencies.
- Runtime config should be consumed in exactly one obvious composition layer.
- Tool behavior should stay small; safety, permission, evidence, retries, and
  tracing should remain middleware.
- Persistent schemas should include version fields and migration paths.
- New state writes should use `storage_paths` atomic helpers.
- New provider adapters should include fake-client tests through constructor
  injection.
- New CLI behavior should be testable through `CliDependencies`, not global
  patching.
- New work-loop providers should implement generic lifecycle protocols first,
  with legacy Jira/GitHub shape only as compatibility adapters.
- New memory ingestion flows should record source hash/version and support
  repair/reconciliation.
- Async runtime code should not call blocking provider or subprocess APIs
  without an explicit runner/thread boundary.
- Permission and safety changes should include regression tests for denied,
  asked, approved, and allowed paths.
- Tool schemas and command output shapes should be treated as public API for
  agent behavior and kept stable unless migration is intentional.

## 25. Developer Modification Guide

### Adding A New Tool

1. Implement `Tool` in `app/tools/`.
2. Define accurate `ToolCallPolicy` tags/effects.
3. Add it to `build_tool_registry` under the appropriate capability.
4. Decide whether it should be deferred.
5. Add it to agent configs only where needed.
6. Add tests for schema, permission behavior, safety/evidence interaction, and
   execution through fakes.

### Adding A New LLM Or Embedding Provider

1. Implement the relevant protocol from `llm_base`.
2. Accept concrete client and client factory seams.
3. Record usage through `UsageCollector`.
4. Add provider detection or explicit provider handling in `create_llm`.
5. Add adapter config examples.
6. Add tests with fake clients and composite completion/embedding cases.

### Adding A New Work-Loop Provider

1. Implement generic lifecycle protocols in `coding_lifecycle.py`.
2. Add a legacy bridge only if current `WorkLoopRunner` still needs it.
3. Register the provider in task-source/code-review adapter factories.
4. Add runtime adapter config tests.
5. Avoid provider-specific field names in new persisted data.

### Adding A New CLI Feature

1. Add dependencies to `CliDependencies` if construction or external effects
   are needed.
2. Keep Typer wrapper thin.
3. Put logic in an internal function accepting `deps`.
4. Add tests using `override_cli_dependencies`.
5. Ensure resources are closed on success and error.

### Adding New Persistent State

1. Put it under `WorkspacePaths`.
2. Use containment-safe path helpers.
3. Add schema version.
4. Use atomic writes.
5. Add load-with-backup behavior for JSON where corruption would be costly.
6. Document reset behavior.

## 26. Summary

SmolClaw is organized around a strong runtime composition pattern: entrypoints
build services, services build agents, agents project tools, middleware enforces
policy/safety/observability, and durable stores make runs inspectable. The best
parts of the system are the explicit dependency seams, declarative agent config,
capability projection, and reliability sidecars.

The areas needing the most architectural attention are command adapter config
consumption, the partially generic work-loop, remaining direct subprocess use,
blocking sync SDK calls inside async methods, and transactional consistency in
memory document ingestion. Addressing those would make the implementation match
the intended application engineering patterns more completely.
