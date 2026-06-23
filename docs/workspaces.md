# SmolClaw Workspaces

Workspaces are the unit of project scope in SmolClaw.

By default, `smolclaw` uses the current working directory as the workspace. That directory is the root for local file tools and project-specific runtime state.

Use one workspace per codebase or project.

## Layout

```text
your-project/
  stores/
    smolclaw.db
    kg_db.graphml
    sessions/
    logs/
    cache/
  memory/
  research/
```

- `stores/` holds derived runtime state. This includes the SQLite database, knowledge graph, sessions, logs, and caches.
- `memory/` holds exported markdown memories and session documents.
- `research/` holds optional source material you want SmolClaw to ingest and preserve.

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

If you keep project notes or external material in `research/`, you can ingest them:

```bash
python -m cli.main ingest ~/code/my-project/research --workspace ~/code/my-project
```

If you want continuous re-ingestion while you add or edit files:

```bash
python -m cli.main watch --workspace ~/code/my-project
```

Research loops still exist, but the main product direction is local coding reliability.

## Reset Behavior

`reset` clears derived state for the active workspace:

- `stores/sessions/`
- `stores/logs/`
- `stores/cache/`
- `smolclaw.db`
- `kg_db.graphml`
- `memory/`

`reset` does not delete `research/`.

Example:

```bash
python -m cli.main reset --workspace ~/code/my-project --force
```

## Workspace Scoping

The direct local runtime uses the active workspace as its boundary for local state and filesystem tools.

- Relative file paths resolve from the workspace root.
- Local derived state is written only under that workspace.
- Different workspaces keep recall, memory promotion, sessions, and logs isolated from one another.

Gateway mode still exists in the codebase, but it is not the primary product surface while local safety, checkpoints, and evals are being hardened.

## Recommended Pattern

- One workspace per codebase
- One workspace per client project
- One workspace per long-running investigation

That keeps memories and sessions useful instead of mixing unrelated work into one retrieval pool.
