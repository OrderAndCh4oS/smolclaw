---
memory_type: journal
tags:
  - mcp
  - skills
  - claude
  - codex
  - comparison
  - agent-skills
  - tooling
created_at: '2026-02-19T00:07:07.311874+00:00'
---

#journal #mcp #skills #claude #codex #comparison #agent-skills #tooling

Comprehensive, up-to-date research on MCP (Modular Capability Providers) and Skills: 

1. DEFINITION & CONCEPTUAL DISTINCTION:
- MCP (Modular Capability Provider) exposes tools or API-like function calls (over protocols like JSON-RPC/HTTP) to agents or LLMs, making external actions (read/write, services, integrations) and authentication and permissions possible. MCP is a secure, protocol-based gateway to real-world capabilities for AI agents. (`cra.mr/mcp-skills-and-agents/`)
- Skills are structured, reusable instructions (often as SKILL.md files with YAML frontmatter and Markdown), loaded on demand, that encode behaviors, checklists, domain context, or step-by-step workflows. They optimize LLM prompt use by progressive loading and support modular, composable reasoning or workflows.
- Skills teach the agent behaviors or reasoning patterns; MCP provides the instruments/tools for those skills to operate on actual external resources or APIs.

2. FUNCTIONAL RELATIONSHIP:
- Skills often invoke tools exposed by MCP, blending local knowledge/process with permissioned acts.
- In practice, skills and MCP complement: skills define “how”, MCP provides “with what.” Skills can be purely instructional, or can invoke tools exposed via MCP for real-world action.

3. IMPLEMENTATION: Claude Code vs Codex
- Claude Code: Skills as folders with SKILL.md containing YAML+Markdown (describes triggers, invocation, description, rules, and can bundle scripts, templates etc.). Skills can be discovered from nested directories, auto-loaded for context efficiency, and invoked by trigger or manually (`/skill-name`). Skills can reference tools allowed; MCP tools integrate via allowed-tools in frontmatter. Supports advanced routing (subagents, context fork, access control).
- Codex (OpenAI): Now supports “Agent Skills,” vendor-agnostic, using the same SKILL.md open standard (name, description, allowed-tools frontmatter, Markdown body). Project and globally-scoped skills; discovery is via enumerator scripts that build a JSON index for efficiency. Agent reads only frontmatter metadata of all skills initially, loads full skill body on demand. Tight integration with MCP servers for tool access; skills can specify or require allowed MCP tools; portable across Codex/Claude/Cursor when following open standard.

4. EXAMPLES:
- Example Skill: 'Create Pull Request' skill outlines PR etiquette and triggers 'gh CLI' tool (via MCP) for execution (cra.mr).
- Skill can be instructional ("explain code with diagrams") or operational ("deploy to cloud"—calls an MCP cloud tool).

5. PORTABILITY & STANDARDIZATION:
- The open Agent Skills format (SKILL.md spec) now shared across Claude, Codex, Cursor, and others, supports drag-and-drop or repo sharing; global or project-based skill folders possible (see Glaser, Kanaries docs, VoltAgent/awesome-agent-skills).

6. SUMMARY: MCP and skills address different layers—MCP exposing secure, tool/action APIs, while skills encode reusable agent behaviors and can leverage those tools. Claude and Codex both now support the open SKILL.md format, initially loading only metadata for efficiency, supporting project/global install, and can reference/invoke MCP-exposed tools. 

Core sources: cra.mr/mcp-skills-and-agents/, code.claude.com/docs/en/skills, kanaries.net/docs/codex-vs-claude-code-skills, robert-glaser.de/claude-skills-in-codex-cli/.