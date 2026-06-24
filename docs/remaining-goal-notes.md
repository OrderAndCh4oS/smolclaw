# Remaining Goal Notes

Date: 2026-06-23

Active goal: implement `docs/next-phase-implementation-design.md`

Status: paused. The foundation for trace export, goal ledgers, approvals, evals, worktree isolation, target-aware safety, and project bootstrap is implemented in the working tree, but the phase is not complete.

## Recent Verification

- Full suite previously passed after the main phase work: `917 passed`.
- Focused smoke after the worktree and related changes passed: `156 passed`.
- Latest focused checks for `/remember-thread` UX passed:
  - `pytest tests/test_cli_tui.py`
  - `pytest tests/test_cli_multiagent.py -k remember_thread`
  - `git diff --check`

## Recently Added During This Session

- `/remember-thread` no longer looks like a terminal crash in TUI/chat.
- TUI now prints a slow-export notice before journaling/indexing the current thread.
- TUI and plain chat now catch real manual export failures and show diagnostics incidents.
- Focused TUI tests cover slow-export notice and export failure reporting.
- SmolRAG now has a two-model memory split:
  - extraction/indexing/keyword work defaults to `gpt-5.4-mini`;
  - final memory query synthesis defaults to `gpt-5.4`;
  - embeddings default to `text-embedding-3-small`.

## Important Current Behaviour

- `/remember-thread` is still synchronous and can remain in `status:exporting` while journal generation and SmolRAG ingestion run.
- Journal generation uses the active agent model via `agent.llm`.
- SmolRAG memory model defaults can be overridden with `MEMORY_EXTRACT_MODEL`, `MEMORY_QUERY_MODEL`, and `EMBEDDING_MODEL`.

## Remaining Work

### Session Memory And Journaling

- Decide whether `/remember-thread` should stay synchronous or become a background job.
- Add a cheaper structured session-summary path before full KG ingestion.
- Consider a first-class `/journal` or enhanced `/remember-thread` output with:
  - objective;
  - decisions;
  - files changed;
  - tests run;
  - unresolved problems;
  - next steps;
  - trace/ledger/session ids.
- Add redaction before storing transcript-derived memories.
- Extend recall so `memory_recall` can include `journal` memories or accept a `memory_type` parameter.

### Trace And Ledger UX

- Add richer TUI trace drawer.
- Make ledger status more visible in final run output and eval report text.
- Surface evidence joins clearly:
  - ledger evidence id;
  - related trace event id;
  - originating `tool.started` event id;
  - provider tool-call id.
- Add parity tests for CLI, TUI, and non-interactive `run` outputs using the same trace/ledger fixture.

### Eval Harness

- Add more realistic fixtures:
  - multi-file bugfix;
  - documentation-only change;
  - blocked secret read;
  - dirty-worktree preservation;
  - approval-required command;
  - TUI/trace rendering;
  - Python, Node, and mixed repos.
- Wire suite score deltas into CI.
- Add a bootstrap-before-run eval comparison.
- Add a full integrity test that follows a changed file from ledger evidence to tool event, checkpoint event, and final trace summary.

### Permissions And Approvals

- Keep exact-call approvals as the safe default.
- Add session-pattern approvals only after the UI can clearly display the approved pattern.
- Pattern approvals should be narrow:
  - command prefix;
  - path glob;
  - tool name.
- Re-validate every approved call against hard-deny and mode-deny rules.
- Add automatic replay only when the transport can prove a retry is byte-for-byte the approved call or matches a displayed session pattern.

### Worktree Isolation

- Harden dirty-copy mode:
  - file-count guardrail;
  - byte-count guardrail;
  - ignored-root exclusions;
  - secret-path warnings;
  - clearer user-facing warning before copying dirty state.
- Add richer apply-back review before applying larger isolated diffs.
- Keep `.smolclaw/` excluded from isolated diff export, with legacy excludes for old top-level `stores/`, `memory/`, and `research/`.
- Add regression tests proving state writes stay in the original workspace for every worktree entrypoint.

### Target-Aware Safety

- Tune target relevance to avoid false unlocks and unnecessary mutation blocks.
- Add reasoned denials naming missing evidence:
  - git status;
  - target read;
  - parent directory evidence;
  - relevant search;
  - verification.
- Add a lightweight exploration score for larger repos:
  - target read;
  - parent listing;
  - symbol search;
  - tests inspected;
  - related call sites.
- Add generated-file and large-repo fixtures before tightening thresholds.

### Project Bootstrap

- Add more fixture coverage for generated `AGENTS.md` guidance.
- Add install and troubleshooting docs.
- Treat generated repo guidance as helpful context, not enforcement.

### Shared Runtime State

- Add a small typed accessor layer for shared state keys used across middleware.
- Missing or malformed shared state should fail softly at runtime and loudly in tests.
- Keep shared keys stable once documented:
  - trace recorder;
  - active trace event ids;
  - active provider tool-call ids;
  - goal ledger store/session key;
  - approval store;
  - checkpoint store.

## Problem Areas To Watch

- Traces and memory can accidentally capture secrets. Keep redaction and summarized payloads as the default.
- Goal completion can become ceremonial if completion does not require evidence.
- Evidence, checkpoint, trace, and ledger writes can drift if they are not tested together.
- Dirty-copy isolation can carry ignored files or stale local artifacts into an isolated run.
- Session-pattern approvals can silently authorize too much.
- Memory indexing can be slow enough to look like a terminal hang.

## Suggested Next Commit Scope

1. Make `/remember-thread` queue background export or add a cheaper structured session-summary path.
2. Add redaction before storing transcript-derived memories.
3. Add richer trace/ledger rendering and parity tests.
4. Expand eval fixtures and wire suite deltas into CI.
