# SmolClaw Reliability Roadmap

This roadmap turns the current SmolClaw codebase into a more reliable harness-style coding assistant while preserving the project's useful small-core shape.

It is based on the local implementation as of June 2026 and on the evidence collected in [research-agentic-coding-harnesses.md](research-agentic-coding-harnesses.md).

## Goal

SmolClaw should become a dependable local coding assistant that can:

- start in the current working directory with `smolclaw`;
- understand a codebase before editing it;
- run bounded agentic loops toward explicit goals;
- expose progress without corrupting the terminal UI;
- safely read, edit, test, and explain code changes;
- support subagents without losing the main conversation;
- recover from mistakes through checkpoints and undo;
- provide enough traces and evals to tell whether reliability is improving.

The product direction is closer to a focused local coding harness than a broad always-on personal assistant. OpenClaw is useful as a reference for gateway, channel, sandboxing, and queue design, but SmolClaw should not copy its full product scope unless remote assistant control becomes a first-class goal.

## Current Baseline

### Working

- Single CLI entry point: `smolclaw`.
- Shared runtime assembly for CLI and gateway paths.
- Agent configs with capabilities, tool projection, and per-agent prompts.
- Memory-backed context assembly and persistent session storage.
- Tool middleware for logging, retries, timeouts, tracing, and hooks.
- Workspace-owned path resolution for filesystem tools.
- Safe state path helpers for user-controlled session, goal, usage, and checkpoint keys.
- Narrow command tools instead of open local shell access.
- Coding tools: file read/write/edit/list/find/grep/apply_patch, git status/diff, constrained command execution.
- Safety gate before mutation requiring status/search/read evidence.
- Permission modes for agent tool access, with v1 hard-deny checks for `.env*` secrets and external workspace paths.
- Repeated identical tool call guard.
- Atomic patch application with rollback tests.
- Mutation checkpoints and `/undo` for session-scoped file restoration.
- OpenAI Responses API routing for reasoning tool turns on supported models.
- Goal persistence, `/goal run`, and agent-started goals.
- TUI with status bar, spinner/status state, and bounded shutdown improvements.
- Large pytest suite covering the harness internals.

### Not Reliable Enough Yet

- The safety gate proves exploration happened, not that exploration was sufficient or relevant.
- Permission policy is still a v1 hard-deny model, not a configurable `ask` approval system.
- TUI output streams are much better isolated, but trace export and richer log-drawer workflows remain incomplete.
- The agent loop does not yet have a structured task ledger with acceptance criteria, verification state, and blockers.
- Evals mostly prove code paths, not full agent behavior on realistic coding tasks.
- There is no sandbox or worktree-backed isolation mode for risky edits or remote-control scenarios.
- Documentation has been narrowed to the current local coding-harness direction, but it still needs ongoing install, packaging, and operator guide improvements.

## Design Principles

1. Keep the core loop simple.
   - mini-SWE-agent is a strong reminder that simple linear histories, independent commands, and inspectable trajectories can outperform elaborate scaffolds.

2. Make safety structural, not only prompt-based.
   - Prompt instructions are useful, but mutation safety, path boundaries, permissions, and approval policy must be enforced in code.

3. Make agent work observable.
   - A run should be replayable enough to answer: what did the agent know, why did it edit, what changed, what verified it, and why did it stop?

4. Separate streams.
   - User transcript, assistant response, tool activity, reasoning summaries, telemetry, errors, and TUI status are different surfaces.

5. Prefer one strong general coding agent before complex multi-agent orchestration.
   - Add subagents where they reduce context pollution or provide independent review, not as a default answer to every task.

6. Use evals to justify complexity.
   - Every new safety or orchestration feature should have a regression test or agent task showing what reliability gap it closes.

## References And Lessons

The supporting research is tracked in [docs/research-agentic-coding-harnesses.md](research-agentic-coding-harnesses.md). The short version:

- OpenCode validates the near-term product shape: terminal-first coding, plan/build separation, role-specific agents, granular permissions, and undo.
- OpenClaw is the right reference for later gateway work: typed protocol frames, pairing, session lanes, stream events, idempotency, sandboxing, and untrusted-content handling.
- Anthropic, OpenAI, SWE-agent, SWE-bench, SWE-Adept, SeaView, ReAct, and recent guardrail research all point toward simple observable loops, strong tool interfaces, structural safety, checkpoints, traces, and evals.

## Roadmap Overview

### Phase 0 - Stabilize The Current Product

Purpose: make the installed `smolclaw` trustworthy enough for daily local use.

Success criteria:

- `/model` settings match actual model API behavior.
- Storage paths cannot escape the workspace or state directory.
- TUI cannot be corrupted by long output, exceptions, or shutdown.
- Package metadata and docs consistently expose `smolclaw` as the only user-facing coding entry point.
- Full test suite and package validation run cleanly in the development environment.

### Phase 1 - Make Safety And Permissions Structural

Purpose: move from coarse mutation gates to enforceable permissions and reviewable write operations.

Success criteria:

- Every tool call is checked against a permission policy.
- Mutation tools create checkpoints before changing files.
- User can undo agent-created changes.
- External directory access and secret files are explicitly gated.
- Repeated identical tool calls trigger a loop guard.

### Phase 2 - Improve Agent Work Quality

Purpose: make the agent consistently explore, plan, implement, verify, and stop.

Success criteria:

- Goal runs create a structured task ledger.
- Mutations require relevant exploration evidence.
- Agent records acceptance criteria and verification commands.
- Failed tests lead to bounded retries or a clear blocker.
- Subagents can investigate or review without polluting main context.

### Phase 3 - Build A Real Evaluation Harness

Purpose: measure agent reliability rather than relying on anecdotes.

Success criteria:

- There is a local suite of realistic coding tasks.
- Each task runs in an isolated workspace or worktree.
- The harness records trajectories, diffs, test results, and stop reasons.
- Regressions fail CI or produce an explicit score delta.
- The suite includes safety, TUI, and shutdown scenarios.

### Phase 4 - Add Isolation And Remote-Control Readiness

Purpose: prepare for Telegram, Signal, WebSocket, or background assistant control without giving remote text raw host authority.

Success criteria:

- Risky or remote-origin work runs in a sandbox or isolated worktree.
- Remote callers are paired/authorized and scoped.
- Side-effecting requests have idempotency keys.
- Channel input is treated as untrusted and cannot silently broaden permissions.
- Gateway events expose progress, cancellation, and final status.

### Phase 5 - Mature The Assistant Experience

Purpose: improve long-running use, multi-session work, and operator confidence.

Success criteria:

- Runs can be resumed, inspected, compacted, and replayed.
- Context compaction preserves modified files, tests run, decisions, and blockers.
- Subagent model policy is configurable and visible.
- TUI has a stable transcript, scrollback, log drawer, status bar, and trace export.
- Documentation matches shipped behavior.

## Detailed Workstreams

## 1. Model And LLM Runtime

### Problems

- `gpt-5.5` with `reasoning_effort` and tools is not supported through the current Chat Completions tool path.
- The UI can report `effort: high` even when the actual tool turn cannot use that parameter.
- Provider/model capabilities are implicit rather than encoded in a durable model registry.

### Work

1. Add a model capability registry.
   - Track provider, endpoint family, supports tools, supports reasoning effort, supports streaming, supports structured output, max context, and default effort.

2. Add OpenAI Responses API support for tool-using turns.
   - Use Responses for models requiring reasoning effort with tools.
   - Keep Chat Completions only for compatible models or legacy fallback.

3. Validate `/model` at switch time.
   - Reject unsupported model/effort/endpoint combinations.
   - Explain exactly which endpoint will be used.

4. Add regression tests.
   - `/model gpt-5.5 high` with tools uses Responses request shape.
   - Unsupported effort on a model fails before the run.
   - Subagent model defaults are visible and overrideable through `/model subagents`.

### Deliverables

- `ModelRegistry`
- Responses-backed OpenAI tool completion path
- `/model` validation tests
- Model compatibility docs

## 2. Storage And Path Safety

### Problems

- Session names and goal keys are user-controlled.
- Any storage path derived from user input must be treated as hostile.
- State files need stronger invariants around containment, atomic writes, and corruption handling.

### Work

1. Encode storage keys.
   - Hash or slug session IDs.
   - Store display labels separately from filesystem names.

2. Centralize state path construction.
   - Provide one helper for session, goal, log, cache, and checkpoint paths.
   - Assert every path remains under the expected state root.

3. Add atomic state writes.
   - Write temp file, fsync if practical, rename.
   - Keep backup or recovery path for JSON/JSONL corruption.

4. Add adversarial path tests.
   - `../`, absolute paths, symlinks, unicode separators, empty names, very long names.

### Deliverables

- Safe state path helper
- Session and goal key migration path
- Path traversal tests
- Corruption recovery tests

## 3. Permissions And Safety Gate

### Problems

- The current safety gate is useful but coarse.
- Permissions are not expressed as a first-class policy with per-tool and per-agent rules.
- Prompt instructions cannot reliably prevent destructive behavior.

### Work

1. Introduce permission policy objects.
   - Actions: `allow`, `ask`, `deny`.
   - Scope: tool name, command prefix, file glob, external directory, agent role.

2. Add default policy.
   - Read workspace files: allow.
   - Read `.env`, `.env.*`: deny except examples.
   - Edit workspace files: ask or allow depending mode.
   - External directory read/write: ask.
   - Git commit/push: ask.
   - Destructive commands: deny or ask with explicit escalation.

3. Add per-agent overrides.
   - `coder`: can edit with safety gate.
   - `researcher`: read/search/web only.
   - `reviewer`: deny edit, allow diff/search/read.
   - `subagent`: inherit or constrain from parent.

4. Upgrade exploration gate.
   - Require relevant read/search evidence tied to target files.
   - Require mutation reason and expected outcome.
   - Store the evidence in the run trace.

5. Add loop guards.
   - Repeated identical tool call detection.
   - Max failed mutation attempts.
   - Max failed test reruns without new information.

### Deliverables

- Permission engine
- Policy config schema
- Tool middleware enforcement
- Exploration evidence schema
- Loop guard tests

## 4. Checkpoints, Undo, And Diff Safety

### Problems

- Agent mutations are hard to reverse unless the user relies on git.
- Git is not enough because users may have dirty work before SmolClaw starts.
- There is no checkpoint attached to a prompt/run.

### Work

1. Snapshot before mutation.
   - Track original file content for files the agent edits.
   - Track file creation and deletion.
   - Exclude large/generated files by policy.

2. Add checkpoint records.
   - Prompt ID, run ID, tool call ID, changed paths, before hashes, after hashes.

3. Add `/undo`.
   - Undo last agent-created checkpoint.
   - Refuse or warn if the file changed externally after the checkpoint.

4. Add `/rewind` later.
   - Restore code only.
   - Restore conversation only.
   - Restore both.
   - Summarize up to/from checkpoint.

5. Add pre-commit diff review hook.
   - Summarize changed files and risk.
   - Require user confirmation for high-risk changes if policy says `ask`.

### Deliverables

- Checkpoint store
- Mutation tool integration
- `/undo`
- Checkpoint conflict tests
- Diff review summary

## 5. Agent Loop And Goal Execution

### Problems

- `/goal run` can continue the model, but the loop needs a more explicit task state.
- Goal completion depends heavily on model self-report.
- There is no structured ledger of plan, progress, verification, and blockers.

### Work

1. Add a task ledger.
   - Goal text.
   - Plan steps.
   - Current step.
   - Files inspected.
   - Files changed.
   - Commands run.
   - Acceptance criteria.
   - Verification status.
   - Blockers and stop reason.

2. Let agents start goals explicitly.
   - Tool already exists; refine policy so "make this a goal" can be fulfilled without brittle slash-command reconstruction.

3. Add completion rules.
   - Goal cannot be marked complete unless acceptance criteria are satisfied or the agent records why no test is possible.
   - Completion stores verification evidence.

4. Add bounded retry behavior.
   - Test failure triggers diagnosis.
   - Retry must use new information.
   - Repeated failure stops with a blocker.

5. Add continuation prompt hygiene.
   - Continuation should include ledger summary, not raw full transcript.
   - Avoid putting tool logs into user-visible transcript.

### Deliverables

- Goal ledger schema
- Goal update tool improvements
- Completion gate
- Goal run tests with mocked LLM
- Goal trace export

## 6. TUI And Operator Experience

### Problems

- Long output and exceptions have already corrupted the UI.
- Tool thoughts/logs can overwhelm the main pane.
- Shutdown has hung before and needs better operator feedback.

### Work

1. Enforce separate buffers.
   - Transcript pane: user and assistant messages only.
   - Status bar: mode, model, cwd, git branch, tokens, safety state, run state.
   - Activity line: spinner and current operation.
   - Log drawer: tool calls, diagnostics, errors.
   - Trace export: full machine-readable run record.

2. Add scrollback.
   - Main pane scroll.
   - Log pane scroll.
   - Prompt area fixed-height and clipped.

3. Harden rendering.
   - All text wraps inside pane boundaries.
   - Exceptions render as contained error blocks.
   - Terminal resize recalculates layout.
   - Shutdown state shows phase and timeout countdown.

4. Add cancellation model.
   - First Ctrl+C requests cancel.
   - Second Ctrl+C during shutdown forces exit.
   - Tool execution receives cancellation where possible.

5. Add non-interactive mode.
   - Useful for evals and scripts.
   - Structured JSONL output option.

### Deliverables

- Stream routing abstraction
- Log drawer
- Scrollback tests or snapshot tests
- Shutdown phase UI
- Non-interactive output mode

## 7. Subagents And Orchestration

### Problems

- Subagents exist, but the product semantics should be narrower and clearer.
- Subagents should solve context pollution and independent review, not add uncontrolled complexity.

### Work

1. Define first-class subagent roles.
   - Explorer: read/search only, returns relevant files and hypotheses.
   - Reviewer: diff/read/test-output only, returns risks.
   - Tester: command-limited verification only.
   - Researcher: web/search/read only.

2. Add subagent budget controls.
   - Max turns.
   - Max tokens.
   - Allowed tools.
   - Model and effort.

3. Keep main context clean.
   - Subagents return structured summaries.
   - Full subagent traces are stored separately.

4. Add orchestration only where useful.
   - Writer/reviewer.
   - Explorer/implementer.
   - Test-first split.

### Deliverables

- Subagent role configs
- Structured subagent result schema
- Budget enforcement
- Independent reviewer tests

## 8. Evaluation Harness

### Problems

- Unit tests prove implementation details, not agent reliability.
- We need a sufficiently difficult benchmark task set for SmolClaw itself.

### Work

1. Create local coding task fixtures.
   - Small Python bug fix.
   - Multi-file refactor.
   - CLI behavior change.
   - TUI rendering regression.
   - Safety blocked mutation.
   - Goal continuation.
   - Dirty worktree preservation.

2. Isolate each run.
   - Copy fixture to temp dir or use git worktree.
   - Run `smolclaw` non-interactively.
   - Capture trajectory, diff, output, tests, and status.

3. Score outcomes.
   - Tests passed.
   - Diff minimality.
   - Required files touched.
   - Forbidden files untouched.
   - Exploration evidence present.
   - Goal completion justified.
   - No safety violations.

4. Add regression modes.
   - Mock LLM for deterministic loop tests.
   - Live model smoke for periodic manual runs.
   - Recorded trajectory replay for UI/log rendering.

5. Track metrics.
   - Success rate.
   - Turns to completion.
   - Tool calls.
   - Tokens.
   - Cost estimate.
   - Failure class.

### Deliverables

- `tests/fixtures/agent_tasks/`
- `scripts/run_agent_eval.py`
- JSONL trajectory format
- Eval score report
- CI smoke subset

## 9. Sandbox And Worktree Isolation

### Problems

- Direct host execution is risky.
- Remote chat control via Telegram, Signal, or WebSocket should not share the same trust model as a local TUI operator.

### Work

1. Add worktree mode.
   - Create a temporary git worktree per goal.
   - Let the agent edit there.
   - Present diff back to main repo.

2. Add sandbox backend abstraction.
   - Local process.
   - Docker.
   - Future: macOS sandbox, bubblewrap, SSH.

3. Define trust levels.
   - Local trusted operator.
   - Local untrusted workspace.
   - Remote paired operator.
   - Remote untrusted inbound message.

4. Restrict remote-origin sessions.
   - No direct host write by default.
   - No secret reads.
   - Explicit approvals for side effects.
   - Idempotency keys for writes/messages.

5. Add sandbox tests.
   - Path containment.
   - Secret denial.
   - External directory denial.
   - Worktree diff export.

### Deliverables

- Worktree runner
- Sandbox interface
- Trust-level policy
- Remote-safe defaults

## 10. Gateway And Remote Control

### Problems

- The project has a WebSocket gateway, but remote assistant control needs a stronger protocol and trust model.
- Chat channels like Signal or Telegram introduce prompt injection and identity risks.

### Work

1. Define typed gateway events.
   - `run.accepted`
   - `run.progress`
   - `tool.started`
   - `tool.finished`
   - `run.waiting_for_approval`
   - `run.cancelled`
   - `run.completed`
   - `run.failed`

2. Add run IDs and idempotency.
   - Side-effecting requests must include an idempotency key.
   - Replays should not duplicate writes or messages.

3. Add pairing.
   - Single-account local pairing first.
   - Store paired identity separately from session key.

4. Add channel adapters later.
   - Telegram first if desired.
   - Signal only after proving local gateway auth, pairing, and sandbox policy.

5. Add remote-safe command surface.
   - Status.
   - Start goal.
   - Continue goal.
   - Cancel run.
   - Approve/reject pending action.
   - Fetch summary/diff.

### Deliverables

- Gateway protocol doc
- Typed event schema
- Pairing store
- Remote-safe tool policy
- Channel adapter spike

## 11. Documentation And Packaging

### Problems

- Some docs are stale.
- Package install validation was blocked by missing local build dependencies.
- The project needs clear operator docs before broader use.

### Work

1. Maintain current docs.
   - Document `smolclaw` as the only entry point.
   - Keep `docs/architecture-runtime.md` current.
   - Keep this roadmap current as priorities change.

2. Add user docs.
   - Install.
   - Configure API keys.
   - Switch models.
   - Start a goal.
   - Run tests.
   - Undo changes.
   - Troubleshoot TUI.

3. Add developer docs.
   - Runtime architecture.
   - Tool registration.
   - Permissions.
   - Safety gate.
   - Eval harness.

4. Add package checks.
   - Build wheel in CI.
   - Install into a clean venv.
   - Verify `smolclaw --help`.
   - Verify no legacy coding console script is installed.

### Deliverables

- Updated README
- Updated project outline
- Packaging CI check
- Install smoke test

## Milestones

### Milestone A - Trust The Local CLI

Status: mostly complete for the local CLI path.

Completed scope:

- Responses API for tool turns.
- Safe session/goal storage keys.
- TUI stream isolation for errors/logs.
- Docs and package metadata consistently expose `smolclaw`.
- Full test and package smoke pass.

Why first:

The user-facing product must stop saying or displaying things that are not true. Model effort, global install, and terminal stability are the current credibility risks.

### Milestone B - Safe Mutation

Status: complete for v1 hard-deny local safety; approval workflows remain future work.

Completed scope:

- Permission policy engine.
- Checkpoints before writes.
- `/undo`.
- Secret and external-directory gates.
- Repeated identical tool call guard.

Remaining follow-up:

- Better structured exploration evidence and trace export.
- Configurable `ask` approvals for riskier local workflows.

Why second:

This is the minimum needed before trusting longer agentic loops.

### Milestone C - Useful Goals

Scope:

- Task ledger.
- Acceptance criteria.
- Verification gates.
- Bounded retries.
- Structured goal traces.

Why third:

The goal loop should become a real harness, not just repeated chat continuation.

### Milestone D - Prove It

Scope:

- Local agent task eval suite.
- Non-interactive runner.
- Trajectory capture.
- Score report.
- CI smoke subset.

Why fourth:

Reliability work is otherwise anecdotal. This gives us a way to compare changes.

### Milestone E - Remote-Ready Isolation

Scope:

- Worktree mode.
- Sandbox abstraction.
- Gateway run events.
- Pairing and idempotency.
- Remote-safe policy.

Why fifth:

Telegram/Signal/WebSocket control should wait until mutation and identity boundaries are enforceable.

## Suggested Immediate Backlog

1. Add goal ledger v1.
   - Store plan, inspected files, changed files, tests, status, and stop reason.

2. Add completion and verification gates.
   - Require acceptance criteria or an explicit "no verification possible" note before goal completion.
   - Store verification commands and results.

3. Build first eval fixture.
   - Use a small intentionally broken project.
   - Require exploration, edit, test, and completion evidence.

4. Add non-interactive eval runner.
   - Capture prompt, trajectory, diff, tests, status, and stop reason.

5. Add worktree or sandbox spike.
   - Run a risky goal in isolation and present the diff back to the main workspace.

6. Expand operator docs.
   - Document `/undo`, permission denials, secret-file behavior, and troubleshooting.
   - Add install and troubleshooting docs.
   - Keep README, workspace docs, and roadmap aligned.

## Open Questions

- Should default local edit policy be `allow` after exploration, or `ask` until checkpoints/undo are mature?
- Should worktree mode be the default for goals, or an opt-in mode for risky tasks?
- Should memory be enabled for coding by default, or should coding sessions prefer project-local context plus explicit memory recall?
- How much reasoning/thinking should be visible in the TUI versus stored only in traces?
- Should subagents be user-visible commands or mostly model-invoked tools?
- What is the first remote channel worth supporting: WebSocket client, Telegram, or Signal?

## Non-Goals For Now

- Full OpenClaw-style always-on personal assistant.
- Multi-user hostile tenancy in one gateway.
- Unrestricted host shell access.
- Browser automation by default.
- Autonomous git push without explicit approval.
- Large multi-agent organization before single-agent reliability is measured.

## Definition Of Reliable Enough

SmolClaw is reliable enough for regular local coding use when:

- it does not corrupt the terminal during long output, errors, or shutdown;
- it does not edit before relevant exploration;
- it can undo its own file mutations;
- it cannot escape workspace/state storage through path tricks;
- it can run a goal to completion with recorded acceptance criteria and verification;
- it exposes enough status to show whether it is thinking, searching, editing, testing, blocked, cancelling, or shutting down;
- it passes a local agent eval suite that includes realistic implementation, failure, safety, and UI scenarios;
- its docs match the installed command and actual runtime behavior.
