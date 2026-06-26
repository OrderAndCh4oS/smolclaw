# SmolClaw Test Suite

The test suite covers the local coding-agent harness, explicit dependency seams,
runtime composition, tools, memory, evals, CLI/TUI behavior, and state stores.
Normal unit coverage should be deterministic and should not require live provider
credentials.

## Running Tests

Install development dependencies from the project root:

```bash
pip install -e ".[dev]"
```

Run the full suite:

```bash
python -m pytest
```

Run common focused groups:

```bash
python -m pytest tests/test_runtime.py tests/test_agent_factory.py tests/test_agent_loop.py
python -m pytest tests/test_tools_command.py tests/test_permissions.py tests/test_checkpoints.py
python -m pytest tests/test_mcp_client.py tests/test_tools_web.py tests/test_llm_factory.py
python -m pytest tests/test_agent_eval.py tests/test_memory_eval.py
```

## Coverage Areas

- Runtime configuration and dependency injection:
  `test_runtime_config.py`, `test_command_adapters.py`, `test_llm_factory.py`,
  `test_runtime.py`, and `test_runtime_state.py`.
- Agent loop and factory behavior:
  `test_agent_loop.py`, `test_agent_factory.py`, `test_context_builder.py`, and
  `test_tool_completion.py`.
- Tool registry, middleware, safety, permissions, checkpoints, and evidence:
  `test_tool_registry.py`, `test_tool_middleware.py`, `test_tools_safety.py`,
  `test_permissions.py`, `test_checkpoints.py`, and `test_evidence.py`.
- CLI, TUI, gateway, worktree, and work-loop flows:
  `test_cli_multiagent.py`, `test_cli_tui.py`, `test_gateway.py`,
  `test_worktree.py`, and `test_work_loop.py`.
- SmolRAG, memory documents, graph/vector/BM25 stores, contradictions, and
  ingestion:
  `test_smol_rag.py`, `test_memory_documents.py`, `test_graph_store.py`,
  `test_vector_store.py`, `test_bm25_store.py`, `test_contradiction*.py`, and
  `test_ingest_text.py`.
- Whole-agent and memory evals:
  `test_agent_eval.py`, `test_memory_eval.py`, and
  `test_memory_coding_eval.py`.

## Test Design Rules

- Use explicit constructors, provider objects, factories, context managers, or
  dependency containers for fakes.
- Do not patch module globals or object attributes for dependency substitution.
- `monkeypatch.setenv`, `monkeypatch.delenv`, and `monkeypatch.chdir` are
  acceptable only when the behavior under test is environment or cwd handling.
- Prefer fake clients/runners passed through public seams over mutating module
  globals.

The patch-free dependency substitution acceptance check is documented in
`docs/system-design-spec.md` and should return no matches under `tests/`.
