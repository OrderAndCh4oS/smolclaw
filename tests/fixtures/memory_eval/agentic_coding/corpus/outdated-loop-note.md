---
source_id: outdated-loop-note
title: Outdated Loop Note
kind: produced
captured_at: "2024-01-01"
entities:
  - SmolClaw
  - Long-running loops
claims:
  - subject: SmolClaw loop state
    predicate: persistence
    object: stateless
relationships:
  - source: SmolClaw
    relation: reconsidered
    target: Stateless loop notes
---

An older design note said SmolClaw could keep loop state stateless and rely on
the active process for progress. That position is stale because the current
design requires durable run state, stop reasons, and resumability.
