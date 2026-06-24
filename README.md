# SmolClaw

SmolClaw is a local coding-assistant harness with persistent memory, project-aware tools, goal loops, and a terminal-first interface.

The main entry point is:

```bash
smolclaw
```

There is no separate `smolcode` command. Coding work, chat, goals, and model switching all happen through `smolclaw`.

## Direction

SmolClaw is being shaped into a focused local coding tool, closer to OpenCode or Claude Code than to a broad always-on personal assistant.

The current priority is reliability:

- understand the codebase before editing;
- keep tool output, logs, and user messages visually separate;
- make model settings match actual provider behavior;
- enforce structural safety for file and command tools;
- support checkpoints and undo for agent-made changes;
- run explicit goals with verification evidence;
- build evals that prove agent behavior, not just unit-level code paths.

For the roadmap, see [docs/reliability-roadmap.md](docs/reliability-roadmap.md).

## What Works Today

- Interactive terminal UI through `smolclaw`.
- Agent loop with OpenAI/Anthropic model support.
- Per-agent configuration through `agents.yaml` and markdown bootstrap files.
- Project-scoped filesystem tools:
  - `read_file`
  - `write_file`
  - `edit_file`
  - `apply_patch`
  - `list_dir`
  - `find_files`
  - `grep_search`
- Constrained command tools for project checks.
- Git status and diff helpers.
- Checkpoints for file mutations and `/undo` for restoring the last SmolClaw change.
- Permission policies with exact-call approval commands:
  - `/approval status`
  - `/approval approve <id>`
  - `/approval deny <id>`
- Run trace inspection:
  - `/trace`
  - `/trace list`
  - `/trace events [run_id] [limit]`
  - `/trace replay [run_id]`
- Project bootstrap with `/init` or `smolclaw init`.
- Goal commands:
  - `/goal start ...`
  - `/goal run N`
  - `/goal status`
  - `/goal complete ...`
- Agent tools for inspecting/updating active goals.
- Persistent sessions and token usage tracking.
- Memory-backed retrieval through SmolRAG.
- Optional WebSocket/gateway infrastructure in the codebase, treated as secondary until local reliability is stronger.

## Install

Use Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Set provider keys in your shell or `.env`:

```bash
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

SmolRAG memory model defaults:

```bash
MEMORY_EXTRACT_MODEL=gpt-5.4-mini
MEMORY_QUERY_MODEL=gpt-5.4
EMBEDDING_MODEL=text-embedding-3-small
```

Then run:

```bash
smolclaw
```

SmolClaw uses the current working directory as the project workspace by default.

## Common Commands

Inside the TUI:

```text
/help
/model
/model list
/model gpt-5.5 medium
/model subagents gpt-5.5 medium
/undo
/approval status
/approval approve apr-...
/goal start Add a regression test for the parser
/goal run 3
/goal status
/quit
```

Sessions are not exported to memory on shutdown by default. Use `/remember-thread` for an explicit session export, or start with `--auto-export` when you intentionally want close-time memory export.

Model compatibility:

- `/model` reports the active model, effort, provider, and endpoint behavior.
- `gpt-5.4*` and `gpt-5.5*` models are validated through `ModelRegistry`.
- Reasoning tool turns use the OpenAI Responses API; compatible legacy text/tool turns keep using Chat Completions.

Useful examples:

```text
review this project
find where sessions are persisted
add grep search within the current workspace
run the relevant tests
make this a goal and work through it
```

Reset examples:

```bash
smolclaw reset --force --logs
smolclaw reset --force --journals
smolclaw reset --force --memories
smolclaw reset --force --rag --kg
smolclaw reset --force --all
```

## Workspaces And State

The active project directory is the workspace for local file tools. Runtime state is stored under `.smolclaw/` in that project rather than mixed into the repository root.

For workspace behavior and reset semantics, see [docs/workspaces.md](docs/workspaces.md).

## Architecture

The maintained runtime architecture doc is [docs/architecture-runtime.md](docs/architecture-runtime.md).
The supporting research for the architecture and roadmap is [docs/research-agentic-coding-harnesses.md](docs/research-agentic-coding-harnesses.md).
The next-phase implementation design is [docs/next-phase-implementation-design.md](docs/next-phase-implementation-design.md).

At a high level:

- `cli/main.py` owns the CLI/TUI entry points.
- `app/runtime_builder.py` builds workspace, memory, session, and runtime services.
- `app/runtime.py` resolves capabilities and configured agents.
- `app/agent_factory.py` builds agent loops and child-agent factories.
- `app/agent_loop.py` runs model/tool iterations.
- `app/tools/` contains tool definitions, middleware, permissions, and registries.
- `app/smol_rag.py` and related stores provide memory/retrieval.

## Tests

Run the Python suite:

```bash
python -m pytest -q
```

Tests use mocked model paths where possible and should not require live provider keys for normal unit coverage.
Agent eval tasks can be run with `scripts/run_agent_eval.py` in `mock`, `recorded`, or opt-in `live` mode. Pass multiple task directories to emit a suite report with aggregate check rates, failure classes, recommended actions, and optional score deltas from `--baseline`.

## Current Reliability Work

The next major work is tracked in [docs/reliability-roadmap.md](docs/reliability-roadmap.md) and [docs/next-phase-implementation-design.md](docs/next-phase-implementation-design.md). The highest-priority items are:

1. Harden shared run presentation across `/trace`, `/goal status`, eval reports, non-interactive JSON, and TUI drawers.
2. Expand the eval suite with realistic fixtures and CI score-delta reporting.
3. Harden worktree dirty-copy behavior and add richer apply-back review.
4. Improve approval UX while keeping exact-call approvals as the safe default.
5. Tune target-aware safety using eval-backed fixtures before tightening heuristics.

## Non-Goals For Now

- Full OpenClaw-style always-on personal assistant.
- Multi-user hostile tenancy in one gateway.
- Unrestricted host shell access.
- Autonomous git push without explicit approval.
- Telegram/Signal control before sandboxing, pairing, and remote-safe permissions are implemented.
