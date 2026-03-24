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

### 1. ReAct Reasoning Loop (Critical)

**What it is**: Before taking an action, the agent explicitly reasons about what it should do and why. After observing the result, it reflects on whether it worked and what to do next.

**Who has it**: OpenClaw, Claude Code, OpenCode

**SmolClaw today**: Pure tool-use trampoline. LLM decides actions implicitly in its response. No explicit planning, no observation analysis, no strategy adjustment.

**Impact**: Without ReAct, the agent can't decompose complex tasks, can't recover from failed approaches, and can't reason about whether its answer is complete.

### 2. Identity / SOUL.md (High)

**What it is**: A persistent, immutable identity file that defines who the agent is, its values, behavioral boundaries, and communication style. Loaded first, never modified by the agent.

**Who has it**: OpenClaw (SOUL.md), Claude Code (CLAUDE.md), NanoClaw (CLAUDE.md per group)

**SmolClaw today**: `AGENT.md` exists but is thin — lists capabilities and memory taxonomy. No personality, values, reasoning methodology, or behavioral guidelines.

**Impact**: The agent has no consistent identity or approach. Every session starts from a generic persona.

### 3. Memory Tiers (High)

**What it is**: Separating memory into tiers with different persistence, decay, and access patterns:
- Immutable identity (never changes)
- Core/evergreen knowledge (curated, no decay)
- Working memory (recent, decays)
- On-demand access (search, don't auto-inject)

**Who has it**: OpenClaw (T0/T1/T2), Claude Code (context compression)

**SmolClaw today**: Single flat retrieval layer. Everything has the same importance weighting (modulo taxonomy weights). Context auto-injected into system prompt (4K budget). No "must never forget" vs "happened yesterday" distinction.

**Impact**: Important knowledge gets buried under recent noise. Context window wasted on auto-injected content that may not be relevant.

### 4. Extended Thinking / Reasoning Budget (Medium)

**What it is**: Configurable reasoning depth. Agent can spend more tokens thinking before acting for complex tasks, or less for simple ones.

**Who has it**: OpenClaw (6 levels), Claude Code (built-in)

**SmolClaw today**: No reasoning budget concept. Agent always responds at the same depth.

**Impact**: Complex research tasks get the same shallow reasoning as simple fact lookups.

### 5. Specialized Sub-Agents (Medium)

**What it is**: Different agent configurations for different task types. A planning agent thinks differently than an exploration agent or an execution agent.

**Who has it**: Claude Code (Plan, Explore, Task agents with different system prompts)

**SmolClaw today**: Multi-agent spawn exists but all agents use the same generic persona. No task-type specialization.

**Impact**: Research tasks, creative tasks, and simple lookups all get the same approach.

### 6. Skills-as-Prompts (Medium)

**What it is**: Agent capabilities defined as markdown instruction files (SKILL.md), not code. Composable, shareable, and the agent can write its own.

**Who has it**: OpenClaw, NanoClaw, Claude Code (slash commands)

**SmolClaw today**: Tools are code-level plugins. Agent cannot create or modify its own capabilities.

**Impact**: Adding capabilities requires code changes. Agent can't adapt to novel tasks by writing its own skill files.

### 7. Self-Correction & Checkpoints (Medium)

**What it is**: Agent observes action results, recognizes failures, and tries alternative approaches. Checkpoints allow backtracking.

**Who has it**: OpenClaw (checkpoints every N steps), Claude Code (course correction)

**SmolClaw today**: No self-correction. If a tool call fails, the error is fed back to the LLM but there's no explicit "try a different approach" mechanism.

### 8. Multi-Provider Model Support (Low)

**What it is**: Support for many LLM providers, including local models.

**Who has it**: OpenCode (75+ providers), OpenClaw (multiple)

**SmolClaw today**: OpenAI + Anthropic only.

**Impact**: Can't use local models for privacy. Can't try different models for different tasks.

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

### Phase 1: Composable Agent Intelligence (Current — ready to implement)

Make reasoning behavior configurable per-agent. No hardcoded logic for any single use case.

**What this checks off:**
- [x] Research complete (this document)
- [ ] Extend `AgentConfig` with `context_budget` (int, default 4000) and `reflection` (bool, default false)
- [ ] Wire `context_budget` through `agent_factory.py` → `ContextAssembler`
- [ ] Add reflection prompt injection in agent loop (config-driven, fires after tool rounds when enabled)
- [ ] Enrich tool descriptions in `app/tools/*.py` — universal guidance on when/how to use each tool
- [ ] Rewrite `AGENT.md` as universal reasoning foundation (search before assuming, verify claims, store findings, be explicit about uncertainty)
- [ ] Rewrite `agents/smolclaw.md` as improved default agent methodology
- [ ] Create `agents/researcher.md` — research decomposition, multi-source synthesis, citation
- [ ] Create `agents/coder.md` — read before modifying, test after changes, minimal diffs
- [ ] Update `agents.yaml` default agent with `context_budget: 8000`, `reflection: true`
- [ ] Update tests for new config fields and reflection behavior

**Patterns addressed:** Identity file, tool selection guidance, configurable reasoning depth, sub-agent specialization, composability.

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
