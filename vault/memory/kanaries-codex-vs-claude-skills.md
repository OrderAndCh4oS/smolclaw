---
memory_type: reference
tags:
  - codex
  - claude
  - skills
  - mcp
  - agent
  - code
created_at: '2026-02-18T22:40:23.390837+00:00'
source_id: kanaries-codex-vs-claude-skills
---

#reference #codex #claude #skills #mcp #agent #code

From Kanaries (2026): Codex (OpenAI) and Claude Code (Anthropic) both implement skill systems but with distinct discovery, config, and invocation patterns:
- Codex: Skills are typically specified in TOML/yaml under agents/skills/ or in agents/openai.yaml (for UI/settings metadata). Also tightly integrated with MCP for remote tool calls (server-based APIs), and supports per-project or global skill configs. Codex extends skill invocation with UI metadata and MCP server extension. Has less flexible shell/sandbox isolation than Claude.
- Claude Code: Skills are in .claude/skills/ as folders with SKILL.md (YAML + markdown), supporting automatic progressive loading, subagent context forking, shell command preprocessing, and fine-grained tool access control. 
- Key differences: Claude skills add subagent context forking (run skills as microagents); Codex focuses more on UI integration and outside-MCP extension via openai.yaml. Claude puts more emphasis on inline knowledge/context manipulation (templates/examples in skills) versus Codex's focus on MCP/server tooling/integration. 
- Both support skill sharing; but Claude emphasizes code/knowledge fusion, while Codex treats skill as API invocation wiring.