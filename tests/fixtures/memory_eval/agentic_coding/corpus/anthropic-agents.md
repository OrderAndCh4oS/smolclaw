---
source_id: anthropic-effective-agents
title: Building Effective Agents
kind: sourced
source_url: https://www.anthropic.com/engineering/building-effective-agents
captured_at: "2025-01-01"
entities:
  - Coding agents
  - Automated tests
  - Environment feedback
relationships:
  - source: Coding agents
    relation: use
    target: Environment feedback
  - source: Automated tests
    relation: provide
    target: Verification evidence
---

Coding agents benefit from environment feedback during implementation.
Automated tests provide verification evidence that a code change still behaves
as intended. [[SmolClaw]] can use that evidence in traces and ledgers.
