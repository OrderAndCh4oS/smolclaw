---
memory_type: journal
tags:
  - mcp
  - skills
  - llm-integration
  - claude
  - codex
  - synthesis
created_at: '2026-02-18T22:43:06.776347+00:00'
---

#journal #mcp #skills #llm-integration #claude #codex #synthesis

Summary of distinctions and relationships between Skills and MCP (as per IntuitionLabs, Skywork, Anthropic docs, etc.):
- Skills represent domain-/task-specific knowledge, procedures, or templates coded for an LLM to use (usually housed in structured files/folders, e.g., SKILL.md for Claude, TOML/yaml for Codex). They capture organizational best practice, review steps, or code patterns, and can optionally include scripts for local execution.
- MCP represents the integration/invocation infrastructure, standardizing access between LLMs and remote/external tools, APIs, or resources. MCP is agnostic to LLM vendor and is designed for scalable governance, discovery, and secure tool exposure.
- Functional relationship: Skills = What & How (instructions, templates, logic local to AI); MCP = Where/Real world (connect AI to actual live data/tools). An LLM can use Skills for reasoning/generation, then trigger MCP to actually call an external API or tool.
- Example: A code review Skill instructs "run linter, summarize output, update status"; MCP provides secure access to the actual linter and CI system APIs to perform those steps and return data to the LLM.
- Claude skills are structured for context efficiency and user curation; Codex skills tend to be more tightly coupled to tool invocations or platform function calling.