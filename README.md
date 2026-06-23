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
/goal start Add a regression test for the parser
/goal run 3
/goal status
/quit
```

Useful examples:

```text
review this project
find where sessions are persisted
add grep search within the current workspace
run the relevant tests
make this a goal and work through it
```

## Workspaces And State

The active project directory is the workspace for local file tools. Runtime state is stored under the project-owned state layout rather than mixed into arbitrary user files.

For workspace behavior and reset semantics, see [docs/workspaces.md](docs/workspaces.md).

## Architecture

The maintained runtime architecture doc is [docs/architecture-runtime.md](docs/architecture-runtime.md).

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

## Current Reliability Work

The next major work is tracked in [docs/reliability-roadmap.md](docs/reliability-roadmap.md). The highest-priority items are:

1. Route OpenAI tool-using turns through an endpoint that supports reasoning effort.
2. Harden session and goal storage paths.
3. Separate TUI transcript, status, logs, traces, and errors.
4. Add structural permissions and secret/external-directory gates.
5. Add checkpoints and `/undo`.
6. Add a goal ledger with acceptance criteria and verification evidence.
7. Add a local agent-eval harness.

## Non-Goals For Now

- Full OpenClaw-style always-on personal assistant.
- Multi-user hostile tenancy in one gateway.
- Unrestricted host shell access.
- Autonomous git push without explicit approval.
- Telegram/Signal control before sandboxing, pairing, and remote-safe permissions are implemented.
