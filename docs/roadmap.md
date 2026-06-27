# SmolClaw Roadmap

Status: current implementation roadmap
Last reviewed: 2026-06-27

This roadmap describes the next implementation work after the project pivot. It
is not a historical planning note. The architecture source of truth is
[system-design-spec.md](system-design-spec.md); this file turns the current
gaps, risks, and engineering focus into sequenced implementation work with
expected impact and acceptance criteria.

## Roadmap Principles

1. Preserve local reliability as the primary product target.
2. Keep dependency seams explicit and testable without global patching.
3. Improve user trust through observable runs, durable evidence, and reversible changes.
4. Add provider breadth only after the core contracts are stable.
5. Use evals and trace/ledger evidence to justify safety and orchestration complexity.
6. Keep gateway and remote-control work secondary until local sandboxing, approvals, and state contracts are stronger.

## Priority Overview

| Priority | Workstream | Primary Impact | Risk Reduced |
| --- | --- | --- | --- |
| P0 | Shared run presentation | Users and evals see one consistent run state | Status drift across CLI/TUI/evals |
| P0 | Eval suite expansion | Reliability changes become measurable | Anecdotal quality assessment |
| P1 | Worktree dirty-copy hardening | Safer isolated coding on dirty repos | Copying secrets, caches, stale build output |
| P1 | Real sandbox backend | Agent commands run in isolated containers/workspaces | Host filesystem, env, network, and resource escape |
| P1 | Approval UX improvements | Safer side effects with less operator friction | Overbroad or confusing approvals |
| P1 | Target-aware safety tuning | Fewer unsafe edits and fewer false blocks | Irrelevant exploration unlocking mutation |
| P1 | Plan/build mode UX | Clear separation between analysis and mutation | Accidental edits during planning |
| P1 | LSP code intelligence | Better localization and refactor accuracy | Grep-only understanding of code structure |
| P1 | Todo planning tool | Lightweight progress tracking during ordinary tasks | Goal ledger too heavy for every task |
| P2 | Redo and conversation rewind | Faster recovery and iteration after bad edits | One-way undo workflows |
| P2 | Subagent navigation UX | More usable multi-agent sessions | Hidden or hard-to-follow delegated work |
| P2 | State schema migrations | More durable long-term state contracts | Silent incompatibility across versions |
| P2 | Runtime shared-state narrowing | Clearer internal contracts | Dict key drift and accidental collisions |
| P2 | Adapter diagnostics | Easier support/debugging | Hidden degraded provider behavior |
| P2 | Custom tools and plugins | User-extensible harness behavior | Core-code changes for every integration |
| P3 | IDE integration | Better daily developer workflow | Terminal-only context entry |
| P3 | Sharing and export | Easier collaboration and support | Local-only run/session artifacts |
| P3 | Daily-driver polish | Lower friction for regular use | Rough command/theme/keybinding workflows |
| P3 | Provider maturity | More deployment options | Single-provider bottlenecks |
| P3 | Async streaming and MCP atomicity | Better responsiveness and remote correctness | UI stalls and remote edit races |

## Phase 1 - Shared Run Presentation

### Objective

Make `/trace`, `/goal status`, eval reports, non-interactive JSON, and future TUI
drawers render the same underlying run status. The trace and goal ledger already
exist; the cleanup is to make every surface consume shared view models rather
than reinterpreting artifacts independently.

### Current State

- `RunTraceStore` persists JSONL events and summaries.
- `GoalLedgerStore` tracks objectives, criteria, plan state, evidence, changed files, verification, blockers, and stop reasons.
- `app/run_views.py` provides shared formatting for compact run status.
- CLI and TUI paths use some shared renderers, but parity coverage is not complete.

### Implementation Details

1. Promote `RunStatusView` as the canonical read model for user-facing run state.
2. Add typed fields for:
   - latest trace path;
   - trace summary path;
   - ledger path;
   - status;
   - stop reason;
   - changed files;
   - verification evidence;
   - pending approvals;
   - checkpoint ids;
   - worktree isolation metadata.
3. Route all status surfaces through the same view builder:
   - `/trace`;
   - `/goal status`;
   - `smolclaw run --json`;
   - eval report summaries;
   - TUI status/detail drawers.
4. Keep terminal styling in CLI/TUI only. The view model should be plain data.
5. Add snapshot-style parity tests using one fixture trace and ledger.

### Impact

- Users get consistent answers about what happened in a run.
- Eval failures become easier to triage because reports point at the same fields as the CLI.
- Future UI work becomes safer because the TUI renders canonical state instead of inventing a parallel model.

### Acceptance Criteria

- A single trace/ledger fixture produces equivalent status in CLI, TUI helper output, eval report text, and non-interactive JSON.
- Status includes changed files, verification, stop reason, approval state, and artifact paths.
- Tests fail if a surface drops one of the canonical fields.

## Phase 2 - Eval Suite Expansion And CI Score Deltas

### Objective

Move from useful harness plumbing to a decision-grade eval suite. The goal is not
to benchmark models broadly; it is to detect regressions in SmolClaw's local
coding behavior, safety behavior, and run artifact integrity.

### Current State

- `scripts/run_agent_eval.py` supports mock, recorded, and opt-in live modes.
- Eval scoring checks trace/ledger integrity, loop state, approval state, denied tool-call expectations, failure classes, and score deltas.
- `scripts/ci_agent_eval.py` runs deterministic recorded coding fixtures plus the memory-on/off coding contrast fixture without model credentials.
- Memory evals have deterministic fixture and docs suites.

### Implementation Details

1. Add coding-agent fixtures:
   - documentation-only change;
   - blocked secret read;
   - approval-required command;
   - dirty-worktree preservation;
   - generated-file edit;
   - large-repo exploration;
   - parser bugfix;
   - memory-on/off coding contrast.
2. For each fixture define:
   - prompt;
   - allowed files;
   - forbidden files;
   - expected status;
   - required evidence;
   - verification commands;
   - expected failure class where applicable.
3. Record deterministic artifacts for recorded mode:
   - ledger JSON;
   - trace summary;
   - trace JSONL where useful;
   - diff;
   - command output summary.
4. Add CI entrypoints:
   - fast deterministic eval subset on every run;
   - optional live smoke via explicit environment flag;
   - baseline score comparison with `--max-score-drop`.
5. Report score dimensions separately:
   - exploration;
   - safety;
- permissions;
- approval pause state;
- touched files;
   - verification;
   - completion;
   - trace/ledger integrity.

### Impact

- Roadmap decisions can be tied to failing fixtures and score movement.
- Safety changes can be tuned against known false-positive and false-negative cases.
- Refactors to tools, prompts, or runtime state get an end-to-end regression signal.

### Acceptance Criteria

- At least six realistic fixtures run in deterministic mode.
- CI can compare current score against a committed baseline.
- Reports identify failure class, failed checks, artifact paths, and recommended next action.
- Live evals remain opt-in and never run accidentally without explicit credentials/config.

## Phase 3 - Worktree Dirty-Copy Hardening

### Objective

Make isolated work safe enough for regular use on dirty repositories. Clean git
worktrees are preferred; dirty-copy mode exists for practical local work but
needs stronger guardrails and review.

### Current State

- `WorktreeRunner` creates isolated git worktrees or dirty copies.
- `chat --worktree` and `run --worktree` keep source root separate from original workspace state root.
- `/worktree status`, `/worktree diff`, `/worktree apply`, and `/worktree discard` exist.
- Dirty-copy behavior has preflight metadata, default exclusions, warnings, private-key refusal, and review-gated broad apply-back.

### Implementation Details

1. Add pre-copy analysis:
   - file count;
   - total bytes;
   - ignored-root detection;
   - known cache/build directory detection;
   - secret-path warnings;
   - large binary detection.
2. Add injectable thresholds with safe defaults.
3. Record isolation metadata in trace summaries and eval reports:
   - isolation mode;
   - dirty-copy flag;
   - file count;
   - byte count;
   - excluded roots;
   - warning count.
4. Improve apply-back review:
   - summarize changed files;
   - show added/deleted/modified counts;
   - warn on large diffs;
   - require `/worktree apply --confirm` for broad apply-back;
   - keep `.smolclaw/` excluded from exported diffs.
5. Add regression tests for state placement:
   - sessions;
   - traces;
   - ledgers;
   - approvals;
   - checkpoints;
   - memory;
   - eval artifacts.

### Impact

- Users can isolate work without accidentally copying secrets, virtualenvs, caches, or stale artifacts.
- Future long-running and remote-origin work has a safer substrate.
- Apply-back becomes a deliberate review step instead of a blind patch transfer.

### Acceptance Criteria

- Dirty-copy mode refuses or warns on threshold violations.
- Run status and trace summaries show isolation metadata.
- Apply-back review lists risk indicators before applying broad diffs.
- Tests prove state writes stay under the original workspace state root for every worktree entrypoint.

## Phase 4 - Real Sandbox Backend

### Objective

Move SmolClaw from "supervised local harness" to a real isolated coding
harness. A real sandbox means agent-controlled commands and file mutations cannot
access the host outside the mounted isolated workspace, cannot read host secrets,
cannot use network by default, and cannot apply changes back without explicit
review.

### Current State

- `CommandRunner` and `CommandAdapterBundle` provide the right injection seam.
- `SubprocessCommandRunner` is the only supported command provider.
- Worktree mode separates editable source root from durable `.smolclaw` state.
- Direct local shell capability remains disabled until a sandbox backend exists.
- Worktree isolation protects the base repo from direct edits but does not
  isolate host process execution.

### Implementation Details

1. Split execution lanes explicitly:
   - host infrastructure lane for trusted SmolClaw operations such as worktree
     creation, git apply-back, Jira/GitHub lifecycle calls, and job supervision;
   - agent sandbox lane for model-triggered commands, tests, builds, package
     commands, generated artifacts, and file mutations.
2. Add a sandbox abstraction:
   - `SandboxBackend.prepare(workspace, run_id)`;
   - `SandboxContext.source_root`;
   - `SandboxContext.state_root`;
   - `SandboxContext.run_command(args, cwd, env, timeout)`;
   - `SandboxContext.export_diff()`;
   - `SandboxContext.cleanup()`.
3. Add a Docker/Podman MVP provider:
   - `DockerCommandRunner`;
   - `DockerSandboxBackend`;
   - `DockerSandboxContext`;
   - command adapter provider value: `docker`;
   - optional provider alias: `podman` if invocation differences stay small.
4. Make sandbox mode imply isolated source mode:
   - never mount the base repo as the mutable workspace;
   - create or reuse an isolated worktree/copy;
   - mount only that source root into the container as `/workspace`;
   - keep `.smolclaw` state under the original workspace on the host.
5. Use secure container defaults:
   - non-root user;
   - `--network none`;
   - `--cap-drop ALL`;
   - `--security-opt no-new-privileges`;
   - CPU, memory, process, and timeout limits;
   - read-only mounts except `/workspace` and controlled temp/cache paths;
   - no Docker socket, home directory, SSH agent, cloud config, or provider keys.
6. Add environment policy:
   - allowlist only basic execution variables such as `PATH`, `LANG`, `LC_ALL`,
     `CI`, and sandbox-local `HOME`;
   - deny provider keys, `SSH_AUTH_SOCK`, `GITHUB_TOKEN`, `AWS_*`, cloud config,
     and user shell startup files by default;
   - record redacted env policy decisions in diagnostics.
7. Add network policy:
   - default: no network;
   - later: per-command or per-run approval for full network;
   - host allowlists can come after the MVP, not before.
8. Add resource policy:
   - default timeout;
   - CPU limit;
   - memory limit;
   - process limit;
   - disk/cache budget where practical;
   - deterministic timeout/cancellation behavior.
9. Add apply-back review:
   - changed file list;
   - diff size;
   - add/delete/modify counts;
   - large/generated-file warnings;
   - suspicious path warnings;
   - explicit approval before applying isolated diffs to the base repo.
10. Add trace metadata:
   - sandbox provider;
   - image;
   - network mode;
   - source root;
   - state root;
   - resource limits;
   - env policy summary;
   - apply-back status.

### Impact

- Agent-triggered commands lose direct host authority.
- Provider credentials and host secrets stay with the harness, not inside the
  agent execution environment.
- Worktree isolation becomes a real security boundary when paired with a
  container or OS sandbox.
- Future remote-control and broader command workflows have a defensible trust
  model.

### Acceptance Criteria

- `adapters.command.default.provider: docker` runs agent commands inside a
  container-mounted isolated workspace.
- Agent commands cannot read files outside `/workspace`.
- Provider API keys and host secret variables are absent inside the sandbox.
- Network is disabled by default and recorded in trace metadata.
- CPU, memory, process, and timeout limits are enforced or explicitly reported
  as unsupported on the host platform.
- File tools mutate only the isolated source root in sandbox mode.
- Applying changes back to the base repo requires an explicit apply-back step.
- Tests cover command construction, cwd containment, env stripping, timeout,
  nonzero exit capture, state-root separation, and apply-back review.

## Phase 5 - Approval UX And Narrow Session Patterns

### Objective

Keep exact-call approvals as the safe default while making approval review less
clunky. Add session-pattern approvals only when the UI can display the exact
scope clearly and enforcement revalidates every call.

### Current State

- Permission policy supports `allow`, `ask`, and `deny`.
- `ask` creates durable exact-call approval requests.
- Approval detail includes tool, normalized argument hash, argument preview, matched rule, reason, run id, and expiry.
- Retrying an approved exact call can execute once.
- Pattern approvals and automatic replay are intentionally absent.

### Implementation Details

1. Improve exact-call review first:
   - better `/approval detail` formatting;
   - grouped pending approvals by run id;
   - trace links for approval request/resolution events;
   - explicit expiry display.
2. Add narrow session-pattern approval model:
   - command prefix;
   - path glob;
   - tool name;
   - expiry;
   - reason;
   - created-by run/session;
   - display string shown before approval.
3. Revalidate every approved call against:
   - hard-deny secret checks;
   - workspace containment;
   - active permission mode;
   - command policy;
   - direct shell restrictions.
4. Add automatic replay only for transports that can prove the replayed call is
   byte-for-byte identical or matches a displayed session pattern.
5. Add audit events:
   - `approval.pattern_requested`;
   - `approval.pattern_resolved`;
   - `approval.pattern_matched`;
   - `approval.pattern_expired`.

### Impact

- Users spend less time approving repeated safe operations.
- Dangerous scope expansion remains visible and auditable.
- Remote/gateway work can later reuse the same approval model without trusting prompt text.

### Acceptance Criteria

- Exact-call approvals remain the default behavior.
- Pattern approvals cannot bypass hard-deny or mode-deny checks.
- The approved pattern is rendered before approval and in later audit output.
- Tests cover allowed, denied, expired, and mismatched pattern calls.

## Phase 6 - Target-Aware Safety Tuning

### Objective

Improve mutation safety so relevant exploration unlocks edits, irrelevant
exploration does not, and legitimate generated-file/new-file workflows are not
blocked unnecessarily.

### Current State

- `SafetyState` records exploration evidence.
- Mutation tools require relevant read/search/status/diff evidence.
- Filesystem mutation schemas accept optional reasons.
- Relevance remains heuristic.

### Implementation Details

1. Add actionable denial messages that name missing evidence:
   - git status;
   - target read;
   - parent directory listing;
   - relevant search;
   - verification command.
2. Add generated-file handling:
   - parent directory evidence;
   - generator/source evidence where available;
   - explicit mutation reason for generated outputs.
3. Add large-repo exploration scoring:
   - target read;
   - parent listing;
   - symbol search;
   - related call sites;
   - tests inspected.
4. Feed safety outcomes into eval dimensions:
   - false unlock;
   - false block;
   - missing evidence;
   - generated-file exception.
5. Keep prompt instructions secondary. Enforcement belongs in middleware.

### Impact

- Fewer accidental edits based on superficial repo exploration.
- Fewer operator interruptions for legitimate new-file or generated-file work.
- Safety rules become explainable and measurable.

### Acceptance Criteria

- Denied mutations explain exactly what evidence is missing.
- Eval fixtures cover unrelated search, target read, new file, generated file, and large-repo cases.
- Tightening safety rules must not lower eval score without an accepted rationale.

## OpenCode-Comparable Harness Workstreams

These workstreams address the practical agentic-coding harness gaps identified
by comparing SmolClaw with mature terminal-first coding tools such as OpenCode.
They should be implemented without weakening the architectural rules in
[system-design-spec.md](system-design-spec.md): explicit dependency seams,
workspace containment, middleware enforcement, deterministic tests, and local
reliability first.

## Phase 7 - Plan And Build Mode UX

### Objective

Make planning and mutation distinct first-class interaction modes. Users should
be able to ask for analysis and implementation plans without risking file edits
or command execution, then intentionally switch into a build-capable mode.

### Current State

- SmolClaw has agent configs, permission modes, goal ledgers, and subagents.
- Plan-like behavior can be approximated through restricted agents or prompts.
- There is not yet a polished primary-mode UX equivalent to a visible
  plan/build toggle.

### Implementation Details

1. Define two built-in primary modes:
   - `plan`: read/search/status/diff/web/memory allowed; file mutation and command execution ask or deny by default;
   - `build`: normal coding permissions subject to policy, safety, approvals, and checkpoints.
2. Add mode state to CLI/TUI session state:
   - visible mode indicator;
   - slash commands such as `/mode plan`, `/mode build`;
   - optional keybinding in TUI.
3. Keep permission enforcement structural:
   - mode changes update agent/tool projection and permission baseline;
   - plan mode cannot bypass hard-deny or safety middleware;
   - build mode still requires exploration evidence before mutation.
4. Make plan output actionable:
   - plan summaries can be promoted into goal acceptance criteria;
   - selected plan steps can seed the lightweight todo tool;
   - final plan response should include risks, likely files, and verification path.
5. Add tests for mode transitions, denied plan-mode mutations, and build-mode checkpoint behavior.

### Impact

- Users can safely ask for design analysis before implementation.
- Accidental edits during planning become structurally impossible.
- Goal runs can start from a reviewed plan instead of model self-continuation.

### Acceptance Criteria

- Plan mode visibly disables or asks for all mutations and command execution.
- Switching to build mode preserves conversation context and planned tasks.
- Tests prove a model cannot mutate files in plan mode through direct or deferred tools.
- TUI and CLI show the active mode consistently.

## Phase 8 - LSP Code Intelligence

### Objective

Add language-server-backed code intelligence so agents can localize symbols,
references, definitions, diagnostics, and call hierarchies without relying only
on grep/read/list operations.

### Current State

- SmolClaw has file read/search/find tools and target-aware safety evidence.
- There is no first-class LSP client/tool surface.
- Refactor and large-repo tasks depend heavily on text search and model judgment.

### Implementation Details

1. Add an LSP service boundary:
   - `LspClient` protocol;
   - `LspServerManager` for per-workspace server lifecycle;
   - factory injection for tests.
2. Support core operations first:
   - `document_symbols`;
   - `workspace_symbols`;
   - `go_to_definition`;
   - `find_references`;
   - `hover`;
   - `diagnostics`;
   - later: call hierarchy and implementation lookup.
3. Add tool schemas that return compact, path-safe results:
   - symbol names;
   - file paths;
   - ranges;
   - diagnostic severity/message;
   - previews capped and redacted.
4. Integrate with safety/evidence:
   - LSP references and definitions count as structured exploration evidence;
   - diagnostics can count as verification evidence only when explicitly requested.
5. Add server discovery:
   - project-local config first;
   - conservative built-in defaults for common Python/TypeScript repos;
   - no auto-install until diagnostics and approval UX are stronger.
6. Add faked LSP tests and one fixture-backed integration test where available.

### Impact

- Better code localization for large repos.
- Safer refactors because references and definitions are structured evidence.
- Less context waste from broad grep output.

### Acceptance Criteria

- LSP tools are optional and fail gracefully when no server is configured.
- Results are workspace-contained and redacted.
- Safety middleware can treat LSP definition/reference output as relevant evidence.
- Tests cover missing server, successful symbol lookup, path containment, and diagnostics rendering.

## Phase 9 - Lightweight Todo Planning Tool

### Objective

Provide a small in-session todo tool for ordinary coding tasks. Goal ledgers are
durable and evidence-heavy; the todo tool should be lightweight, visible, and
cheap for the model to update during normal chat/build work.

### Current State

- Goal ledgers track durable objectives, criteria, evidence, changed files, and verification.
- There is no lightweight per-turn task list comparable to a coding-session todo.
- Agents may overuse goal tools for small tasks or keep plans only in prose.

### Implementation Details

1. Add `TodoStore` under session state:
   - in-memory for transient chat;
   - persisted in session metadata where useful;
   - optionally linked to active goal ledger.
2. Add tools:
   - `todo_write(items)`;
   - `todo_update(id, status, note=None)`;
   - `todo_status()`;
   - `todo_clear(completed=False)`.
3. Define item states:
   - `pending`;
   - `in_progress`;
   - `blocked`;
   - `done`;
   - `dropped`.
4. Integrate with UI:
   - compact TUI panel or status drawer;
   - `/todo` command;
   - final response can summarize unfinished items.
5. Bridge to goal ledgers:
   - plan mode can create todos;
   - goal acceptance criteria remain durable and evidence-backed;
   - completed todos do not imply goal completion unless ledger criteria are satisfied.

### Impact

- Better transparency for multi-step edits.
- Less context drift during ordinary tasks.
- Cleaner separation between lightweight progress and durable completion evidence.

### Acceptance Criteria

- Todo updates are visible in CLI/TUI and trace summaries.
- Subagents cannot mutate parent todos unless explicitly allowed.
- Goal completion still requires ledger criteria and verification evidence.
- Tests cover todo persistence, rendering, and goal-ledger separation.

## Phase 10 - Redo And Conversation Rewind

### Objective

Extend `/undo` into a fuller recovery loop. Users should be able to undo bad
agent changes, inspect the prompt/run that produced them, revise the request,
and optionally redo a reverted checkpoint where no conflicts exist.

### Current State

- File mutation checkpoints and `/undo` exist.
- Undo restores the last SmolClaw change when safe.
- Redo and conversation rewind are not first-class workflows.

### Implementation Details

1. Extend checkpoint records:
   - before hash;
   - after hash;
   - prompt/run id;
   - related trace id;
   - ledger evidence id;
   - redo applicability.
2. Add `/redo`:
   - reapply the latest undone checkpoint if target files still match the expected before/undo state;
   - refuse on conflict with actionable diagnostics.
3. Add `/rewind`:
   - show candidate run/checkpoint history;
   - restore code only initially;
   - later consider conversation-state rewind.
4. Link trace replay:
   - show the user prompt and tool summary associated with the checkpoint;
   - allow "retry from here" as a future mode.
5. Add tests for undo/redo conflict handling and trace/checkpoint linkage.

### Impact

- Users can recover faster from unwanted edits.
- Bad agent runs become learning opportunities rather than dead ends.
- Checkpoint metadata becomes more valuable for eval and UX.

### Acceptance Criteria

- `/redo` replays a reverted checkpoint only when hashes match.
- `/rewind` lists checkpoint/run candidates with changed files and prompt summaries.
- Conflict messages identify exactly which files changed.
- Tests cover edit, create, delete, conflict, and no-op cases.

## Phase 11 - Subagent Navigation And Session UX

### Objective

Make subagent work visible, inspectable, and easy to navigate. SmolClaw has
subagents and orchestration, but delegated work should feel like a first-class
session workflow instead of hidden background activity.

### Current State

- `ChildAgentFactory`, `SubagentManager`, orchestration tools, and agent configs exist.
- Child sessions derive traceable session keys.
- UI affordances for parent/child navigation and subagent result inspection are limited.

### Implementation Details

1. Add subagent run views:
   - active subagents;
   - status;
   - purpose;
   - started/ended timestamps;
   - trace path;
   - parent session key.
2. Add commands:
   - `/agents`;
   - `/agent status <id>`;
   - `/agent trace <id>`;
   - `/agent result <id>`;
   - `/agent cancel <id>`.
3. Improve TUI:
   - subagent drawer;
   - parent/child breadcrumbs;
   - result summaries linked to traces.
4. Add permission clarity:
   - display subagent mode/capabilities;
   - deny hidden escalation from read-only subagents to mutating tools.
5. Add eval fixtures for explorer/reviewer subagent workflows.

### Impact

- Delegation becomes understandable and auditable.
- Users can tell whether a subagent is still running or blocked.
- Multi-agent work becomes safer because capabilities and outputs are visible.

### Acceptance Criteria

- CLI and TUI can list active and completed subagents.
- Subagent traces are discoverable from the parent run.
- Read-only subagents cannot mutate files even through deferred tools.
- Tests cover spawn, status, result, trace, cancel, and permission-denied paths.

## Phase 12 - Custom Tools And Plugin Surface

### Objective

Expose a controlled extension system so users can add project-specific tools and
hooks without modifying core SmolClaw code. This should build on existing
dependency seams and permission middleware, not bypass them.

### Current State

- SmolClaw has internal tool registration, MCP wrappers, hook runners, and dependency injection.
- There is no supported user-facing plugin directory or custom tool manifest.
- Adding integrations currently requires changing Python code.

### Implementation Details

1. Define plugin scope:
   - local project plugins under `.smolclaw/plugins/` or a clearly named config path;
   - optional user-level plugins later;
   - disabled by default until policy is in place.
2. Define a manifest:
   - plugin id;
   - version;
   - tool names;
   - permissions/effects;
   - command/runtime requirements;
   - trusted/untrusted flag;
   - entrypoint.
3. Start with safe extension points:
   - hook-only plugins;
   - read-only tools;
   - MCP server registration helpers.
4. Require permission policy integration:
   - plugin tools must declare effects;
   - mutating tools go through policy, safety, evidence, checkpoints, and traces;
   - plugin load events are diagnosed and traceable.
5. Add tests:
   - manifest validation;
   - disabled plugin;
   - read-only plugin tool;
   - denied mutating plugin tool;
   - malformed plugin failure.

### Impact

- Users can tailor SmolClaw to local workflows without forking.
- Core runtime remains stable while integrations grow.
- Plugin capability becomes auditable and policy-controlled.

### Acceptance Criteria

- No plugin can register a mutating tool without declared effects and permission enforcement.
- Plugin load failures are visible and non-fatal by default.
- Tests prove plugin tools use the same middleware chain as built-in tools.

## Phase 13 - IDE Integration And File References

### Objective

Add IDE-adjacent workflow support while keeping terminal-first behavior. The
first milestone should not require a full extension; it should make file
references, selected ranges, and editor handoff practical.

### Current State

- SmolClaw runs as a terminal application.
- File paths can be mentioned in plain text, and tools can read files.
- There is no structured file reference syntax or editor-selection bridge.

### Implementation Details

1. Add file reference parsing:
   - `@path/to/file`;
   - `@path/to/file:line`;
   - `@path/to/file:start-end`;
   - reject paths outside workspace.
2. Add prompt enrichment:
   - resolve references before model call;
   - include compact snippets with file/range metadata;
   - record referenced files as exploration evidence where appropriate.
3. Add editor commands:
   - `/editor <path[:line]>`;
   - `/export` or equivalent for opening trace/session artifacts;
   - respect `EDITOR`.
4. Add optional IDE extension later:
   - launch/focus terminal session;
   - send selected range to SmolClaw;
   - insert file references;
   - display trace/checkpoint links.
5. Add tests for parsing, containment, prompt enrichment, and editor command building.

### Impact

- Users can provide precise context without copying file contents.
- Agents waste fewer turns locating files.
- A later IDE extension has stable CLI primitives to call.

### Acceptance Criteria

- File references resolve only inside the active source root.
- Prompt enrichment caps snippet size and redacts secret-like values.
- Referenced files are visible in trace/evidence output.
- Editor commands are testable through injected runners.

## Phase 14 - Sharing, Export, And Collaboration

### Objective

Make local run artifacts easier to share without compromising privacy. SmolClaw
should first support local export bundles; remote/public sharing should wait for
explicit policy and redaction controls.

### Current State

- Runs have trace JSONL, summaries, ledgers, diagnostics, checkpoints, and eval reports.
- There is no polished share/export command for a conversation or run bundle.
- Gateway exists but is not the primary collaboration surface.

### Implementation Details

1. Add local export bundles:
   - transcript summary;
   - trace summary;
   - ledger summary;
   - changed files list;
   - verification commands;
   - redaction report;
   - optional diff.
2. Add commands:
   - `/export run`;
   - `/export session`;
   - `/export goal`;
   - `smolclaw export --run <id>`.
3. Redaction first:
   - secret-looking values;
   - `.env` paths;
   - large file content;
   - command output caps;
   - explicit warning for raw export.
4. Add optional remote sharing later:
   - disabled by default;
   - explicit provider/config;
   - privacy warning;
   - revocation/unshare mechanism if supported.
5. Add tests for redaction, bundle contents, missing artifacts, and raw-export gating.

### Impact

- Users can attach a run report to issues/PRs without manually collecting artifacts.
- Support and debugging become easier.
- Privacy posture remains local-first.

### Acceptance Criteria

- Local export produces a deterministic bundle with redacted content by default.
- Raw export requires explicit flag and warning.
- Tests prove secret-like values are redacted from exported artifacts.

## Phase 15 - Daily-Driver UX Polish

### Objective

Reduce friction for regular use. This phase is not visual polish for its own
sake; it is about making the terminal coding loop efficient enough for daily
work.

### Current State

- TUI exists with status handling and command support.
- Model switching, goals, approvals, traces, undo, worktree commands, and memory export are available.
- The UX is still more harness-like than product-like.

### Implementation Details

1. Command discoverability:
   - searchable `/help`;
   - grouped commands;
   - command argument hints;
   - recent commands.
2. Keybindings:
   - mode switch;
   - trace drawer;
   - approval drawer;
   - worktree diff;
   - interrupt/cancel;
   - configurable mapping later.
3. Visual state:
   - current mode;
   - model/provider;
   - permission mode;
   - workspace/worktree status;
   - active goal/todo;
   - pending approvals.
4. Formatting:
   - consistent tool output folding;
   - bounded command output previews;
   - clearer error blocks;
   - final response template with changed files/tests/run status.
5. Documentation:
   - install smoke;
   - daily workflow guide;
   - troubleshooting guide;
   - permission examples.

### Impact

- More reliable day-to-day use.
- Fewer support questions caused by hidden state.
- Better onboarding for contributors and users.

### Acceptance Criteria

- `/help` covers all user-facing commands with examples.
- TUI status always shows mode, model/provider, workspace, and pending approval count.
- Long tool output cannot corrupt or hide the prompt area.
- Docs include a daily local coding workflow from init through undo/export.

## Phase 16 - Agentic Coding Harness Parity Evals

### Objective

Add evals specifically for the OpenCode-comparable gaps so product-workflow
features are tested as harness behavior, not just UI commands.

### Current State

- Agent evals and memory evals exist.
- Existing roadmap eval needs focus on plan/build, LSP, todo, approvals,
  subagents, rewind, and export workflows.

### Implementation Details

1. Add deterministic fixtures:
   - plan mode must not edit;
   - build mode edits after reviewed plan;
   - LSP definition/reference localizes the right target;
   - todo list tracks a multi-step refactor;
   - approval pattern allows safe repeated command only;
   - subagent explorer returns read-only findings;
   - undo/redo restores and reapplies a checkpoint;
   - export bundle redacts secrets.
2. Score workflow dimensions:
   - mode safety;
   - code localization;
   - progress tracking;
   - approval scope;
   - recovery;
   - collaboration/export safety.
3. Include traces and ledgers in recorded artifacts.
4. Keep live runs opt-in.

### Impact

- Product UX work becomes regression-tested.
- SmolClaw can improve toward practical daily-driver parity without sacrificing safety.
- The roadmap remains evidence-driven.

### Acceptance Criteria

- Every new harness-product workstream has at least one deterministic eval fixture before being marked complete.
- Eval reports identify which parity dimension regressed.
- CI can run the deterministic subset without provider credentials.

## Phase 17 - State Schema Versions And Migrations

### Objective

Make durable state contracts explicit. Some stores already have schema versions
or tolerant readers; the cleanup is to standardize migration behavior before
state becomes harder to evolve.

### Current State

- Work-loop items carry schema versions and migrate legacy Jira fields.
- Goal ledgers, traces, approvals, checkpoints, sessions, usage, and diagnostics are mostly tolerant readers or append-only formats.
- Atomic writes exist for important JSON/text state.

### Implementation Details

1. Inventory every durable state file under `.smolclaw/`:
   - sessions;
   - traces;
   - trace summaries;
   - ledgers;
   - approvals;
   - checkpoints;
   - usage;
   - eval reports;
   - work-loop items;
   - memory docs;
   - SQLite schema-backed stores.
2. Add schema version constants where missing.
3. Add per-store migration functions:
   - load legacy;
   - normalize to current dataclass/dict;
   - write current schema on next save where safe.
4. Add corruption behavior:
   - recover backup where supported;
   - fail with actionable error where recovery is unsafe;
   - keep append-only trace tolerance for trailing malformed lines.
5. Add tests for legacy fixtures and adversarial state keys.

### Impact

- Upgrades become safer.
- Eval artifacts and user state remain readable across refactors.
- Developers get one pattern for adding new stores.

### Acceptance Criteria

- Every JSON state store has a documented schema version or a documented reason it is append-only/unversioned.
- Legacy fixture tests exist for stores with migration behavior.
- State path containment tests cover user-controlled identifiers.

## Phase 18 - Runtime Shared-State Narrowing

### Objective

Reduce reliance on public mutable shared-state dictionaries while preserving the
existing tool boundary. `RuntimeSharedState` should become the normal contract
inside runtime code; raw dict access should be restricted to compatibility
edges.

### Current State

- `RuntimeSharedState` provides typed accessors for trace recorder, session key,
  approval store, checkpoint store, safety state, active tool ids, and approved
  command bypass.
- The underlying wire format remains a dict for tool compatibility.
- Some code still reads and writes string keys directly.

### Implementation Details

1. Inventory direct shared-state key access.
2. Move stable keys to constants and typed properties.
3. Add helper methods for common scoped state:
   - active tool call;
   - approval bypass;
   - active trace recorder;
   - active ledger/store references if needed.
4. Make middleware fail softly at runtime when optional state is absent.
5. Make tests fail loudly for malformed required state.
6. Update docs to identify public shared-state keys.

### Impact

- Runtime contracts become easier to review.
- Tool and middleware changes are less likely to collide on string keys.
- Future provider work can reuse stable accessors.

### Acceptance Criteria

- Direct string-key reads are limited to `RuntimeSharedState`, tool compatibility helpers, or explicitly documented extension points.
- Tests cover missing and malformed shared-state cases.

## Phase 19 - Adapter Diagnostics

### Objective

Make runtime adapter selection and degraded behavior visible. The adapter config
is respected, but users and developers need clearer diagnostics when a provider
is unsupported, missing credentials, falling back, or using legacy env overrides.

### Current State

- Runtime adapter config loads from explicit, user, and workspace config files.
- Unsupported command/task/review providers fail fast.
- LLM and embedding providers support factory/client injection.
- Memory still honors legacy model environment variables.

### Implementation Details

1. Add an adapter-resolution diagnostic view:
   - selected provider;
   - selected model;
   - source of selection;
   - config file path;
   - CLI/session override;
   - legacy env override.
2. Add CLI commands or doctor output for:
   - active adapter config;
   - missing provider credentials;
   - unsupported provider values;
   - memory embedding dimensions.
3. Emit structured diagnostics for degraded paths:
   - missing memory provider;
   - unsupported embedding provider;
   - fallback to default model;
   - unavailable external CLI.
4. Add tests with injected configs and fake environments.

### Impact

- Configuration support becomes easier.
- Users can see why a model/provider was selected.
- Provider additions become less risky because each adapter must report its resolution path.

### Acceptance Criteria

- `doctor` or an equivalent command reports active adapter selections without exposing secrets.
- Unsupported provider diagnostics name the provider, scope, and supported values.
- Tests prove CLI flags override YAML and YAML overrides defaults.

## Phase 20 - Provider Maturity

### Objective

Expand provider breadth after contracts are stable. This is intentionally later
than local reliability work because new providers multiply test and support
surface.

### Current State

- Command provider registry supports `subprocess` only.
- Work-loop task/review providers are Jira and GitHub.
- Gateway and MCP code paths are dependency-injected but secondary.

### Implementation Details

1. Define a command-provider acceptance contract:
   - workspace cwd containment;
   - timeout behavior;
   - stdout/stderr capture;
   - cancellation;
   - environment policy;
   - process group behavior if applicable;
   - sandbox boundary.
2. Add additional command providers only after the Docker/Podman sandbox MVP
   establishes the provider contract:
   - macOS sandbox;
   - remote executor;
   - container variants;
   - other explicit backends.
3. Define work-loop provider interfaces beyond Jira/GitHub:
   - task source;
   - review source;
   - lifecycle transitions;
   - metadata mapping;
   - provider-neutral persistence.
4. Add conformance tests that each provider must pass.

### Impact

- SmolClaw becomes deployable in more environments without rewriting core runtime.
- Provider additions remain testable and observable.
- The sandbox contract becomes reusable across multiple execution backends.

### Acceptance Criteria

- New command providers pass the same timeout, output, cwd, env, cancellation, and policy tests.
- New work-loop providers do not add provider-specific fields to neutral persisted state.
- Unsupported providers continue to fail fast at startup/config resolution.

## Phase 21 - Async Streaming And MCP Edit Atomicity

### Objective

Address lower-priority correctness and responsiveness risks after the core local
workflow is hardened.

### Current State

- Non-streaming provider calls are async-compatible through worker-thread wrapping.
- Some streaming SDK iterators are synchronous.
- MCP edit is read/replace/write and can race with external edits.

### Implementation Details

1. Replace synchronous streaming iteration where clients expose async streams.
2. For sync-only SDK streams, move iteration into a worker boundary with backpressure.
3. Add TUI responsiveness tests for streaming output.
4. Design transactional MCP edit support:
   - expected hash/version;
   - reject on conflict;
   - return conflict details;
   - preserve current simple edit path as fallback where remote does not support transactions.
5. Add gateway-supported edit operations if needed.

### Impact

- TUI remains responsive during long streaming responses.
- Remote/MCP edits become safer under concurrent modification.
- Gateway work has stronger correctness contracts.

### Acceptance Criteria

- Streaming paths do not block the event loop in measured tests.
- MCP transactional edit rejects stale writes when expected content hash/version mismatches.
- Existing MCP edit behavior remains backward compatible where transactions are unavailable.

## Sequencing Dependencies

1. Shared run presentation should land before broad eval expansion so reports
   use stable fields.
2. Eval fixtures should land before tightening safety rules so false positives
   and false negatives are measurable.
3. Worktree dirty-copy hardening should land before the real sandbox MVP because
   sandbox mode should always operate on an isolated source root.
4. The real sandbox backend should land before remote-origin work, broader
   command authority, or unattended long-running autonomy.
5. Approval UX improvements should land before pattern approvals or automatic replay.
6. Plan/build mode should land before richer daily-driver UX so mutation
   authority is visible throughout the interface.
7. LSP code intelligence should land before tightening large-repo exploration
   scoring so structured symbol evidence can participate in safety decisions.
8. Todo planning should land before broader subagent navigation so delegated work
   can report progress into a shared task surface.
9. Redo/rewind should land before export/share workflows so exported recovery
   context is accurate.
10. Plugin/custom-tool support should wait until permission effects, diagnostics,
   and middleware conformance tests are explicit.
11. IDE integration should start with file-reference parsing and editor commands
   before a full extension.
12. State schema versions should land before major persistent-state refactors.
13. Provider maturity should wait until adapter diagnostics, sandbox semantics,
   and conformance tests are in place.

## Cross-Cutting Test Requirements

- Keep the no-patch dependency-substitution scan clean.
- Add fakes through constructors, factories, dependency containers, or context managers.
- Run targeted tests for each touched subsystem.
- Run full `pytest` before merging broad architecture or state changes.
- Run `git diff --check`.
- For roadmap-impacting changes, update this file and
  [system-design-spec.md](system-design-spec.md) together.

## Impact Summary

The near-term roadmap improves trust: users can inspect what happened, plan
without accidental mutation, run agent commands in a real sandbox, undo or
review risky changes, and see why a run stopped. The product-parity roadmap
improves daily coding usefulness: LSP-backed localization, todo tracking,
redo/rewind, subagent navigation, custom tools, IDE references, and safe
export/sharing. The mid-term roadmap improves maintainability: state schemas,
shared-state contracts, diagnostics, and evals make large changes safer. The
longer-term roadmap improves capability breadth: additional command providers,
work-loop providers, async streaming, and transactional MCP edits become
practical once the core contracts are stable.
