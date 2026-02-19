---
memory_type: reference
tags:
  - llm-integration
  - claude
  - codex
  - mcp
  - skills
  - agent
created_at: '2026-02-18T22:38:38.282204+00:00'
source_id: intuitionlabs-claude-skills-vs-mcp
---

#reference #llm-integration #claude #codex #mcp #skills #agent

Claude Skills (Anthropic) vs MCP: 
- Claude Skills are modular, task-focused capability packs (folders) containing a SKILL.md (with YAML frontmatter and markdown instructions) plus optional scripts/resources. They teach Claude repeatable workflows, and are instantly available across Claude environments (Claude Code, Claude.ai, API). Key benefits include token efficiency through progressive loading: only metadata is preloaded; full content for relevant skills is injected on demand. Skills can be triggered automatically or by slash-command. They serve for structured organizational knowledge, checklists, code review patterns, etc. 
- Model Context Protocol (MCP) is an open client-server protocol to connect AI hosts (not just Claude) to 3rd party tools, data resources, and prompt templates, using JSON-RPC over HTTP or stdio. MCP exposes functions as Tools, databases as Resources, and templates as Prompts in a vendor-neutral way. This enables LLMs to access real-time APIs and services beyond context window limits, with centralized governance and multi-host reuse. 
- Differences: Skills package instructions and occasionally code for repeatable tasks distinct to the Claude runtime; MCP standardizes outward tool/integration access for any LLM/client. Skills are easier for non-developers; MCP requires server setup but is cross-platform. 
- Interdependence: Skills and MCP are often combined—e.g., Skills encode how to analyze CI data, but require an MCP connection to fetch that data from a CI server. Use Skills for guidance, templates, preference injection; use MCP for external API/tool access.
- Examples: A code review Skill could embed a checklist and style rules; MCP could provide access to external linter tools or codebases.
- Codex (OpenAI) also supports Skills-like task configurations (using TOML/yaml/manifest definitions in agents/openai.yaml), but focuses on platform-specific Plugins and Actions (analogous to MCP Tools). Codex skills often rely more on direct function calling/API wiring. Claude's container/skills model is more flexible for non-coders and emphasizes context/knowledge as much as code.