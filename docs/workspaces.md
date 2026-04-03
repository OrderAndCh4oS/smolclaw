# SmolClaw Workspaces

Workspaces are the unit of isolation in SmolClaw.

Pick a workspace when you start the CLI or gateway with `--workspace`. That directory becomes the home for local research material, exported memory, sessions, logs, indexes, and caches for that run.

Use one workspace per topic, project, client, or research stream.

## Layout

```text
your-workspace/
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
- `research/` holds the source material you want SmolClaw to ingest and preserve.

## How To Use One

Choose a workspace root and keep your source material inside `research/`.

```bash
export WS=~/smolclaw-workspaces/acme-research
mkdir -p "$WS"/research
cp ~/notes/acme-brief.md "$WS"/research/
```

Then run SmolClaw against that workspace:

```bash
python -m cli.main ingest "$WS"/research --workspace "$WS"
python -m cli.main chat --workspace "$WS" --session acme
python -m cli.main recall "acme" --workspace "$WS"
```

If you want continuous re-ingestion while you add or edit files:

```bash
python -m cli.main watch --workspace "$WS"
```

If you want recurring automated research inside one isolated workspace:

```bash
python -m cli.main research-loop "Track Acme competitors and notable product changes." --workspace "$WS"
```

The loop keeps using the same workspace memory and session until you stop it with `Ctrl+C` or `Esc`.

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
python -m cli.main reset --workspace "$WS" --force
```

## Workspace Scoping

The direct local runtime uses the active workspace as its boundary for local state and filesystem tools.

- Relative file paths resolve from the workspace root.
- Local derived state is written only under that workspace.
- Different workspaces keep recall, memory promotion, sessions, and logs isolated from one another.

Gateway mode still uses the selected workspace for SmolClaw's own state. Remote MCP tools remain governed by the remote provider's execution policy.

## Recommended Pattern

- One workspace per customer or client engagement
- One workspace per codebase
- One workspace per research topic
- One workspace per long-running investigation

That keeps memories and sessions useful instead of mixing unrelated work into one retrieval pool.

## Example: Gateway Workspace

Run the WebSocket gateway against a dedicated workspace:

```bash
export WS=~/smolclaw-workspaces/acme-research
python -m cli.main serve --workspace "$WS"
```

That gateway instance will use the selected workspace for its sessions, memory exports, graph, database, and logs.
