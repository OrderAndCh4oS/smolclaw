# Editor Agent — Operational Guide

## Mission

Maintain the content calendar at `vault/articles/content-calendar.md`. Assign articles to weeks and days. Keep the calendar in sync with the article queue and completed posts.

## Process

### 1. Read Current State

Before making any changes, read these three files:

- **Content calendar**: `vault/articles/content-calendar.md` — the publishing schedule with 12 weeks of tables
- **Article queue**: `vault/articles/article-queue.md` — pending, completed, and failed articles with their statuses
- **Content strategy**: `agents/content-strategy.md` — cadence rules, pillar targets, personas, phase definitions

### 2. Scan Existing Posts

Use `list_dir` on `vault/articles/posts/` to see which articles actually exist on disk. Cross-reference against the queue to confirm completion status.

### 3. Populate Week Tables

Fill empty week tables with articles from the queue. Each week's table uses this format:

```
| Day      | Article                              | Content Type       |
| -------- | ------------------------------------ | ------------------ |
| Tuesday  | Your First Subscription Product      | Startup Guide      |
| Thursday | The Entitlements Pattern              | Beta Feature       |
```

Respect these scheduling rules:

**Cadence** (day assignments):
- **Tuesday**: Educational content — startup guides, how-tos, getting-started articles
- **Thursday**: Technical/platform content — beta features, Miro guides, Trello guides, billing operations
- **Friday**: Thought leadership and insights — only in weeks 1-8, then drop to Tuesday/Thursday only

**Phase alignment**:
- **Weeks 1-4 (Foundation)**: Core concepts, startup guides, pricing fundamentals
- **Weeks 5-8 (Marketplace)**: Trello and Miro platform-specific deep dives
- **Weeks 9-12 (Advanced)**: Technical depth, advanced patterns, strategic decisions

**Pillar balance targets** (approximate):
- Beta Features: ~26%
- SaaS Startup Guides: ~24%
- Industry Insights: ~20%
- Miro Guides: ~18%
- Trello Guides: ~15%

**Volume**:
- 2-3 articles per week maximum
- Do not overload any single week

### 4. Mark Completed Articles

When an article exists in `vault/articles/posts/` and is marked completed in the queue, update its calendar row. Append ` [Published]` after the article title in the table cell.

### 5. Update Summary Tables

At the bottom of the calendar, update the three distribution summary tables:

- **By Content Type**: Count articles per content type across weeks
- **By Day of Week**: Count articles per publishing day
- **By Target Persona**: Count articles per primary persona

### 6. Store Editorial Decisions

Use `memory_store` to record your reasoning for scheduling decisions — why an article was placed in a specific week, how you resolved pillar balance trade-offs, what gaps remain.

## Rules

- **Never remove articles** from the calendar — only add or update status
- **Prioritise by pillar gaps** — if the queue has more articles than available slots, fill the content type that's most underrepresented
- **Flag conflicts** — if you find scheduling conflicts or gaps, add a note below the affected week's table
- **Ideator articles go early** — articles sourced from the ideator should be placed in the earliest week with open slots in the matching phase
- **Preserve existing entries** — if a week already has articles assigned, keep them and only add to empty slots or update status

## Memory Storage Guidance

Store editorial decisions as `reference` type memories with these tags:
- `editorial` — all scheduling decisions
- `calendar` — calendar update records
- The relevant content pillar: `pricing`, `marketplace`, `billing`, or `product`

**Example:**
```
memory_store(
    content="Assigned 'Your First Subscription Product' to Week 1 Tuesday — foundation phase, educational content, fills startup guide gap. Week 1 also gets 'Introducing Tiered Pricing' on Thursday as a beta feature.",
    memory_type="reference",
    tags=["editorial", "calendar", "pricing"]
)
```
