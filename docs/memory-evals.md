# Memory And Knowledge-Graph Evals

SmolClaw can now run deterministic corpus-memory evals before involving a live
model. These evals check whether produced docs, sourced articles, research notes,
and evidence records can support provenance-first answers.

The eval answers four questions for each prompt:

- Did local retrieval surface the expected source notes?
- Did the corpus expose the expected entities?
- Did the graph contain the expected relationships?
- Did the retrieved evidence include required terms?
- Did corpus hygiene checks find expected stale or conflicting evidence?

This is intentionally separate from the coding-agent eval harness. It tests the
quality and structure of long-term memory material, not model behavior.

## Memory-On Versus Memory-Off Coding Fixture

The lightest coding usefulness check is deterministic and does not call live
LLMs. `tests/fixtures/agent_tasks/csv_memory_policy` contains a small parser
task where the prompt asks for CSV row handling, but the project decision to
preserve empty fields exists only as memory evidence. The scripted eval applies
one plausible memory-off patch and one memory-on patch, runs the same tests for
both, and passes only when memory-on succeeds while memory-off fails.

Run it through pytest:

```bash
python -m pytest tests/test_memory_coding_eval.py
```

This is not a replacement for a live model benchmark. It is a cheap regression
that proves the fixture shape can express "memory changed the coding outcome"
before adding provider-dependent runs.

## Run The Sample

```bash
smolclaw memory-eval tests/fixtures/memory_eval/agentic_coding/memory-eval.yaml --output .smolclaw/stores/evals/memory
```

The default mode is deterministic and offline. It prints a JSON report and writes:

```text
.smolclaw/stores/evals/memory/agentic_coding_memory.memory-eval.json
```

To exercise live SmolRAG ingestion, embeddings, BM25, vector retrieval, and graph
lookup against the same suite:

```bash
smolclaw memory-eval tests/fixtures/memory_eval/agentic_coding/memory-eval.yaml --mode rag --output .smolclaw/stores/evals/memory
```

`--mode rag` uses the configured memory LLM and embedding provider, so it may
require provider credentials. Tests inject an offline fake provider to keep CI
deterministic.

To ask a model to compose answers from retrieved corpus sources and grade whether
it cites the expected evidence:

```bash
smolclaw memory-eval tests/fixtures/memory_eval/agentic_coding/memory-eval.yaml --mode answer --model gpt-5.4-mini --output .smolclaw/stores/evals/memory
```

`--mode answer` retrieves sources with the deterministic corpus index, gives the
model source IDs, source kinds, URLs, and excerpts, then checks whether the final
answer cites the expected source IDs or URLs and names the expected source kinds
such as `produced` or `sourced`.

The standalone script remains available for direct development use:

```bash
python scripts/run_memory_eval.py tests/fixtures/memory_eval/agentic_coding/memory-eval.yaml
```

## Run The Project Docs Suite

The repo also includes a non-toy suite backed by the current project docs:

```bash
smolclaw memory-eval docs/smolclaw-memory-eval.yaml --output .smolclaw/stores/evals/memory
```

This suite references the current docs that remain after the project pivot:
the system design spec, roadmap, workspace guide, memory-eval guide, and the
suite file itself. The suite adds metadata in YAML rather than copying the
documents, so it exercises the real writing while still declaring the graph
entities, relationships, claims, and freshness expectations the memory layer
should preserve.

## Suite Reports And Baselines

Pass multiple suites to get an aggregate report with check rates and score
deltas:

```bash
smolclaw memory-eval suite-a.yaml suite-b.yaml --baseline .smolclaw/stores/evals/memory/baseline.json
```

Fail the run when any suite drops below its baseline by more than the allowed
amount:

```bash
smolclaw memory-eval suite-a.yaml suite-b.yaml --baseline baseline.json --max-score-drop 0
```

Write the current aggregate report as a future baseline:

```bash
smolclaw memory-eval suite-a.yaml suite-b.yaml --write-baseline .smolclaw/stores/evals/memory/baseline.json
```

The aggregate report includes:

- `suite_count`, `passed`, `failed`, and `average_score`;
- per-check pass rates across all questions;
- per-suite `current`, `baseline`, and `delta` scores;
- `regressions` when `--max-score-drop` fails a baseline comparison;
- the full individual reports.

Exit codes:

- `0`: all questions passed.
- `1`: suite loading or execution failed.
- `2`: the eval ran but at least one question failed.

## CI Entrypoint

Use the deterministic CI wrapper for local or repository CI checks:

```bash
python scripts/ci_memory_eval.py
```

By default it runs:

- `tests/fixtures/memory_eval/agentic_coding/memory-eval.yaml`
- `docs/smolclaw-memory-eval.yaml`

Environment variables:

- `SMOLCLAW_MEMORY_EVAL_SUITES`: whitespace-separated suite paths.
- `SMOLCLAW_MEMORY_EVAL_OUTPUT`: report output directory, defaults to `.smolclaw/stores/evals/memory-ci`.
- `SMOLCLAW_MEMORY_EVAL_BASELINE`: optional baseline JSON.
- `SMOLCLAW_MEMORY_EVAL_MAX_DROP`: allowed score drop when a baseline is set, defaults to `0`.
- `SMOLCLAW_MEMORY_EVAL_WRITE_BASELINE`: optional path to write the current aggregate suite report.

The repository `scripts/test_all.sh` runs this deterministic memory eval suite
after unit tests.

## Corpus Files

Corpus files are markdown with YAML frontmatter. The most useful fields are:

```yaml
---
source_id: anthropic-effective-agents
title: Building Effective Agents
kind: sourced
source_url: https://www.anthropic.com/engineering/building-effective-agents
author: Anthropic
trust_level: primary
evidence_type: article
entities:
  - Coding agents
  - Automated tests
relationships:
  - source: Automated tests
    relation: provide
    target: Verification evidence
claims:
  - subject: Coding agent verification
    predicate: evidence
    object: automated tests
captured_at: "2025-01-01"
---
```

The runner also reads Obsidian-style `[[Wiki Links]]` and `#tags` from markdown
bodies as graph signals.

## Suite Format

```yaml
id: agentic_coding_memory
corpus:
  - path: corpus/long-running-loops.md
  - path: corpus/anthropic-agents.md
questions:
  - id: coding_agent_verification
    query: What sourced evidence supports using automated tests for coding agents?
    expected_sources:
      - anthropic-effective-agents
    expected_entities:
      - Coding agents
      - Automated tests
    expected_relationships:
      - source: Automated tests
        relation: provide
        target: Verification evidence
    required_terms:
      - environment feedback
staleness:
  - id: article_capture_is_current_enough
    source_id: anthropic-effective-agents
    expected: fresh
    max_age_days: 730
    as_of: "2026-06-24"
contradictions:
  - id: loop_state_persistence_conflict
    subject: SmolClaw loop state
    predicate: persistence
    sources:
      - smolclaw-loop-design
      - outdated-loop-note
```

Use this to test whether memory can ground answers such as:

- why an architecture decision was made;
- which sources support a current architecture claim;
- which use cases a feature is intended to serve;
- whether a claim is unsupported by the current corpus;
- whether a source is stale according to its `captured_at` metadata;
- whether two produced or sourced records make conflicting structured claims;
- whether a relationship exists between concepts, sources, and decisions.

## Design Notes

The default eval is deterministic by design. It does not call an LLM, create
embeddings, or mutate SmolRAG. That makes failures easier to interpret:

- missing source means the corpus or query coverage is weak;
- missing entity means the note lacks graph metadata;
- missing relationship means the knowledge graph cannot support the claim;
- missing term means retrieved evidence is too thin for the expected answer.

`--mode rag` uses the same suite to evaluate live SmolRAG ingestion and
retrieval. The report separates `vector_sources` and `bm25_sources` so failures
show whether semantic retrieval, keyword retrieval, graph indexing, or source
mapping lost the evidence.

`--mode answer` is intentionally a citation/provenance grader, not a full prose
quality judge. It proves whether the answer names the expected evidence and
distinguishes produced project material from sourced external material. It does
not yet grade factual completeness beyond the existing source/entity/relationship
and required-term checks.

Staleness and contradiction checks are deterministic corpus-hygiene gates.
Staleness compares a source's `captured_at` date with the suite's `as_of` date
and `max_age_days`. Contradiction checks compare frontmatter `claims` with the
same normalized `subject` and `predicate`; different `object` or `polarity`
values count as a conflict when the expected source set is present. These checks
do not adjudicate which claim is correct. They prove the memory store can
surface known conflicts and stale evidence for the agent workflow to handle.
