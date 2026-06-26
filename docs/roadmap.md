# SmolClaw Roadmap

Status: current implementation roadmap
Last reviewed: 2026-06-26

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
| P1 | Approval UX improvements | Safer side effects with less operator friction | Overbroad or confusing approvals |
| P1 | Target-aware safety tuning | Fewer unsafe edits and fewer false blocks | Irrelevant exploration unlocking mutation |
| P2 | State schema migrations | More durable long-term state contracts | Silent incompatibility across versions |
| P2 | Runtime shared-state narrowing | Clearer internal contracts | Dict key drift and accidental collisions |
| P2 | Adapter diagnostics | Easier support/debugging | Hidden degraded provider behavior |
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
- Eval scoring checks trace/ledger integrity and can report failure classes and score deltas.
- Existing fixtures are thin and do not cover enough real workflow diversity.
- Memory evals have deterministic fixture and docs suites.

### Implementation Details

1. Add coding-agent fixtures:
   - multi-file bugfix;
   - documentation-only change;
   - blocked secret read;
   - approval-required command;
   - dirty-worktree preservation;
   - generated-file edit;
   - large-repo exploration;
   - TUI/trace rendering.
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
- Dirty-copy behavior is explicit but not fully productized.

### Implementation Details

1. Add pre-copy analysis:
   - file count;
   - total bytes;
   - ignored-root detection;
   - known cache/build directory detection;
   - secret-path warnings;
   - large binary detection.
2. Add configurable thresholds with safe defaults.
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
   - require explicit confirmation for broad apply-back;
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
- Trace/eval summaries show isolation metadata.
- Apply-back review lists risk indicators before applying broad diffs.
- Tests prove state writes stay under the original workspace state root for every worktree entrypoint.

## Phase 4 - Approval UX And Narrow Session Patterns

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

## Phase 5 - Target-Aware Safety Tuning

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

## Phase 6 - State Schema Versions And Migrations

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

## Phase 7 - Runtime Shared-State Narrowing

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

## Phase 8 - Adapter Diagnostics

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

## Phase 9 - Provider Maturity

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
2. Add one sandboxed command provider only after policy review:
   - Docker;
   - macOS sandbox;
   - remote executor;
   - other explicit backend.
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
- Sandbox-backed commands can eventually unlock broader command authority safely.

### Acceptance Criteria

- New command providers pass the same timeout, output, cwd, env, cancellation, and policy tests.
- New work-loop providers do not add provider-specific fields to neutral persisted state.
- Unsupported providers continue to fail fast at startup/config resolution.

## Phase 10 - Async Streaming And MCP Edit Atomicity

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
3. Worktree dirty-copy hardening should land before remote-origin or long-running
   autonomy work.
4. Approval UX improvements should land before pattern approvals or automatic replay.
5. State schema versions should land before major persistent-state refactors.
6. Provider maturity should wait until adapter diagnostics and conformance tests
   are in place.

## Cross-Cutting Test Requirements

- Keep the no-patch dependency-substitution scan clean.
- Add fakes through constructors, factories, dependency containers, or context managers.
- Run targeted tests for each touched subsystem.
- Run full `pytest` before merging broad architecture or state changes.
- Run `git diff --check`.
- For roadmap-impacting changes, update this file and
  [system-design-spec.md](system-design-spec.md) together.

## Impact Summary

The near-term roadmap improves trust: users can inspect what happened, undo or
review risky changes, and see why a run stopped. The mid-term roadmap improves
maintainability: state schemas, shared-state contracts, diagnostics, and evals
make large changes safer. The longer-term roadmap improves capability breadth:
additional command providers, work-loop providers, async streaming, and
transactional MCP edits become practical once the core contracts are stable.
