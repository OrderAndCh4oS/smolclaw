# SmolClaw System Design Specification

Status: source-derived design spec
Last reviewed: 2026-06-26

This document describes the current SmolClaw architecture as implemented in the
repository. It is intended for developers who need to modify the system safely,
add adapters, extend tools, reason about runtime behavior, or evaluate whether a
change follows the project architecture. Accuracy matters more than aspiration:
where the implementation has gaps, this document names them.

Related docs:

- [workspaces.md](workspaces.md): workspace layout, reset behavior, and adapter config.
- [memory-evals.md](memory-evals.md): memory evaluation design and operating guidance.
- [smolclaw-memory-eval.yaml](smolclaw-memory-eval.yaml): deterministic eval suite for current project docs.

Older roadmap, research, and design-planning notes have been removed after the
project pivot. This specification is the architecture source of truth.

## 1. Project Goals

SmolClaw is a local-first coding assistant harness. The current project goals are:

1. Build a reliable terminal coding agent that understands a workspace before editing it.
2. Keep all external dependencies behind explicit constructors, factories, providers, or context-scoped dependency containers.
3. Make runtime behavior adapter-driven so model, command, task-source, review, MCP, and HTTP dependencies can be configured and tested without global patching.
4. Preserve user control and auditability through permission policies, approvals, checkpoints, traces, ledgers, usage records, and diagnostics.
5. Provide durable project memory through SmolRAG with provenance, contradiction handling, source documents, and eval coverage.
6. Support multi-agent and work-loop automation while keeping the core local agent path safe, observable, and recoverable.
7. Keep tests deterministic by using explicit seams instead of `patch`, `patch.dict`, or `monkeypatch.setattr` dependency substitution.

Non-goals for the current phase:

- SmolClaw is not a general-purpose shell sandbox. Direct arbitrary shell execution remains disabled.
- The gateway and MCP surfaces are secondary to local reliability, although they are maintained.
- Work-loop automation currently targets Jira and GitHub only.
- The command adapter provider registry supports `subprocess` only today; unsupported providers fail fast.

## 2. System Context

```text
-------------------+        +-------------------+
| Human / CLI / TUI|        | Gateway / MCP     |
| cli.main/cli.tui |        | app.gateway       |
+---------+---------+        +---------+---------+
          |                            |
          +-------------+--------------+
                        |
                        v
          +-------------+--------------+
          | RuntimeServices            |
          | workspace, diagnostics,    |
          | adapter config, commands,  |
          | SmolRAG, sessions, env     |
          +-------------+--------------+
                        |
                        v
          +-------------+--------------+
          | Agent Factory              |
          | LLM, registry projection,  |
          | middleware, hooks, state   |
          +-------------+--------------+
                        |
                        v
          +-------------+--------------+
          | AgentLoop                  |
          | prompt assembly, LLM turn, |
          | tool calls, traces, goals  |
          +-------------+--------------+
                        |
        +---------------+----------------+
        |               |                |
        v               v                v
+-------+------+ +------+-------+ +------+-------+
| Tool System  | | SmolRAG      | | State Stores |
| local/MCP    | | memory, KG,  | | sessions,    |
| middleware   | | vector, BM25 | | ledgers, etc |
+--------------+ +--------------+ +--------------+
```

The design uses composition over global lookup. Entrypoints build dependency
objects, factories consume those objects, and tests supply fakes through the same
interfaces production uses.

## 3. Source Layout

```text
app/
  runtime_config.py          Adapter config data model and loader.
  runtime_builder.py         Workspace-scoped runtime service composition.
  runtime.py                 RuntimeEnvironment and configured-agent assembly.
  command_runner.py          Infrastructure command runner protocol and subprocess implementation.
  command_adapters.py        Runtime command provider bundle for infrastructure and agent-facing tools.
  agent_config.py            AgentConfig model and YAML loader.
  agent_factory.py           AgentLoop composition, middleware wiring, child-agent factory.
  agent_loop.py              Main model/tool iteration engine.
  llm.py                     LLM provider selection and CompositeLlm.
  openai_llm.py              OpenAI completion/tool/Responses/embedding adapter.
  anthropic_llm.py           Anthropic Messages adapter.
  voyage_llm.py              Voyage embedding adapter.
  smol_rag.py                Memory facade and SmolRAG service composition.
  ingestion.py               Chunking, embeddings, entity extraction, and graph ingestion.
  document_manager.py        Document deletion and source-map cleanup.
  memory_documents.py        Durable memory/research document writes and opt-in ingestion jobs.
  graph_store.py             NetworkX graph persistence and async atomic save.
  vector_store.py            Local vector store.
  bm25_store.py              Keyword index.
  sqlite_store.py            SQLite key-value store.
  tools/                     Tool contracts, registry, concrete tools, policies, middleware.
  checkpoints.py             File mutation checkpoint records and undo.
  goal_ledger.py             Goal state, acceptance criteria, and evidence.
  run_trace.py               Append-only run trace and summary store.
  approvals.py               Exact-call approval store.
  diagnostics.py             Structured JSONL diagnostics and incident reporting.
  gateway.py                 WebSocket JSON-RPC gateway.
  mcp_client.py              MCP/token/gateway HTTP client.
  worktree.py                Isolated git worktree helper.
  work_loop.py               Jira/GitHub coding lifecycle automation.
  coding_lifecycle.py        Provider-neutral lifecycle data contracts.

cli/
  main.py                    Typer commands, CliDependencies, TUI/run/work-loop flows.
  tui.py                     Prompt-toolkit full-screen UI.
  commands.py                Slash-command parser and formatting helpers.

agents.yaml                  Default agent definitions.
agents/*.md                  Agent bootstrap prompts.
docs/                        Project docs.
scripts/                     Eval and smoke scripts.
tests/                       Unit, integration-style, CLI, eval, and regression tests.
```

## 4. Architectural Principles

### Explicit Dependency Seams

Dependencies cross boundaries through:

- constructors;
- factory parameters;
- protocol objects;
- runtime provider bundles;
- `CliDependencies`;
- scoped CLI overrides through `override_cli_dependencies`;
- injected HTTP clients and LLM clients;
- injected command runners.

Tests should not patch global module functions for dependency substitution.
Environment and cwd monkeypatching is acceptable only when the behavior under
test is environment or cwd handling.

### Local-First Runtime

The direct local path is the primary product surface. Gateway and MCP code are
kept functional, but local CLI/TUI reliability drives design decisions.

### Least Privilege By Projection

Agent configs declare tools and capabilities. The master registry contains the
system catalog, but each agent receives a projected registry with only the tools
it is allowed to see. Deferred tools remain hidden until exposed through
`tool_search`.

### Durable, Inspectable State

Runtime state is intentionally stored under the workspace `.smolclaw/` tree.
Most state stores use JSON or SQLite so users and developers can inspect,
repair, and test behavior without opaque services.

### Fail Fast At Adapter Boundaries

Unsupported provider config should fail when the runtime or work-loop is built,
not halfway through agent execution. The command adapter currently supports only
`subprocess`; task-source and review adapters support only `jira` and `github`.

## 5. Workspace And State Model

`WorkspaceContext` is the source of truth for source root and state root.

Responsibilities:

- resolve workspace-relative paths;
- reject paths outside the workspace;
- ensure runtime directories exist;
- support isolated worktrees where source root and state root differ.

Important workspace paths:

- `.smolclaw/stores/smolclaw.db`: SQLite-backed stores and caches.
- `.smolclaw/stores/kg.graphml`: knowledge graph.
- `.smolclaw/stores/traces`: run traces and summaries.
- `.smolclaw/stores/ledgers`: goal ledgers.
- `.smolclaw/stores/approvals`: approval requests.
- `.smolclaw/stores/checkpoints`: file mutation checkpoints.
- `.smolclaw/sessions`: session JSON files and usage sidecars.
- `.smolclaw/logs`: logs and diagnostics events.
- `.smolclaw/memory`: durable memory markdown.
- `.smolclaw/research`: durable research/source notes.
- `.smolclaw/work-loop`: work-loop items, jobs, controls, and run workspaces.

`app.storage_paths` provides safe storage stems, contained storage paths,
backup paths, and atomic writes. Durable JSON/text/binary state should use these
helpers.

## 6. Configuration Model

`RuntimeAdapterConfig` has four provider domains:

- `llm`: default, memory extraction, memory query, embeddings, and subagents.
- `task_source`: work-loop task source provider.
- `code_review`: work-loop review/publication provider.
- `command`: host command provider.

Config lookup order:

1. `SMOLCLAW_CONFIG`.
2. `~/.config/smolclaw/config.yaml`.
3. `~/.smolclaw/config.yaml`.
4. workspace state config files.
5. `.smolclaw/config.*` under state root and source root.

Later files override earlier values. The loader accepts either a top-level
adapter mapping or an `adapters:` wrapper. Provider selections also accept a
nested `default:` shape where relevant.

Current consumption:

| Config | Consumer | Status |
| --- | --- | --- |
| `llm.default` | `build_agent_loop` | Used for default agent model/provider unless a model override or explicit agent model applies. |
| `llm.memory_extract` | `build_runtime_services` -> `create_smol_rag` | Used. |
| `llm.memory_query` | `build_runtime_services` -> `create_smol_rag` | Used. |
| `llm.embeddings` | `build_runtime_services` -> `create_smol_rag` | Used. |
| `llm.subagents` | `RuntimeModelSettings`, child-agent construction | Used. |
| `task_source` | CLI work-loop config loading | Used unless work-loop YAML explicitly sets the task source type. |
| `code_review` | CLI work-loop config loading | Used unless work-loop YAML explicitly sets the review type. |
| `command` | `build_command_adapter_bundle` | Used to build infrastructure and agent-facing command runners. Only `subprocess` is supported. |

## 7. Runtime Composition

`build_runtime_services` creates `RuntimeServices`:

- `workspace`: ensured `WorkspaceContext`;
- `smol_rag`: created or injected `SmolRag`;
- `session_manager`: created or injected `SessionManager`;
- `env`: `RuntimeEnvironment`.

Runtime build sequence:

1. Normalize and ensure workspace paths.
2. Configure diagnostics under the workspace log directory.
3. Load `RuntimeAdapterConfig` unless supplied.
4. Build command adapters from `adapter_config.command`.
5. Build SmolRAG with memory and embedding provider config.
6. Build session manager.
7. Build subagent `RuntimeModelSettings`.
8. Return `RuntimeEnvironment`.

`RuntimeEnvironment` carries:

- SmolRAG;
- session manager;
- workspace;
- transport;
- token issuer and gateway URLs;
- agent configs and subagent enablement;
- optional fixed LLM;
- optional LLM factory;
- infrastructure command runner;
- agent-facing subprocess-compatible command runner;
- model settings;
- adapter config.

`build_master_registry` passes `env.agent_command_runner` into command and git
tools. Infrastructure consumers such as worktrees and work-loops use
`env.command_runner` or command adapters created directly from the same config.

## 8. Command Architecture

There are two command seams:

1. Infrastructure command runner: `CommandRunner.run(args, cwd, input_text, timeout)` returning `CommandResult`.
2. Agent-facing command callable: a `subprocess.run`-compatible callable used by `RunCommandTool` and git tools.

`app.command_adapters.build_command_adapter_bundle` creates both from the same
provider selection. Today:

- supported provider: `subprocess`;
- unsupported providers raise `ValueError`;
- `SubprocessCommandRunner` owns `Popen`, captured output, timeouts, process groups, and active process termination;
- `AgentSubprocessAdapter` exposes the `CommandRunner` through the subset of `subprocess.run` used by command tools.

Consumers:

- CLI worktree creation uses a configured infrastructure runner.
- `WorktreeRunner` and `WorktreeContext` carry an injected runner.
- `WorkLoopRunner`, Jira adapter, GitHub adapter, git operations, verification, internal review, and run workspace cleanup use injected runners.
- Agent command tools receive the agent-facing runner through tool registry construction.
- Eval runners accept command runners.
- TUI git state accepts a provider; production TUI receives the configured agent runner.

Intentional exception:

- `WorkLoopJobSupervisor` directly uses `subprocess.Popen` and signal APIs because it owns background worker process lifecycle. This is process supervision, not simple command execution.

## 9. Agent Configuration

`AgentConfig` fields include:

- `name`;
- `model`;
- `persona`;
- `tools`;
- `capabilities`;
- `behaviors`;
- `bootstrap_path`;
- `skills`;
- `permission_mode`;
- `max_iterations`;
- `memory_window`;
- `context_budget`;
- `timeout_seconds`.

Capabilities:

- `filesystem`;
- `web`;
- `memory`;
- `orchestration`;
- `subagents`;
- `shell`;
- `command`;
- `goal`.

Default configured agents:

- `default`: plan-mode assistant focused on inspection, memory, web, and goals.
- `researcher`: research-mode assistant with web and memory write/source tools.
- `coder`: execute-mode coding agent with filesystem writes, git, run command, memory, web, and goals.
- `reviewer`: read-only reviewer for correctness and tests.
- `orchestrator`: delegate-only coordinator with orchestration and subagent tools.

## 10. Agent Factory And Loop

`build_configured_agent` resolves capabilities, memory, context builders, hooks,
and the projected master registry before calling `build_agent_loop`.

`build_agent_loop` is responsible for:

- selecting the LLM provider/model;
- creating or reusing the LLM;
- creating/loading the session;
- creating goal, trace, approval, and checkpoint stores;
- creating `RuntimeSharedState`;
- creating `SafetyState`;
- creating `ToolRuntimeContext`;
- creating `ChildAgentFactory`;
- projecting the tool registry;
- installing middleware;
- creating the context builder or assembler;
- returning `AgentLoop`.

Runtime middleware order:

1. `HookFiringMiddleware`.
2. `PolicyPermissionMiddleware`.
3. `SafetyMiddleware`.
4. `EvidenceMiddleware`.
5. `CheckpointMiddleware`.

Registry-level logging and tracing middleware are installed before runtime
projection. Middleware order matters:

- policy must block before safety/evidence/checkpoints;
- safety must block before mutation execution;
- evidence records command/read/search/test/verification outcomes;
- checkpoints snapshot only successful filesystem mutations.

`AgentLoop.process` flow:

1. Start trace and goal-loop run state.
2. Append user message.
3. Consolidate old messages into memory when needed.
4. Build context messages.
5. Inject active goal context.
6. Call LLM with visible tool definitions.
7. Stream final text or execute tool calls.
8. For each tool call, set active tool IDs in shared state, invoke registry, append trace and session events.
9. Repeat until final response or max iterations.
10. Finalize trace, goal run state, and session.

On close, the loop drains usage, fires session-end hooks, closes owned resources,
and deduplicates close calls by object identity.

## 11. Runtime Shared State

`RuntimeSharedState` is a typed facade over the shared-state dictionary used by
tools and middleware. It preserves the dict wire format while providing stable
accessors for:

- trace recorder;
- trace store;
- session key;
- approval store;
- checkpoint store;
- safety state;
- permission policy;
- active tool call IDs;
- one-shot denied-command bypass.

It also provides scoped context managers for active tool IDs and approved command
bypass, plus typed retrieval helpers for new state keys.

## 12. LLM And Embedding Providers

`create_llm` detects providers by explicit config or model prefix:

- `claude-*`: Anthropic.
- `voyage-*`: Voyage embeddings.
- otherwise OpenAI.

It returns:

- `OpenAiLlm`;
- `AnthropicLlm`;
- `VoyageEmbeddingLlm`;
- `CompositeLlm` when completion and embedding providers differ.

Factory seams:

- `openai_factory`;
- `anthropic_factory`;
- `voyage_factory`.

`OpenAiLlm` supports:

- chat completions;
- Responses API translation for reasoning/tool turns;
- tool calls;
- streaming;
- structured output through OpenAI parse API;
- single and batched embeddings;
- SQLite query and embedding caches;
- usage recording.

`AnthropicLlm` supports:

- Messages API completions;
- tool calls;
- streaming;
- schema-prompted structured completion;
- SQLite query cache;
- usage recording.

Anthropic does not provide embeddings. Use `CompositeLlm` with OpenAI or Voyage
embeddings.

`VoyageEmbeddingLlm` supports Voyage embeddings, caching, usage recording, and
explicit close semantics.

OpenAI and Anthropic SDK calls are wrapped with an async compatibility helper:
sync client methods run in a worker thread, and awaitable results are awaited.
This keeps the harness async-facing while supporting sync SDK clients and test
fakes.

## 13. Context And Prompt Assembly

`ContextBuilder` builds system context from:

- persona;
- current timestamp;
- shared bootstrap;
- agent bootstrap;
- project instructions from `AGENTS.md`, `CLAUDE.md`, and `.smolclaw/instructions.md`;
- latest memory eval summary;
- configured skills;
- session history.

`ContextAssembler` extends `ContextBuilder` when memory is enabled. It retrieves:

- tier-0 identity memories;
- vector matches;
- BM25 keyword matches;
- low-level and high-level graph context;
- contradiction notices.

Memory scoring uses importance, confidence, recency, type weighting, and tier
boosts. Tier-0 memories are intentionally outside the normal token budget, which
is useful for identity invariants but can inflate prompts if overused.

## 14. Tool System

`Tool` defines:

- `name`;
- `description`;
- JSON schema parameters;
- examples;
- deferred visibility flag;
- default call policy;
- bind behavior;
- async `execute`;
- OpenAI-compatible schema conversion.

`ToolRegistry` owns:

- tool instances;
- capability metadata;
- global middleware;
- per-tool middleware;
- exposed deferred tools.

Important registry operations:

- `register`;
- `get_definitions`;
- `search_tools`;
- `expose_tool`;
- `invoke`;
- `filter_by_names`;
- `project_for_agent`.

Deferred tool search uses deterministic lexical ranking. Exact name matches rank
above prefix/name-token matches, which rank above description-only matches.
Ties are sorted by tool name.

`build_tool_registry` maps capabilities and transport to concrete tools.

Direct transport:

- filesystem tools;
- web tools;
- command/git tools;
- memory tools;
- goal tools;
- orchestration tools;
- subagent tools.

MCP transport:

- file read/write/edit wrappers;
- shell wrapper;
- HTTP fetch wrapper;
- web search wrapper.

Direct local shell execution remains disabled until a real sandbox backend
exists.

## 15. Tool Families

### Filesystem

Tools:

- `read_file`;
- `write_file`;
- `edit_file`;
- `list_dir`;
- `find_files`;
- `apply_patch`;
- `grep_search`.

All paths are resolved through `WorkspaceContext`. Mutation tools accept
optional `reason` metadata for checkpoint and evidence records. `ApplyPatchTool`
plans and applies structured patch operations and restores original state on
multi-step failure.

### Command And Git

Tools:

- `git_status`;
- `git_diff`;
- `git_branch`;
- `git_checkout`;
- `git_pull`;
- `git_add`;
- `git_commit`;
- `git_push`;
- `run_command`.

`run_command` is allowlist-based. It permits common verification commands and
read-only inspection commands, denies risky tokens, enforces cwd containment,
formats output, handles timeouts, and supports a narrowly scoped approval bypass.

### Web

Tools:

- `web_search`, using Brave Search API;
- `web_fetch`, using httpx and HTML text extraction.

Both accept HTTP client factory seams. Search configuration can come from
environment, local `.env`, or config-dir `.env`.

### MCP

`McpClient` supports token-issuer flow, gateway/direct proxy execution, and
injected async HTTP client factories. MCP tool wrappers accept a client or client
factory.

MCP edit is implemented as read, local string replace, write. It is not remote
atomic.

### Memory

Tools:

- `memory_search`;
- `memory_graph_query`;
- `memory_store`;
- `research_source_store`;
- `memory_relate`;
- `memory_recall`;
- `memory_get`;
- `contradiction_review`.

Memory search and recall can return accessed excerpt IDs. Agent factory installs
hooks that promote accessed memories after tool use. `MemoryStoreTool` writes
durable markdown through `MemoryDocumentService` and ingests through SmolRAG.

### Goal

Tools:

- `goal_start`;
- `goal_status`;
- `goal_update`;
- `goal_record_evidence`.

Goal completion is constrained by `GoalLedgerStore`: acceptance criteria must be
satisfied or not applicable, and changed files require verification evidence or
an explicit no-verification reason.

### Orchestration And Subagents

Orchestration tools:

- `sequential_pipeline`;
- `fanout_pipeline`;
- `route`.

They bind to the runtime `ChildAgentFactory` and accept runner seams. Route uses
structured LLM classification when available, then regex fallback, then first
configured route.

Subagent tools:

- `spawn_agent`;
- `get_result`;
- `await_result`.

They use `SubagentManager`, stored in runtime shared state, to manage background
tasks and close/cancel behavior.

## 16. Permission, Safety, Evidence, And Checkpoints

Permission modes:

- `full`;
- `plan`;
- `execute`;
- `research`;
- `delegate_only`.

Permission policy supports subjects:

- tool;
- capability;
- path;
- command.

Actions:

- allow;
- ask;
- deny.

Hard denies always block secret `.env` files and paths outside the workspace.
`ask` creates an exact-call approval request. Approved exact calls are consumed
once.

Safety middleware blocks mutation until the agent has explored:

- git status;
- workspace search/list/diff;
- relevant target file or parent path.

Evidence middleware records:

- read;
- search;
- status;
- diff;
- command;
- test;
- checkpoint.

Checkpoint middleware snapshots successful filesystem mutations. Large or
non-file snapshots are skipped and now surfaced in checkpoint metadata and trace
events. Undo refuses skipped snapshots and refuses conflicts when files changed
after the checkpoint.

## 17. SmolRAG Memory System

`SmolRag` composes:

- LLM/embedding provider;
- store bundle;
- query engine;
- document manager;
- ingestion pipeline;
- rate limiter;
- contradiction detector.

Stores:

- SQLite source/excerpt/entity/relationship maps;
- vector store;
- BM25 store;
- NetworkX graph store;
- contradiction store.

Ingestion flow:

1. Normalize source ID.
2. Split document into excerpts.
3. Summarize excerpts.
4. Generate embeddings.
5. Extract entities and relationships.
6. Parse Obsidian links/tags and frontmatter metadata.
7. Upsert vector, entity, relationship, source map, and graph records.
8. Save vector stores and graph asynchronously.

Graph persistence is atomic:

- writes GraphML to a temp file;
- replaces the destination with `os.replace`;
- runs async saves in a worker thread.

Graph metadata includes a schema version.

`MemoryDocumentService` owns durable memory, journal, session, research, and
external source writes. It supports opt-in ingestion job records with stages,
errors, and repair. Job persistence is explicit through `ingestion_jobs_dir` so
existing memory directories are not polluted by default.

Document deletion is handled by `DocumentManager`, which removes source maps,
excerpts, vector rows, BM25 entries, graph provenance, and orphaned graph
entities/relationships.

## 18. State Stores And Observability

Primary durable stores:

- `SessionManager`: session messages and metadata.
- `GoalLedgerStore`: objective, acceptance criteria, verification, evidence, changed files.
- `RunTraceStore`: append-only JSONL events plus run summaries.
- `ApprovalRequestStore`: exact-call approval requests.
- `CheckpointStore`: mutation snapshots and undo metadata.
- `UsagePersistHook`: usage JSON sidecars.
- `MemoryDocumentService`: durable memory/research document files.
- work-loop item/job stores.

Diagnostics:

- `diagnostics.configure` installs rotating logs and JSONL events.
- `record_exception` writes structured incidents with redaction.
- Graph load degradation records structured diagnostics and falls back to an empty graph.

Tracing:

- `app.tracing` wraps OpenTelemetry when configured and no-ops otherwise.
- Tool middleware and LLM adapters set trace attributes for duration, model, tokens, and tool status.

Pricing:

- `app.pricing` tracks model pricing with source URLs, effective dates, and a table version.
- Usage summaries aggregate credits/USD and unknown model calls.

## 19. CLI And TUI

`cli.main` is the Typer entrypoint. It defines:

- `smolclaw` chat/TUI default;
- `smolclaw run`;
- `smolclaw init`;
- `smolclaw doctor`;
- `smolclaw reset`;
- `smolclaw research-loop`;
- `smolclaw memory-eval`;
- `smolclaw work-loop ...`.

`CliDependencies` is the dependency container for tests and alternate entrypoint
composition. It includes console, prompt session, async runner, runtime builder,
agent builder, registry builder, worktree runner factory, TUI factory, work-loop
factories, stores, hooks, and loop runner overrides.

`override_cli_dependencies` uses a `ContextVar` so tests can scope dependency
overrides and guarantee restoration.

`cli.tui.CoderTui` owns the full-screen prompt-toolkit UI. It accepts:

- terminal size provider;
- shutdown phase timeout;
- git state provider;
- stores and command resolvers;
- formatting callbacks.

The TUI runs slow status/utility tasks in a worker loop so rendering is not
blocked by filesystem, trace, memory, approval, or undo operations.

## 20. Gateway And MCP

`app.gateway` provides a WebSocket JSON-RPC style protocol.

Responsibilities:

- authentication challenge/response;
- agent creation and session reuse;
- chat send/abort lifecycle;
- output streaming;
- run ID and session metadata;
- error event emission.

Gateway construction accepts dependencies for config loading, runtime building,
and agent building. This keeps gateway tests and alternate hosting paths from
patching module globals.

`McpClient` and MCP tools handle remote tool invocation over HTTP. MCP wrappers
are selected by transport and capability. Gateway and MCP are functional but
secondary to local CLI/TUI reliability.

## 21. Worktree And Work-Loop Automation

`WorktreeRunner` creates isolated git worktrees or dirty copies and carries an
injected `CommandRunner`. `WorktreeContext` can:

- show isolated diffs;
- apply diffs back to the base repo;
- clean up worktree state.

Work-loop automation lives in `app.work_loop`.

Core types:

- `WorkLoopConfig`;
- `TaskCandidate`;
- `WorkItem`;
- `WorkLoopLedger`;
- `WorkLoopJob`;
- `WorkLoopControl`;
- `WorkLoopRunner`;
- `CodingLifecycleWork`.

`WorkItem` has provider-neutral accessors:

- `source_key`;
- `source_url`;
- `source_provider`.

Legacy fields remain:

- `jira_key`;
- `jira_url`;
- `task_source_type`.

The ledger writes both neutral and legacy fields for compatibility.

Provider registries:

- task source: `jira`;
- code review: `github`.

`JiraAdapter` uses Atlassian `acli` through `CommandRunner`.
`GitHubAdapter` uses `gh` through `CommandRunner`.

`WorkLoopRunner` flow:

1. Preflight auth, git clean state, base branch fetch, and verification commands.
2. Search/select task candidates.
3. Create branch worktree.
4. Run coder agent through CLI.
5. Run verification and optional internal review.
6. Commit and push.
7. Create PR.
8. Transition/comment task source.
9. Record ledger state.
10. Clean run workspace.

Review mode:

1. Find open PR items.
2. Read GitHub comments/reviews/checks.
3. Filter actionable feedback.
4. Recreate/ensure worktree.
5. Run coder agent with review feedback.
6. Commit/push.
7. Respond on PR and update ledger.

Background jobs are supervised by `WorkLoopJobSupervisor`, which directly owns
process creation and signal termination. This is the intentional direct process
lifecycle exception.

## 22. Evaluation Systems

Agent evals:

- `AgentEvalRunner`;
- mock, recorded, and live modes;
- trace/ledger/diff scoring;
- required evidence checks;
- score deltas and suite JSON.

Memory evals:

- deterministic corpus checks;
- RAG retrieval scoring;
- answer/citation scoring;
- stale-source and contradiction hygiene.

Memory coding evals:

- memory-on versus memory-off workspaces;
- injected command runner;
- deterministic verification contrast.

All eval runners expose command/client seams where external execution is needed.

## 23. Testing Standards

Current acceptance standard:

- no `with patch(...)`;
- no `@patch(...)`;
- no `patch.dict(...)`;
- no `monkeypatch.setattr(...)` for dependency substitution.

Allowed:

- constructor fakes;
- provider objects;
- factory injection;
- CLI dependency overrides;
- context managers dedicated to test overrides;
- `monkeypatch.setenv`, `delenv`, and `chdir` when the test is about environment or cwd behavior.

Important verification commands:

```bash
rg 'with patch\(|@patch\(|patch\.dict|monkeypatch\.setattr' tests
pytest
git diff --check
```

## 24. Known Gaps And Problem Areas

### Command Provider Depth

The command adapter config is now respected everywhere the runtime builds command
runners, but only `subprocess` is implemented. A real sandbox, remote executor,
or container-backed provider would require a new `CommandRunner` implementation
and policy review.

### Work-Loop Provider Breadth

The work-loop lifecycle model is provider-neutral at the data-contract level,
but concrete task/review providers are still Jira and GitHub only.

### MCP Edit Atomicity

MCP edit is read/replace/write. It is practical but not remote-atomic and can
race with external edits.

### Prompt Budget Risk

Tier-0 memory bypasses normal context-budget scoring. This is deliberate but can
cause prompt growth if too many identity/core facts are stored as tier 0.

### Streaming SDK Blocking

Non-streaming OpenAI/Anthropic calls are async-compatible through worker-thread
wrapping. Streaming paths still iterate synchronous SDK streams in the event loop
where the SDK exposes synchronous iterators. This is acceptable today but should
be revisited if streaming latency becomes a UI problem.

### Process Supervision Exception

`WorkLoopJobSupervisor` intentionally uses direct process APIs. Do not route it
through `CommandRunner` unless the replacement preserves process group,
environment, pause/stop, and kill semantics.

### Schema Migration Coverage

Work-loop items carry a schema version and migrate legacy Jira fields into
neutral fields on load/save. Other JSON stores are mostly tolerant readers rather
than formal migrators. If state contracts harden, add explicit schema versions
and migration tests per store.

### Gateway Priority

Gateway code is dependency-injected and tested, but local CLI/TUI remains the
primary reliability target. Avoid designing core features that only work through
gateway transport.

## 25. Practices Followed Well

- Runtime composition is centralized in `build_runtime_services`.
- Agent construction is centralized in `build_configured_agent` and `build_agent_loop`.
- External systems have explicit injection seams.
- CLI tests use `CliDependencies` and scoped overrides.
- Local tools are projected by capability and agent tool list.
- Permission, safety, evidence, and checkpoint behavior are layered as middleware.
- Durable state lives under the workspace state root.
- Atomic writes are used for important JSON/text state.
- Graph save is non-blocking and atomic.
- Command adapter config is respected by runtime, CLI worktrees, work-loop, TUI git state, and tool registry construction.
- LLM adapters support client/factory injection and async-facing calls.
- Tool discovery is deterministic and ranked.
- Tests cover the seams without monkeypatching dependencies.

## 26. Practices To Improve Next

- Add real non-subprocess command providers only with clear sandbox semantics.
- Expand provider-neutral work-loop support beyond Jira/GitHub.
- Formalize schema versions and migrations across all state stores.
- Replace synchronous streaming SDK iteration with true async streaming where clients support it.
- Add richer diagnostics for adapter selection and degraded memory/query behavior.
- Consider making MCP edit transactional through gateway-supported operations.
- Continue shrinking public mutable shared-state usage in favor of typed helpers.
- Keep README, runtime architecture docs, and this spec synchronized when architecture changes.

## 27. Developer Change Checklist

Before changing a subsystem:

1. Identify the owning service or adapter boundary.
2. Prefer existing factories, protocols, and dependency containers.
3. Add a constructor/factory seam before introducing a test fake.
4. Preserve workspace containment for file paths.
5. Preserve middleware order for tool behavior.
6. Record diagnostics for degraded fallbacks.
7. Add focused tests for the new seam or behavior.
8. Run the no-patch grep.
9. Run the relevant targeted tests.
10. Run full `pytest` before merging broad architecture changes.

## 28. Current Verdict

The current architecture follows established application engineering patterns:
explicit dependency injection, adapter boundaries, provider configuration,
capability projection, middleware composition, durable state stores, and
source-derived tests. The main remaining risks are not structural confusion but
provider maturity: command has one provider, work-loop has two concrete external
providers, and several state stores are tolerant rather than fully migrated.

The system is now in a good position for contributors to add providers and tools
without patching globals or bypassing runtime configuration. New work should
continue to make dependencies explicit, keep local reliability first, and update
this spec when a boundary changes.
