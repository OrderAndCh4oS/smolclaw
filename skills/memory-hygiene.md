# Memory Hygiene

Guidelines for effective memory management in SmolClaw.

## When to Store

- Store facts, decisions, and preferences that will be useful across sessions.
- Store session summaries as episodes when the conversation contains novel insights.
- Do NOT store ephemeral task details, debugging output, or transient state.

## Memory Types

| Type | Use When | Example |
|------|----------|---------|
| fact | Durable atomic knowledge | "API rate limit is 100 req/s" |
| decision | Choice with rationale | "Chose PostgreSQL because of JSONB support" |
| preference | Personal attribute/style | "User prefers concise responses" |
| episode | Session event summary | "Discussed migration strategy on 2026-03-15" |
| task | Active work in progress | "Currently implementing auth middleware" |
| journal | First-person reflection | "Noticed user gets frustrated with long explanations" |
| reference | External knowledge/docs | "API docs at https://docs.example.com" |

## Tier Guidelines

- **Tier 0 (Identity)**: Reserve for essential knowledge the agent must always have. Examples: user name, role, core project context. Always in context, never decays.
- **Tier 1 (Core)**: Important facts and decisions. Auto-promoted from Tier 2 when importance >= 0.8.
- **Tier 2 (Working)**: Default for session observations. Subject to normal recency decay.

## Tagging

- Use specific, reusable tags: `pricing`, `auth`, `deployment`, not `important` or `misc`.
- Tags improve BM25 retrieval. 2-4 tags per memory is ideal.
- Include the project or domain as a tag when storing cross-project knowledge.

## Search Before Store

Always search memory before storing to avoid duplicates. If a memory already exists, update it rather than creating a new one.
