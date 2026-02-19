# Modular Capability Providers vs. Skills: Architecting Composable AI Agents in Claude Code and Codex

## Introduction
AI agents are rapidly evolving from language models that simply respond to prompts into dynamic assistants that interact with real-world code, infrastructure, and external APIs. This leap in capability is made possible by decoupling two architectural elements: *skills*—modular know-how that encodes logic—and *Modular Capability Providers* (MCPs), which give agents secure and standardized access to live tools and data. For engineering leads building in Claude Code, Codex, or any advanced agent framework, mastering the differences and what each layer brings is essential for robust, maintainable systems.

This article dives deep into those distinctions, explains how skills and MCPs support each other, and unpacks implementation patterns across Claude Code and Codex. Expect actionable guidance, clear technical detail, and reusable patterns you can adapt in your own teams.

## 1. Skills and MCPs: Clear Definitions

### What are MCPs (Modular Capability Providers)?
MCP is an open protocol and set of standards which enables agents—especially large language models (LLMs)—to invoke external tools, scripts, APIs, or services in a composable, secure, and transparent way. Think of MCP as the plumbing that carries commands from the agent out to external systems, and responses back in. Key design features:
- **API/Transport Layer:** MCP often specifies JSON-RPC or HTTP as the data protocol between the agent and an MCP server, which acts as a hub for tools.
- **Discovery/Metadata:** MCPs describe exposed tools with rich metadata (capabilities, description, security scope, etc.).
- **Security:** Authentication, authorization, and auditing are built in to let teams control exposure of sensitive actions.
- **Standardization:** With MCP, tool authors expose actions (like "push commit", "fetch PR") that any compatible agent can discover and invoke.

### What are Skills?
Skills are the packaged know-how that lives inside the agent. A skill is usually a folder containing a `SKILL.md` file with a YAML header and Markdown body:
- **YAML Frontmatter:** Description, triggers, allowed tools (via MCP), and configuration.
- **Markdown Body:** Stepwise instructions, procedural logic, or workflow decompositions. Sometimes includes templates or helper scripts.
- **Who Writes Skills:** Domain experts, developers, even non-programmers can write skills—making them both reusable and inspectable.

Skills often reference which MCP-exposed tools they're allowed to call, letting them drive interactions with live systems within safe, governable limits.

## 2. How They Differ—and How They Work Together

| Aspect          | MCP                          | Skills                            |
|-----------------|------------------------------|------------------------------------|
| Role            | Supplies capabilities/tools  | Provides procedural know-how       |
| Format          | API/schema (e.g., JSON-RPC)  | SKILL.md (YAML + Markdown, scripts)|
| Use Case        | Tool invocation & access     | Task/workflow decomposition        |
| Author          | Platform/devops engineers    | Developers & domain specialists    |
| Granularity     | Action/API endpoint          | Full task/checklist/reasoning      |
| Example         | "Query database"            | "Review PR for security issues"   |

In summary: **MCPs give agents hands; skills give them brains.**

*Integration Example*: A “Release Notes Generation” skill defines a Markdown workflow (fetch PRs > summarize changes > collate output). Where steps need live data, it invokes MCP tools (e.g., `github.fetch_prs`). The agent combines both: it reasons through the workflow, then acts where delegated.

## 3. Claude Code vs. Codex: Skill System Requirements & Patterns

### Claude Code (Anthropic)
- **Skill Layout:** Each skill in its directory: `SKILL.md` (YAML+MD), optional helpers.
- **Skill Loading:** Lightweight context loading—agent scans YAML first, only loads Markdown when selected to minimize context overhead.
- **Invocation:** Claude selects skills using pure natural language reasoning and metadata matching—there are no brittle pattern-matching rules.
- **MCP Integration:** Skills can specify permissible tools (via YAML) exposed by an MCP server. Claude orchestrates tool calls per the Markdown recipe.

### Codex (OpenAI/ITECS)
- **Skill Format:** Follows open Agent Skills format (`SKILL.md`).
- **Skill Discovery:** Indexes all skills at YAML level; Markdown/workflow loaded at runtime.
- **Skill Features:** Metadata can tune invocation (implicit/explicit), restrict by input/output types, specify required MCP tools, etc.
- **MCP Integration:** YAML specifies which tools (from any MCP) the skill expects; Codex’s agent runtime invokes as needed.

### Shared Patterns
- Both now converge around an open skill format (SKILL.md, YAML+MD). One skill can run unmodified on both Claude Code and Codex.
- Skills act as portable “brains”—MCPs as universal “hands,” supporting cross-platform agent ecosystems.

## 4. Implementation Best Practices
- **Always Decouple:** Put reusable procedures/logic in skills; sandbox actions inside MCP tools.
- **Keep Skills Focused:** Single-responsibility; ensure metadata is concise and accurate for efficient matching.
- **Progressive Loading:** Only pull Markdown/workflow logic into context when needed.
- **Security by Default:** Let MCP enforce permissions—never embed secrets or risky logic in skills themselves.
- **Catalog and Share:** Reuse and review skills across teams via open catalogs (e.g., `openai/skills`, `anthropics/skills`).

## 5. Practical Examples for Real-World AI Workflows

### Example 1: Data Quality Assurance Agent
**Skill:** "Data QA Checklist"
- Steps include "Fetch new records" (calls MCP `db.query`), "Run validation script" (calls `validation-tool`), "Summarize findings" (local reasoning).
- Benefit: Agents quickly adapt to new backends—just swap in new MCPs.

### Example 2: Automated Release Management
**Skill:** "Generate Release Notes"
- Step-by-step workflow (fetch PRs via MCP `github`, summarize, post release notes).
- MCPs modularize integrations; skills structure reviews and summaries, maximizing reuse and transparency.

## 6. Conclusion: Designing Robust, Modular AI Agents

The best agent systems keep actions and know-how modular—skills as portable logic, MCPs as secure gateways to real-world effects. Claude Code and Codex are converging around open skill standards, enabling developers to build once and deploy anywhere, while gating sensitive integrations via MCP for auditability and control.

**Actionable Summary for Teams:**
- Use SKILL.md for maximal cross-platform reuse.
- Always expose tools via a secure MCP layer—never hard-code credentials or workflows.
- Encourage domain experts to write/maintain skills; let devops focus on tool/MCP maintenance.
- Share and catalog your skills for rapid onboarding and quality assurance.

**Further Reading**
- [Anthropic: Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [OpenAI Skills Catalog](https://github.com/openai/skills)
- [Model Context Protocol (official docs)](https://modelcontextprotocol.io/docs/learn/architecture)
- [Skills Explained: Claude blog](https://claude.com/blog/skills-explained)
