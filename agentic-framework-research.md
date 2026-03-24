# Agentic Framework Research: What SmolClaw Is Missing

Comparative analysis of OpenClaw, Claude Code, NanoClaw, and OpenCode against SmolClaw. Focused on reasoning patterns, memory architecture, and agent intelligence.

---

## OpenClaw

**Type**: Full-featured autonomous agent platform
**Stack**: TypeScript, Anthropic Agent SDK
**Repo**: https://github.com/openclaw

### Identity & Persona

OpenClaw uses a tiered identity system:

- **SOUL.md** — Immutable identity file. "Who I am." Loaded first every session. Defines personality, values, tone, behavioral boundaries. Human-authorized changes only.
- **USER.md** — Human-maintained stable context. Preferences, background, recurring needs.
- **AGENTS.md** — Agent configuration and delegation rules.
- **TOOLS.md** — Available capabilities and their constraints.

SmolClaw equivalent: `AGENT.md` + `agents.yaml` persona. Much thinner — no separate identity vs preferences vs configuration layers.

### Memory Architecture

Three-tier memory with different persistence characteristics:

- **T0: SOUL (Identity)** — `SOUL.md`, `IDENTITY.md`. Immutable. Never decays. "Who I am."
- **T1: Core Memory (Evergreen)** — `MEMORY.md`, `memory/roadmap.md`. No decay. Curated knowledge. "What I must never forget."
- **T2: Working Memory (Temporal)** — `memory/2026-03-19.md` dated files. Half-life: 23 days. "What happened recently."

Critical detail: Memory files are accessed **on demand** via tools, NOT auto-injected into context. This saves tokens — only relevant memories are loaded when the agent explicitly searches.

SmolClaw equivalent: Single retrieval layer (vector + KG + BM25) with promote/decay. No tier separation. Context auto-injected into system prompt (4K token budget). No distinction between "must never forget" and "happened recently."

### Reasoning Loop

OpenClaw implements a **ReAct (Reason + Act) pattern**:

```
Thought → Action → Observation → Thought → ...
```

Key features:
- **Extended thinking**: Configurable reasoning depth (off / minimal / low / medium / high / xhigh). Higher levels = more tokens spent reasoning before acting.
- **Self-correction**: Agent observes whether actions worked and adjusts strategy.
- **Checkpoints**: Every N steps, saves full agent state for backtracking if something goes wrong.
- **Working memory management**: Lightweight relevance scoring keeps only the most relevant items for the current step.

SmolClaw equivalent: None. SmolClaw's loop is `call LLM → execute tools → feed results back → repeat`. No explicit thinking step, no observation analysis, no strategy adjustment, no checkpoints.

### Skills System

Skills are composable capabilities delivered as `SKILL.md` files (YAML frontmatter + markdown instructions). Same format works across Claude Code, Cursor, GitHub Copilot, Gemini CLI, NanoClaw. Skills can be:
- Added via PR/branch
- Shared across forks
- Self-generated (agent writes its own skills when it lacks one)

SmolClaw equivalent: Tool system (code-level plugins). No skill-as-prompt pattern. Agent cannot create or modify its own capabilities.

### Multi-Channel

Gateway routes messages from Slack, WhatsApp, Telegram, Discord, email. Each channel maps to the same agent brain.

### Scheduled Tasks (Heartbeat)

HEARTBEAT.md defines recurring tasks. Agent can act autonomously on a schedule — check inboxes, run reports, send reminders.

---

## Claude Code

**Type**: Agentic coding CLI
**Stack**: TypeScript (closed-source harness around Claude)
**Docs**: https://code.claude.com/docs

### System Prompt

2,896-token core system prompt with 20 built-in tool descriptions. Compact but highly engineered — every word chosen for effectiveness.

### Specialized Sub-Agents

Claude Code runs different agent types for different tasks:
- **Plan agent** (633 tokens) — Designs implementation strategy before coding
- **Explore agent** (516 tokens) — Searches and understands codebases
- **Task agent** (294 tokens) — Executes discrete work items

This means the system adapts its reasoning approach to the task type. A question gets a lightweight exploration. A bug fix gets a plan → fix → verify cycle. A refactor gets extensive verification.

SmolClaw equivalent: Multi-agent spawn exists, but agents aren't specialized by task type. Every task gets the same generic persona.

### Adaptive Reasoning Loop

Claude Code's loop adjusts based on what it learns at each step:
- Chains dozens of actions together
- Course-corrects along the way
- Questions → context gathering only
- Bugs → iterative fix/verify cycles
- Refactors → extensive verification passes

SmolClaw equivalent: Fixed loop. Same behavior regardless of task type. No adaptation.

### Context Management

- Automatic context compression as conversation approaches limits
- Persistent memory via CLAUDE.md files
- Tool results managed to avoid context bloat

---

## NanoClaw

**Type**: Lightweight personal AI assistant
**Stack**: TypeScript, Anthropic Agent SDK
**Repo**: https://github.com/qwibitai/nanoclaw

### Philosophy

"Skills over features." NanoClaw is ~few hundred lines of core TypeScript. It delegates all reasoning to Anthropic's Claude Agent SDK. The framework is thin — it handles channels, isolation, and persistence. Claude handles thinking.

### Container Isolation

Every group/channel gets its own Linux container with:
- Its own `CLAUDE.md` memory file
- Its own filesystem
- Its own session state
- Mounted sandbox (not application-level sandboxing)

SmolClaw equivalent: Path-sandboxed tools. No container isolation. Single-user.

### Skills System

Same SKILL.md format as OpenClaw/Claude Code. Skills are instructional files, not code. Agent capabilities are composed from prompts, not compiled from source.

### Channels

WhatsApp, Telegram, Slack, Discord, Gmail out of the box. Self-register at startup — orchestrator connects whichever ones have credentials present.

### Memory

Per-group CLAUDE.md files. Recently adding semantic RAG (PR #560). Much simpler than SmolClaw's KG + vector + BM25 approach.

---

## OpenCode

**Type**: Open-source AI coding CLI (Claude Code alternative)
**Stack**: Go
**Repo**: https://github.com/opencode-ai/opencode

### Model Flexibility

Supports 75+ LLM providers including local models via Ollama. Can switch models mid-session without losing context. SmolClaw supports OpenAI + Anthropic only.

### Reasoning Loop

ReAct-style loop with built-in tools: grep, terminal, file read/write, web search. Same thought → action → observation pattern as OpenClaw.

### Architecture

- User Interface Layer (TUI, IDE plugins, CLI)
- AI Model Engine (open-weight LLMs)
- Plugin System (sandboxed execution)
- Persistent Memory Store (preferences + session history)

### Key Differentiator

Privacy-first. Everything can run locally. No data leaves your machine if you use local models.

---

## Patterns SmolClaw Is Missing

### ~~1. Identity / SOUL.md~~ — DONE

AGENT.md rewritten with personality, anti-patterns ("What NOT to Do"), behavioral guidance ("act don't narrate", "have opinions"), reasoning methodology, tool selection guidance. Per-agent bootstrap files (researcher.md, coder.md). Composable via agents.yaml.

### ~~2. Tool Selection Guidance~~ — DONE

All tool descriptions enriched with when/how guidance. memory_search, memory_graph_query, memory_recall, memory_store, web_search, web_fetch, contradiction_review all updated.

### ~~3. Context Budget~~ — DONE

Configurable per-agent via `context_budget` in AgentConfig. Default raised to 8K tokens.

### ~~4. Specialized Sub-Agents~~ — DONE

Three agent profiles (default, researcher, coder) with different personas, bootstrap files, tool sets, and settings.

### ~~5. Reflection~~ — DONE

Config-driven reflection prompt injected after tool rounds. Asks agent to assess completeness and verification before responding.

### ~~6. Token Tracking~~ — DONE

Full audit trail: per-call, per-turn, per-session. Real-time events. Persisted JSON. Per-category breakdown.

### ~~7. Streaming~~ — DONE

Token-by-token streaming for both OpenAI and Anthropic. CLI, gateway, and auth system bridge all support it.

### 8. ReAct Reasoning Loop (Critical — next up)

**What it is**: Before taking an action, the agent explicitly reasons about what it should do and why. After observing the result, it reflects on whether it worked and what to do next.

**Who has it**: OpenClaw, Claude Code, OpenCode

**SmolClaw today**: Tool-use loop with post-hoc reflection prompt. But no explicit planning step before acting, no observation analysis after tool results, no strategy adjustment on failure.

**Impact**: Agent can reflect but can't plan ahead or self-correct.

### 9. Memory Tiers (High)

**What it is**: Separating memory into tiers with different persistence, decay, and access patterns. Immutable identity (T0), curated evergreen knowledge (T1), working/temporal memory with decay (T2). On-demand access instead of auto-inject.

**Who has it**: OpenClaw (T0/T1/T2), Claude Code (context compression)

**SmolClaw today**: Single flat retrieval with configurable budget (8K). Taxonomy weights and promote/decay exist but no tier separation.

### 10. Skills-as-Prompts (Medium)

**What it is**: Agent capabilities defined as markdown instruction files. Composable, shareable, agent can write its own.

**Who has it**: OpenClaw, NanoClaw, Claude Code

**SmolClaw today**: Bootstrap files per agent (similar concept), but no runtime skill loading or agent self-authoring.

### 11. Extended Thinking / Reasoning Budget (Medium)

**What it is**: Configurable reasoning depth via Anthropic extended thinking or OpenAI reasoning tokens.

**Who has it**: OpenClaw (6 levels), Claude Code (built-in)

**SmolClaw today**: No reasoning budget concept.

### 12. Self-Correction & Checkpoints (Medium)

**What it is**: Agent detects failed approaches and tries alternatives. Checkpoints allow backtracking.

**Who has it**: OpenClaw (checkpoints every N steps), Claude Code (course correction)

**SmolClaw today**: Error fed back to LLM, but no explicit retry/backtrack mechanism.

### 13. Auth Awareness (New)

**What it is**: Agent knows what auth capabilities it has — which tools are pre-approved, which need human approval, token types (single-use vs reusable), expiry windows.

**Who has it**: OpenClaw (tool policy in system prompt), NanoClaw (container-level permissions)

**SmolClaw today**: Agent has no awareness of the JWT auth layer. MCP tools request tokens transparently but the agent can't reason about approval requirements or batch operations under a reusable token.

### 14. Multi-Provider Model Support (Low)

**What it is**: Support for many LLM providers, including local models via Ollama.

**Who has it**: OpenCode (75+ providers), OpenClaw (multiple)

**SmolClaw today**: OpenAI + Anthropic only.

### 15. Platform Features (Low)

Messaging channels (Slack, Telegram, etc.), scheduled jobs / heartbeat, multi-user / multi-tenant, cost controls / budget enforcement. See Phase 6.

---

## Direct Agent Prompt Comparison

Side-by-side comparison of the actual system prompts and identity files used by each framework.

### Identity / Opening Line

**OpenClaw** (SOUL.md template):
> Be genuinely helpful, not performatively helpful. Skip the "Great question!" and "I'd be happy to help!" — just help.
> Have opinions. You're allowed to disagree, prefer things, find stuff amusing or boring.
> Be resourceful before asking. Try to figure it out. Read the file. Check the context. Search for it.

**Claude Code** (main system prompt):
> You are an interactive CLI tool that helps users with software engineering tasks.

**NanoClaw** (CLAUDE.md):
> NanoClaw is a personal Claude assistant built as a single Node.js orchestrator with a skill-based channel system. *(Focuses on architecture, not personality — delegates identity to the SDK.)*

**OpenCode** (provider-specific prompt):
> *(Assembles dynamically from environment block + AGENTS.md + provider template. No single static identity line — identity comes from configuration.)*

**SmolClaw** (AGENT.md):
> You are SmolClaw, an agentic assistant with deep, persistent, associative memory backed by a knowledge graph.

### Reasoning / Methodology Instructions

**OpenClaw** (from agent-prompts.md):
- Research agent: "Gather, analyze, and synthesize information from multiple sources. Prioritize thorough source checking, cite sources with URLs, compare perspectives, identify information gaps."
- Coordinator agent: "Break down complex tasks, delegate to specialists, and synthesize results."
- Monitor agent: "Perform lightweight checks and report status without taking action. Use read-only operations preferentially."

**Claude Code**:
> You MUST answer concisely with fewer than 4 lines. Minimize output tokens as much as possible.
> Search to understand the codebase, implement solutions, verify with tests, and run lint/typecheck commands before finishing.
> NEVER assume that a given library is available — verify dependencies first.

**NanoClaw**:
> Run commands directly — don't tell the user to run them.
> *(Minimal reasoning instructions — delegates to Claude SDK's built-in reasoning.)*

**OpenCode**:
> Advanced agents use a "chain-of-thought" reasoning step inspired by advanced prompting techniques, where the agent explicitly formulates a plan before acting.
> *(Reasoning is architectural, not prompt-level — the ReAct loop is in code, not instructions.)*

**SmolClaw** (AGENT.md + researcher.md):
> Search before assuming. Check memory first, then the web. Don't guess when you can look it up.
> Verify claims against sources. Cross-reference information when multiple sources are available. Flag contradictions.
> Break complex questions into steps. Decompose multi-part questions. Answer each part, then synthesise.
> Researcher methodology: Decompose → Search memory → Search web → Cross-reference → Synthesize → Verify → Store.

### Tool Guidance Style

**OpenClaw**: Tools defined in separate TOOLS.md. Agent-specific tool access via skills. No inline guidance in system prompt — tools are self-describing via MCP schema.

**Claude Code**: 20 built-in tool descriptions embedded in the system prompt (~14-17K tokens of tool definitions). Highly specific — e.g. "Batch multiple independent tool calls together." Tells the agent to use specialized sub-agents (Plan, Explore, Task) for different work.

**NanoClaw**: Tools added via skills. Four skill categories: feature skills, utility skills, operational skills, container skills. No centralized tool guidance — each skill is self-contained.

**OpenCode**: Tools auto-validated with argument schemas. Output truncated to 2000 lines / 50KB. When output is truncated, the model is told to use Grep/Read or delegate to an explore agent.

**SmolClaw** (AGENT.md Tool Selection section):
> memory_search — Your first move for any knowledge question. Searches across vectors, knowledge graph, and full text.
> web_search — When memory doesn't have the answer or you need current information.
> *(Each tool gets a one-liner explaining when to use it and what it's for.)*

### Style / Tone Guidance

**OpenClaw** (SOUL.md):
> Be the assistant you'd actually want to talk to. Concise when needed, thorough when it matters. Not a corporate drone. Not a sycophant.
> No "it depends" — make a recommendation. Never say "Great question!"
> Private information stays private. Ask before external communications.

**Claude Code**:
> Answer concisely with fewer than 4 lines. DO NOT ADD ANY COMMENTS unless asked.
> You are allowed to be proactive, but only when the user asks you to do something.

**NanoClaw**: No explicit tone guidance. Inherits from Claude SDK defaults.

**OpenCode**: No explicit tone guidance. Provider-specific templates handle model quirks.

**SmolClaw** (agents.yaml persona):
> You are SmolClaw, an agentic assistant with deep, persistent, associative memory. You remember across sessions, classify what you learn, and build connections between concepts over time.
> Use memory tools proactively — search before answering, store important facts and decisions. When you don't know something and can't find it in memory, say so.

### Key Differences in Prompt Philosophy

| Approach | Who | How |
|----------|-----|-----|
| **Personality-first** | OpenClaw | SOUL.md defines who you ARE. Values, opinions, style. Identity drives behavior. |
| **Task-first** | Claude Code | Minimal identity. Heavy on execution instructions. "Do X, verify Y, minimize Z." |
| **Architecture-first** | NanoClaw | Prompt is about the system, not the agent. Identity delegated to the SDK. |
| **Configuration-first** | OpenCode | Identity comes from config files and provider templates, not a single prompt. |
| **Memory-first** | SmolClaw | Identity centers on knowledge capabilities. Reasoning principles + tool selection. |

---

## Agent Prompt & Configuration Comparison

### System Prompt Structure

| Component | OpenClaw | Claude Code | NanoClaw | OpenCode | SmolClaw |
|-----------|----------|-------------|----------|----------|----------|
| Identity file | SOUL.md (immutable) | CLAUDE.md | CLAUDE.md per group | Config file | AGENT.md (shared) |
| Persona | In SOUL.md | Built-in (2,896 tokens) | Per-group CLAUDE.md | Per-config | agents.yaml persona field |
| Tool descriptions | In TOOLS.md | 20 built-in (in system prompt) | Via skills | Built-in | In tool class `description` property |
| Memory context | On-demand via tools (not auto-injected) | Auto-compressed | CLAUDE.md (always loaded) | Persistent store | Auto-injected (token-budgeted) |
| Bootstrap/skills | SKILL.md files (composable) | Slash commands + sub-agent prompts | SKILL.md files | Plugin system | bootstrap_path per agent |
| Runtime context | Host, OS, model, workspace, date | Model, shell, OS, git status, date | Container ID, group, channel | Model, workspace | Current timestamp only |

### Reasoning & Methodology

| Aspect | OpenClaw | Claude Code | NanoClaw | OpenCode | SmolClaw |
|--------|----------|-------------|----------|----------|----------|
| Reasoning pattern | ReAct (think → act → observe) | Adaptive (task-type detection) | Delegated to Claude SDK | ReAct | Tool-use loop (no explicit reasoning) |
| Planning step | Yes (in extended thinking) | Yes (Plan sub-agent) | Via SDK | Yes | No (Phase 2 roadmap) |
| Reflection | Yes (observation analysis) | Yes (course correction) | Via SDK | Yes | Config-driven prompt (just added) |
| Self-correction | Checkpoints + retry | Implicit in loop | Via SDK | Implicit | No |
| Extended thinking | 6 configurable levels | Built-in | Via SDK | No | No (Phase 5 roadmap) |
| Task decomposition | Via skills + reasoning | Sub-agent delegation | Via SDK | Via ReAct | Via bootstrap methodology files |

### Memory & Context

| Aspect | OpenClaw | Claude Code | NanoClaw | OpenCode | SmolClaw |
|--------|----------|-------------|----------|----------|----------|
| Memory tiers | T0 (identity) / T1 (core) / T2 (working) | Context compression | CLAUDE.md per group | Preferences + session history | Flat (promote/decay, no tiers) |
| Decay model | Half-life 23 days on T2 | Auto-compression | None | None | Configurable (batch SQL decay) |
| Context injection | On-demand (tools search) | Auto (compressed) | Always loaded | Auto | Auto (budgeted, configurable) |
| Token budget | Varies by model | ~200K context | Per-container | Model-dependent | Configurable per agent (default 8K) |
| Contradiction detection | No | No | No | No | Yes (built-in) |
| Knowledge graph | No | No | No | No | Yes (NetworkX + vector + BM25) |

### Agent Configuration

| Aspect | OpenClaw | Claude Code | NanoClaw | OpenCode | SmolClaw |
|--------|----------|-------------|----------|----------|----------|
| Multi-agent | Via AGENTS.md delegation | Plan/Explore/Task sub-agents | Per-channel | Single agent | agents.yaml with spawn tools |
| Per-agent model | Yes | Fixed (Claude) | Per-group | Yes (75+ providers) | Yes (per agent in YAML) |
| Per-agent tools | Via skills | Fixed set | Via skills | Via plugins | tools list in YAML |
| Per-agent reasoning depth | Extended thinking levels | Task-type adaptive | Fixed | Fixed | context_budget + reflection flag |
| Agent profiles | Custom SOUL.md + skills | Built-in sub-agent types | Custom CLAUDE.md | Config-based | YAML + bootstrap_path |
| Hot-reload | Yes (file watch) | No | Container restart | No | No (restart required) |

### Tool Ecosystem

| Tool Category | OpenClaw | Claude Code | NanoClaw | OpenCode | SmolClaw |
|---------------|----------|-------------|----------|----------|----------|
| File operations | Yes | Yes (Read, Write, Edit, Glob, Grep) | Via sandbox | Yes | Yes (4 tools) |
| Shell/terminal | Yes | Yes (Bash) | Via container | Yes | Yes (exec, pattern-blocked) |
| Web search | Via skills | Yes (WebSearch, WebFetch) | Via skills | Yes | Yes (Brave API) |
| Memory/knowledge | MEMORY.md + search | CLAUDE.md + context | CLAUDE.md per group | Persistent store | KG + vector + BM25 (6 tools) |
| Messaging | Slack, WhatsApp, Telegram, Discord, email | No | WhatsApp, Telegram, Slack, Discord, Gmail | No | No |
| Scheduling | HEARTBEAT.md (cron) | No | Scheduled jobs | No | No |
| Code analysis | Via skills | LSP, Notebook | No | grep, terminal | Via exec |
| Sub-agents | Via AGENTS.md | Agent tool | No | No | spawn_agent/get_result |

---

## Recommended Priority for SmolClaw

### Tier 1: Highest Impact, Achievable Now

1. **Rewrite AGENT.md as a proper identity/methodology file** — Add research methodology (plan → search → verify → synthesize → reflect), tool selection guidance, reasoning patterns. This is the single highest-ROI change.

2. **Enrich tool descriptions** — Tell the LLM *when* to use each tool, what queries work best, how to interpret results.

3. **Increase context budget** — 4K → 8K tokens for retrieved memories.

4. **Add reflection prompt** — After tool rounds, inject "assess whether your answer is complete and verified" into the conversation.

### Tier 2: Architectural Improvements

5. **ReAct-style reasoning** — Add explicit think → plan → act → observe → reflect steps in the agent loop.

6. **Memory tiers** — Separate core/evergreen memory from working/temporal memory. Access on-demand instead of auto-inject.

7. **Task-type detection** — Detect whether the user wants research, simple lookup, creative work, or file operations, and adjust reasoning depth accordingly.

### Tier 3: Feature Parity

8. **Skills-as-prompts system** — Allow markdown skill files that compose agent capabilities.

9. **Extended thinking integration** — Use Anthropic's extended thinking or OpenAI's reasoning tokens for complex tasks.

10. **Self-correction with backtracking** — Detect failed approaches and try alternatives.

---

## Implementation Phases

All four frameworks (OpenClaw, Claude Code, NanoClaw, OpenCode) use the same pattern: **generic loop + composable configuration = specialized agents.** Nobody hardcodes reasoning for one purpose. The loop stays generic. Prompts, tool sets, and bootstrap files make it smart for a given task. SmolClaw should follow this pattern.

### Phase 1: Composable Agent Intelligence — COMPLETE

Make reasoning behavior configurable per-agent. No hardcoded logic for any single use case.

- [x] Research complete (this document)
- [x] Extend `AgentConfig` with `context_budget` and `reflection`
- [x] Wire `context_budget` through `agent_factory.py` → `ContextAssembler`
- [x] Add reflection prompt injection in agent loop (config-driven)
- [x] Enrich tool descriptions in `app/tools/*.py`
- [x] Rewrite `AGENT.md` — reasoning principles, behavioral guidance, anti-patterns, tool selection
- [x] Rewrite `agents/smolclaw.md` as default agent methodology
- [x] Create `agents/researcher.md` and `agents/coder.md`
- [x] Update `agents.yaml` with `context_budget: 8000`, `reflection: true`, 3 agent profiles
- [x] Sharpen prompts: anti-sycophancy, act-don't-narrate, tone guidance
- [x] Token-by-token streaming (OpenAI + Anthropic)
- [x] Token usage tracking and audit trail
- [x] All tests passing (504)

### Phase 2: ReAct Reasoning Loop

Add explicit think → plan → act → observe → reflect cycle to the agent loop.

- [ ] Before tool calls: inject planning prompt ("what do I need to find out and in what order?")
- [ ] After tool results: inject observation prompt ("what did I learn? do I need to adjust my approach?")
- [ ] Make ReAct steps configurable per-agent (some agents need planning, some don't)
- [ ] Self-correction: detect failed tool calls and suggest alternative approaches

**Patterns addressed:** ReAct loop, self-correction, adaptive reasoning.

### Phase 3: Memory Tiers

Separate memory into layers with different persistence and access patterns.

- [ ] T0: Identity — `AGENT.md` / bootstrap files. Immutable. Always in context.
- [ ] T1: Core memory — Curated evergreen knowledge. No decay. High retrieval priority.
- [ ] T2: Working memory — Recent/temporal. Decays. Accessed on-demand only (not auto-injected).
- [ ] On-demand retrieval instead of auto-inject for T2 (saves context window)
- [ ] Promotion path: working memory → core memory when accessed frequently

**Patterns addressed:** Memory tiers (OpenClaw T0/T1/T2), on-demand access, context window efficiency.

### Phase 4: Skills-as-Prompts

Allow agent capabilities to be defined as markdown instruction files.

- [ ] Define SKILL.md format (YAML frontmatter + markdown instructions)
- [ ] Skill loader that injects relevant skills into agent context
- [ ] Agent can discover and load skills based on task type
- [ ] Agent can write its own skill files for novel tasks

**Patterns addressed:** Skills system (OpenClaw/NanoClaw), agent self-improvement.

### Phase 5: Extended Thinking & Advanced Reasoning

- [ ] Integrate Anthropic's extended thinking API for complex tasks
- [ ] Integrate OpenAI's reasoning tokens (o-series models)
- [ ] Configurable thinking budget per agent
- [ ] Checkpoints and backtracking for long multi-step tasks

**Patterns addressed:** Extended thinking, checkpoints/backtracking.

### Phase 6: Platform Features

- [ ] Multi-provider model support (local models via Ollama, etc.)
- [ ] Messaging channel integrations (Slack, Telegram, etc.)
- [ ] Scheduled jobs / heartbeat
- [ ] Multi-user / multi-tenant
- [ ] Cost controls and budget enforcement

---

## Sources

- [OpenClaw System Prompt](https://docs.openclaw.ai/concepts/system-prompt)
- [OpenClaw Agent Loop](https://docs.openclaw.ai/concepts/agent-loop)
- [OpenClaw Memory Architecture](https://ai-coding.wiselychen.com/en/openclaw-architecture-deep-dive-context-memory-token-crusher/)
- [OpenClaw SOUL.md / HEARTBEAT.md Guide](https://blink.new/blog/openclaw-heartbeat-soul-memory-configuration-guide-2026)
- [OpenClaw Workspace Files Explained](https://capodieci.medium.com/ai-agents-003-openclaw-workspace-files-explained-soul-md-agents-md-heartbeat-md-and-more-5bdfbee4827a)
- [How Claude Code Works](https://code.claude.com/docs/en/how-claude-code-works)
- [Claude Code vs OpenCode Comparison](https://www.infralovers.com/blog/2026-01-29-claude-code-vs-opencode/)
- [NanoClaw on GitHub](https://github.com/qwibitai/nanoclaw)
- [NanoClaw Skills](https://nanoclaw.dev/skills/)
- [NanoClaw Architecture (The New Stack)](https://thenewstack.io/nanoclaw-minimalist-ai-agents/)
- [OpenCode on GitHub](https://github.com/opencode-ai/opencode)
- [OpenCode Agents Docs](https://opencode.ai/docs/agents/)
