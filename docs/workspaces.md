# SmolClaw Workspaces

Workspaces are the unit of project scope in SmolClaw.

By default, `smolclaw` uses the current working directory as the workspace. That directory is the root for local file tools. Project-specific runtime state is kept under `.smolclaw/` in that workspace.

Use one workspace per codebase or project.

Internally SmolClaw distinguishes the editable source root from the state root. For normal use the source root is the project directory and the state root is `<workspace>/.smolclaw`. In isolated worktree runs, file tools operate on the temporary worktree source root while sessions, traces, ledgers, approvals, checkpoints, memory, and eval artifacts stay under the original workspace state root.

## Layout

```text
your-project/
  .smolclaw/
    stores/
      smolclaw.db
      kg_db.graphml
      sessions/
      checkpoints/
      traces/
      ledgers/
      approvals/
      evals/
      logs/
      cache/
    memory/
    research/
```

- `.smolclaw/stores/` holds derived runtime state. This includes the SQLite database, knowledge graph, sessions, checkpoints, traces, ledgers, approval requests, eval artifacts, logs, and caches.
- `.smolclaw/memory/` holds exported markdown memories and session documents.
- `.smolclaw/research/` holds preserved source material for research. Research agents write plain text notes here with source URLs, summaries, related links, and extracted page text.

## How To Use One

For normal coding use, run `smolclaw` from the project root.

```bash
cd ~/code/my-project
smolclaw
```

For explicit workspace commands, pass `--workspace`:

```bash
python -m cli.main chat --workspace ~/code/my-project
python -m cli.main recall "auth" --workspace ~/code/my-project
```

For isolated coding sessions, pass `--worktree` to `chat` or `run`. File tools operate in the temporary worktree source root, while sessions, traces, ledgers, approvals, checkpoints, memory, and eval artifacts stay in the original workspace state root.

```bash
python -m cli.main chat --workspace ~/code/my-project --worktree
python -m cli.main run "fix the parser" --workspace ~/code/my-project --worktree --goal
```

Inside an isolated chat or TUI session, use:

```text
/worktree status
/worktree diff
/worktree apply
/worktree discard
```

`/worktree apply` applies the isolated diff back to the base repository. `/worktree discard` schedules the isolated worktree for cleanup when the session exits.

Normal `--worktree` mode requires a clean git repository and uses `git worktree`
from `HEAD`. If the base repository is dirty, SmolClaw refuses normal worktree
creation unless `--copy-dirty-worktree` is supplied. Dirty-copy mode copies the
working tree into a temporary repository and records preflight metadata in
`/worktree status` and non-interactive `run_status`.

Dirty-copy mode excludes common state, cache, build, and secret-like paths by
default: `.git`, `.smolclaw`, virtualenvs, package caches, build outputs,
`.env*`, private-key-like files, and similar noisy roots. Excluded paths and
large-copy thresholds are reported as warnings. Private-key-like paths and very
large copies are refused by default rather than copied.

Apply-back is review-gated for broad or risky isolated diffs. Small diffs can be
applied with `/worktree apply`; larger diffs, deletions, binary-looking changes,
or secret-like paths return a review summary and require:

```text
/worktree apply --confirm
```

If you keep project notes or external material in `.smolclaw/research/`, you can ingest them:

```bash
python -m cli.main ingest ~/code/my-project/.smolclaw/research --workspace ~/code/my-project
```

During web research, the `researcher` agent should call `research_source_store` after it fetches a source that backs a finding. Those source notes are preserved across `reset` and can also be indexed into SmolRAG for future recall.

If you want continuous re-ingestion while you add or edit files:

```bash
python -m cli.main watch --workspace ~/code/my-project
```

Research loops still exist, but the main product direction is local coding reliability.

## Reset Behavior

`reset` clears derived state for the active workspace:

- `.smolclaw/stores/sessions/`
- `.smolclaw/stores/checkpoints/`
- `.smolclaw/stores/traces/`
- `.smolclaw/stores/ledgers/`
- `.smolclaw/stores/approvals/`
- `.smolclaw/stores/evals/`
- `.smolclaw/stores/logs/`
- `.smolclaw/stores/cache/`
- `.smolclaw/stores/smolclaw.db`
- `.smolclaw/stores/kg_db.graphml`
- `.smolclaw/memory/`

`reset` does not delete `.smolclaw/research/`.

Example:

```bash
python -m cli.main reset --workspace ~/code/my-project --force
```

Targeted reset flags clear selected state while preserving the rest:

```bash
python -m cli.main reset --workspace ~/code/my-project --force --logs
python -m cli.main reset --workspace ~/code/my-project --force --journals
python -m cli.main reset --workspace ~/code/my-project --force --memories
python -m cli.main reset --workspace ~/code/my-project --force --rag --kg
```

- `--logs` clears `.smolclaw/stores/logs/`.
- `--journals` clears `journal-*` files from `.smolclaw/memory/`.
- `--memories` clears non-journal files from `.smolclaw/memory/`.
- `--rag` replaces `.smolclaw/stores/smolclaw.db` with a fresh SQLite database and removes SQLite WAL/SHM files.
- `--kg` replaces `.smolclaw/stores/kg_db.graphml` with a fresh empty GraphML file.
- `--all`, or no component flags, performs the full reset.

Clearing memory markdown does not remove already indexed excerpts from `.smolclaw/stores/smolclaw.db`; use `--rag` as well when recall should forget prior memory content.

## Workspace Scoping

The direct local runtime uses the active workspace as its boundary for local state and filesystem tools.

- Relative file paths resolve from the workspace root.
- Local derived state is written only under `.smolclaw/` in that workspace.
- In worktree mode, relative file paths resolve from the isolated worktree, while derived state is still written under the original workspace.
- Different workspaces keep recall, memory promotion, sessions, and logs isolated from one another.
- Secret files named `.env` or `.env.*` are denied by local tool policy, except example/template files such as `.env.example`.
- Local tools reject file paths and command working directories outside the workspace in the v1 safety policy.

## Permission Policy

SmolClaw loads permission policy from:

- `SMOLCLAW_PERMISSION_POLICY` when set
- `~/.config/smolclaw/permissions.yaml`
- `~/.smolclaw/permissions.yaml`
- `.smolclaw/permissions.yaml`, `.yml`, or `.json` in the workspace

Example:

```yaml
rules:
  - subject: command
    pattern: "npm install*"
    action: ask
    reason: "dependency changes need approval"
  - subject: path
    pattern: "generated/**"
    action: deny
    reason: "generated files are not edited directly"
```

Policy files can make behavior stricter or request approval, but they cannot override hard-deny secret-path checks, workspace containment, or the active agent permission mode. `AGENTS.md` is project guidance only and is never read as permission policy.

When a rule uses `action: ask`, SmolClaw records a pending exact-call approval. Use:

```text
/approval status
/approval detail <id>
/approval approve <id>
/approval deny <id>
```

`/approval detail <id>` shows the tool, exact-call scope, normalized argument hash, argument preview, matched policy rule, reason, run id when available, and expiry. Approving an item allows the same tool call with the same normalized arguments to run once. Changed arguments create a new approval request.

## Adapter Config

SmolClaw loads project adapter defaults from `.smolclaw/config.yaml`.
User-level config can also live at `~/.config/smolclaw/config.yaml` or `~/.smolclaw/config.yaml`.
Workspace config overrides user config, and explicit CLI flags such as `--model` override YAML.

Example:

```yaml
adapters:
  llm:
    default:
      provider: openai
      model: gpt-5.5
    memory_extract:
      provider: openai
      model: gpt-5.4-mini
    memory_query:
      provider: openai
      model: gpt-5.4
    embeddings:
      provider: openai
      model: text-embedding-3-small
    subagents:
      provider: openai
      model: gpt-5.5
  task_source:
    default:
      provider: jira
  code_review:
    default:
      provider: github
  command:
    default:
      provider: subprocess
```

For local Kanboard task intake with GitHub PR publication:

```yaml
adapters:
  task_source:
    default:
      provider: kanboard
  code_review:
    default:
      provider: github

task_source:
  provider: local
  url: http://localhost:8080
  username: jsonrpc
  token_env: KANBOARD_API_TOKEN
  project: SMOL
  eligible_statuses: [Backlog]
  in_progress_status: Work in progress
  review_status: Review
  required_label: agent-ready
```

The local task-source provider is backed by Kanboard. Kanboard columns are
mapped to work-loop statuses. Task tags are mapped to labels, so
`required_label` and `blocked_labels` work the same way as Jira labels.

If you prefer environment-based setup, the Kanboard adapter also reads
`KANBOARD_URL` or `KANBOARD_API_URL`, `KANBOARD_API_TOKEN`,
`KANBOARD_USERNAME`, and one of `KANBOARD_PROJECT`, `KANBOARD_PROJECT_ID`,
`KANBOARD_PROJECT_IDENTIFIER`, or `KANBOARD_PROJECT_NAME`. When these are set,
agents can omit `project` in work-loop tool calls. Agent-facing tools do not
expose config paths; they discover `.work-loop.yaml` or the workspace runtime
adapter config from the active workspace.

Create a Kanboard task through the configured task source:

```bash
smolclaw work-loop create-task "Add totals empty state" \
  --workspace ~/code/my-project \
  --config smolclaw.kanboard-loop.yaml \
  --project SMOL \
  --description "Implement and verify the empty state." \
  --label agent-ready \
  --status Backlog
```

The `coder` agent can also operate on the configured task source from terminal
chat when asked. These provider-neutral tools work with Kanboard or any other
task-source adapter that implements the operation:

- `work_loop_list_tasks`
- `work_loop_view_task`
- `work_loop_create_task`
- `work_loop_move_task`
- `work_loop_comment_task`
- `work_loop_close_task`

Read-only tools (`work_loop_list_tasks` and `work_loop_view_task`) do not require
approval. Mutation tools (`work_loop_create_task`, `work_loop_move_task`,
`work_loop_comment_task`, and `work_loop_close_task`) are approval-gated because
they change external state. The TUI will show a pending approval, and the call
only continues after `/approval approve <id>`.

The `ticket_writer` agent is specialized for turning roadmap notes into
Kanban-ready tickets. It reads project context, drafts problem/solution/
acceptance-criteria sections, checks existing tasks when useful, and creates
work-loop tasks only through approval-gated task-source tools.

From terminal chat, start the mounted work loop with:

```text
/work-loop start --limit 1
```

`start` runs review follow-up first, then starts eligible task-source work. It
uses the configured project from `.work-loop.yaml` unless `--project` is passed
explicitly.

To run agent command and git tools through the Docker sandbox, set the command
provider to `docker`. The legacy `model` field selects the container image;
`sandbox.image` takes precedence when both are present. When omitted, SmolClaw
uses its default Python image and `doctor` warns when project markers suggest a
different toolchain is needed.

```yaml
adapters:
  command:
    default:
      provider: docker
      model: legacy-image:latest
    sandbox:
      image: smolclaw-dev:latest
      cpus: "2"
      memory: 2g
      pids_limit: 256
      tmpfs_size: 512m
      read_only_root: true
      approved_network: bridge
      network_proxy_env:
        HTTPS_PROXY: http://proxy.local:8080
      auto_pull: true
      auto_build: false
      build_context: .
      build_dockerfile: Dockerfile.sandbox
      env_allowlist:
        - CI
        - LANG
        - LC_ALL
        - TERM
```

Docker sandbox networking defaults to `none` for every agent command. Commands
and shell sessions can request `network_access: true`; in `execute` and `full`
permission modes that declares the `network` capability and creates an approval
request before Docker receives the approved network mode. `network_proxy_env`
must be configured for approved network calls. Proxy values are passed to the
Docker CLI through the host runner environment, while Docker command arguments
contain only proxy variable names.

Docker image readiness starts with local `docker image inspect`. If the image is
missing and `auto_build` or `auto_pull` is configured, SmolClaw asks for
`image_management` approval before running `docker build` or `docker pull`.
Successful readiness is cached for the runner lifetime.

Claude completions can be paired with Voyage embeddings:

```yaml
adapters:
  llm:
    default:
      provider: anthropic
      model: claude-sonnet-4-20250514
    subagents:
      provider: anthropic
      model: claude-sonnet-4-20250514
    embeddings:
      provider: voyage
      model: voyage-4
```

Secrets do not belong in this file. API keys and CLI authentication still come from environment variables or provider-specific auth tools.

Gateway mode still exists in the codebase, but it is not the primary product surface while local safety, checkpoints, and evals are being hardened.

## Recommended Pattern

- One workspace per codebase
- One workspace per client project
- One workspace per long-running investigation

That keeps memories and sessions useful instead of mixing unrelated work into one retrieval pool.
