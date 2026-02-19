---
memory_type: reference
tags:
  - claude
  - codex
  - mcp
  - agent-skills
  - engineering
created_at: '2026-02-18T22:43:45.781778+00:00'
source_id: kanaries-codex-vs-claude-skills-structure
---

#reference #claude #codex #mcp #agent-skills #engineering

Claude skills (Anthropic) and Codex skills (OpenAI) both allow creation of "skills" but with different file structure, execution context, and extension patterns:
- Claude skills: Folder with at least SKILL.md (YAML/metainfo, then markdown with instructions, templates, etc.), plus optional scripts or supporting files. Progressive loading minimizes token use; local shell/command execution supported in sandboxed environments; subagent forking enables more modular workflows; invocation via slash commands or automatic triggers; and explicit controls for permissions and tool access.
- Codex skills: Typically declared in TOML/config files or through agents/openai.yaml (with UI integration metadata). More directly tied to function calling or API wiring, and often paired with MCP/MCP server for remote tools. Extension features focus on UI, multi-agent orchestration, and marketplace publishing.
- Main differences: Claude's focus is a unified context/knowledge+code module, emphasizing human-readable instructions and cross-tool portability (especially for non-coders/low-code use). Codex skills are API-centric, more tightly bound to code execution/services, and oriented toward "function calling as skill."