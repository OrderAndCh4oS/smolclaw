---
memory_type: reference
tags:
  - mcp
  - llm-integration
  - agent
  - protocol
created_at: '2026-02-18T22:41:12.831780+00:00'
source_id: skywork-ai-mcp-summary
---

#reference #mcp #llm-integration #agent #protocol

MCP (Model Context Protocol) is an open standard (originating from Anthropic, now under Agentic AI Foundation) for connecting any LLM to external tools, databases, SaaS APIs, resources, or prompt templates. MCP is designed to standardize and centralize access/control, supporting multi-host and multi-client workflows. It exposes 3 object types: Tools (typed actions/functions), Resources (structured data), Prompts (template contexts). MCP uses JSON-RPC over HTTP+SSE or stdio; supporting both local (low-latency) and remote servers. Ecosystem includes SDKs for server/client. Key advantages: vendor neutrality, centralized governance, and shared secrets/auth policies. Common pattern: Claude or Codex agent connects to MCP server to access tools/data in real time. Use cases: automated code review via external linters, database queries, orchestrated app deployment via CI/CD API, etc.