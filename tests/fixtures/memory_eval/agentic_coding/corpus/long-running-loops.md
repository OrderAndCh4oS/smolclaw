---
source_id: smolclaw-loop-design
title: SmolClaw Long-Running Loop Design
kind: produced
captured_at: "2026-06-01"
entities:
  - SmolClaw
  - Long-running loops
  - Run state
claims:
  - subject: SmolClaw loop state
    predicate: persistence
    object: durable
relationships:
  - source: SmolClaw
    relation: needs
    target: Run state
  - source: Run state
    relation: tracks
    target: Stop reasons
---

SmolClaw should treat long-running coding work as durable run state. The run
state should track status, turn count, child task ids, pending approvals, stop
reasons, verification evidence, and blockers.
