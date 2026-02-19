---
memory_type: reference
tags:
  - mcp
  - llm-integration
  - agent
  - architecture
created_at: '2026-02-18T22:42:15.439926+00:00'
source_id: mcp-universe-arxiv
---

#reference #mcp #llm-integration #agent #architecture

The Model Context Protocol (MCP), introduced by Anthropic in 2024 and now stewarded by AAIF, benchmarks a new standard for LLM integration by allowing not just prompt extension, but real-time invocation of external tools/resources. MCP is described as the "USB-C of AI," solving the issue of fragmented, bespoke LLM integrations. Main architectural principle: context (external resources, functions, tools) is injected not by manual prompt stuffing, but discoverable and callable by the LLM via formal APIs. This enables LLMs (including Claude or Codex) to autonomously source real-time data from a CI/CD system, execute complex queries via a solver API, or fetch the latest docs from a document server for context-aware completions. MCP is especially powerful for agent frameworks needing composable, multi-step tool usage. MCP usage patterns often complement skills/templates: skills encode the procedure, MCP provides API access to execute it.