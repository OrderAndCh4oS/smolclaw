---
memory_type: reference
tags:
  - claude
  - skills
  - engineering
created_at: '2026-02-18T22:39:44.619638+00:00'
source_id: anthropic-claude-skills-docs
---

#reference #claude #skills #engineering

Claude Skills are modular, reusable folders used to teach Claude repeatable workflows (Markdown instructions + optional scripts). They include a SKILL.md file (with YAML frontmatter for metadata) and can be loaded automatically or via slash-command. Skills can encode company standards, coding conventions, or step-by-step action guidance. Examples: 'Explain code with diagrams', 'Apply API naming conventions', 'Deploy app to production'. Key features include:
- Progressive loading (token efficient; only relevant skill content is injected on demand).
- Fine-grained control via YAML fields (e.g., restrict user or model invocation, run as subagent, allow/disallow tool access).
- Skills live in user, team, or project folders, with clear override precedence.
- Can include supporting files (templates, scripts, reference docs).