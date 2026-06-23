# Research: Agentic Coding Harness Architecture

Date: 2026-06-23

This note backs the SmolClaw architecture and reliability roadmap against current coding-agent products, agent-runtime guidance, and software-engineering-agent research.

## Bottom Line

SmolClaw's current direction is well supported:

1. Stay focused on a local, terminal-first coding harness before broad personal-assistant scope.
2. Keep the core agent loop simple, explicit, and observable.
3. Enforce safety structurally through tool permissions, path policy, guardrails, approvals, checkpoints, and sandboxing rather than relying on prompts alone.
4. Treat workspace state, trajectories, traces, and evals as first-class reliability artifacts.
5. Use subagents selectively for planning, exploration, review, and context isolation, not as default complexity.
6. Add remote gateway/channel behavior only after isolation, pairing, idempotency, and untrusted-content handling are mature.

## Comparison Targets

### OpenCode

OpenCode is the closest product reference for SmolClaw's near-term shape. It is an open source AI coding agent with terminal, desktop, and IDE surfaces, but the docs foreground terminal coding workflows, project initialization, planning, permissions, and undo.

Relevant lessons:

- Terminal-first coding workflow is a validated product shape. OpenCode's intro positions it as an open source coding agent and walks the user through running it inside a project directory, initializing project context, planning, building, and undoing changes. See [OpenCode intro](https://opencode.ai/docs/).
- Plan/build separation is a strong UX pattern. OpenCode's Plan mode disables changes and asks the model to propose an implementation before switching back to Build mode. See [OpenCode intro: Add features](https://opencode.ai/docs/).
- Checkpoints and undo are table stakes. OpenCode documents `/undo` and `/redo` as normal recovery paths for code changes. See [OpenCode intro: Undo changes](https://opencode.ai/docs/).
- Agent roles should map to tool authority. OpenCode's Build agent has full development access, Plan is restricted, Explore is read-only, and Scout is read-only for external docs/dependency research. See [OpenCode agents](https://opencode.ai/docs/agents/).
- Permissions should be first-class and granular. OpenCode supports `allow`, `ask`, and `deny`, with per-tool, per-command, per-path, per-agent, external-directory, `.env`, and repeated-call policies. See [OpenCode permissions](https://opencode.ai/docs/permissions/).
- Project instruction files are useful, but should not replace enforcement. OpenCode uses `AGENTS.md` for project guidance and `/init` to generate it from repo facts. See [OpenCode rules](https://opencode.ai/docs/rules/).
- Provider/resource policy should remain separate from tool permissions. OpenCode distinguishes session permissions from provider-use policies. See [OpenCode policies](https://opencode.ai/docs/policies/).

SmolClaw alignment:

- Current: terminal-first `smolclaw`, workspace-scoped tools, project docs, permission modes, checkpoints, `/undo`, subagent factory.
- Gap: no configurable `ask` policy yet; no persistent task ledger comparable to a todo/progress surface; no generated project instruction bootstrap.

### OpenClaw

OpenClaw is most useful as a reference for remote, channel, gateway, and long-running assistant concerns. It is less useful as a direct product target because SmolClaw is intentionally not trying to become a broad always-on personal assistant yet.

Relevant lessons:

- The agent loop is an authoritative path from intake through context assembly, model inference, tool execution, streaming, and persistence. OpenClaw serializes each session lane to avoid races and keep session state consistent. See [OpenClaw agent loop](https://docs.openclaw.ai/concepts/agent-loop).
- Gateway APIs need typed frames, schema validation, lifecycle events, and run IDs. OpenClaw's gateway exposes typed WebSocket requests/responses/events, requires a `connect` handshake, emits stream events, and uses idempotency keys for side-effecting methods. See [OpenClaw architecture](https://docs.openclaw.ai/concepts/architecture).
- Remote access requires pairing and explicit trust boundaries. OpenClaw requires device identity and pairing for non-local clients and warns that one gateway is not a hostile multi-tenant boundary. See [OpenClaw security](https://docs.openclaw.ai/gateway/security).
- Tool-enabled agents reading external content need strict tool policy and sandboxing. OpenClaw's security docs emphasize untrusted external content, prompt injection, minimal tools, and sandboxing for agents that touch web/email/docs/channel input. See [OpenClaw security: prompt injection](https://docs.openclaw.ai/gateway/security).
- Operations need audits and dangerous-flag detection. OpenClaw documents `security audit` checks for gateway exposure, browser control, exec approvals, sandboxing, plugins, skills, filesystem permissions, and dangerous config flags. See [OpenClaw security audit guidance](https://docs.openclaw.ai/gateway/security).

SmolClaw alignment:

- Current: shared runtime builder, gateway code path as secondary, per-session state, tool events, checkpoint/undo, strict local path policy.
- Gap: gateway is not ready for remote control; no pairing model, idempotency layer, worktree/sandbox isolation, or untrusted-content channel policy.

## Product And Runtime Guidance

### Anthropic: Simple Composable Agents

Anthropic's "Building effective agents" argues for simple, composable patterns before framework complexity, and distinguishes workflows from autonomous agents. It also says agents should receive ground truth from environment feedback, use stopping conditions, run with guardrails, and be tested in sandboxes. For coding agents specifically, it points to automated tests as a core feedback mechanism while noting that human review remains important. See [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

Implications for SmolClaw:

- Keep `AgentLoop` understandable and inspectable.
- Add complexity only when a test or eval proves it closes a reliability gap.
- Prefer explicit tool contracts and runtime checks over opaque orchestration.
- Make verification commands, stop reasons, and blockers part of the run state.

### Claude Code: Checkpoints, Subagents, Context Hygiene

Claude Code's best-practices docs recommend subagents for codebase investigation and verification without cluttering the main conversation. They also document checkpoints that can restore conversation, code, or both, with file snapshots before each change. See [Claude Code best practices](https://code.claude.com/docs/en/best-practices).

Implications for SmolClaw:

- The checkpoint and `/undo` work is aligned with current coding-agent UX.
- Subagents should be used for exploration/review/context isolation.
- Future checkpoint work should consider conversation plus code rewind, not only file undo.

### OpenAI: Tools, Guardrails, Human Review, Traces, Evals

OpenAI's Agents docs frame the agent stack around agent definitions, model/provider strategy, runtime loop/state, sandboxed environments, orchestration/handoffs, guardrails/human review, results/state, tools, observability, and evals. See [OpenAI Agents SDK guide](https://developers.openai.com/api/docs/guides/agents).

OpenAI's tools docs state that tool semantics are stable across direct API and Agents SDK usage, and that shell, apply-patch, and computer-use harnesses should stay in the runtime even when the SDK models tool choice. See [OpenAI tools guide](https://developers.openai.com/api/docs/guides/tools).

OpenAI's guardrails and human-review docs distinguish automatic checks from approvals: input/output/tool guardrails validate behavior, while human review pauses before side effects such as edits or shell commands. They also warn that agent-level guardrails do not run everywhere, so checks around every side-effecting tool should live next to the tool. See [OpenAI guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals).

OpenAI's agent-evals docs recommend starting with traces while debugging behavior, then moving to repeatable datasets and eval runs once "good" is defined. Traces capture model calls, tool calls, guardrails, and handoffs, and can be graded for tool choice, handoff correctness, instruction violations, and safety policy failures. See [OpenAI agent evals](https://developers.openai.com/api/docs/guides/agent-evals).

Implications for SmolClaw:

- Keep local file/shell/apply-patch behavior in SmolClaw's harness, not hidden behind provider-specific abstractions.
- Attach safety checks to tools and middleware, especially mutation and command tools.
- Add human approval/resume semantics before allowing broader command or external-directory access.
- Build trace capture first, then build evals on top of those traces.

## Research Evidence

### ReAct

ReAct introduced interleaved reasoning and acting, where reasoning tracks plans and exceptions while actions gather external information from tools/environments. The paper reports improved interpretability and reduced hallucination/error propagation in knowledge tasks by grounding the model in environment interactions. See [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629).

SmolClaw implication: the core loop should preserve a visible sequence of user intent, model decision, tool call, tool result, and next decision. This supports the roadmap's focus on traces, stopping conditions, and verification evidence.

### SWE-bench

SWE-bench showed that real GitHub issues require repository understanding, multi-file coordination, long-context handling, execution environments, and complex reasoning beyond standalone code generation. See [SWE-bench](https://arxiv.org/abs/2310.06770).

SmolClaw implication: unit tests alone are not enough. The eval harness should run realistic repo tasks that require localization, editing, execution, and final verification.

### SWE-agent

SWE-agent argues that language-model agents need agent-computer interfaces designed for their needs, not just generic human CLIs. Its custom interface improved repository navigation, file editing, test execution, and benchmark performance. See [SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793).

SmolClaw implication: tool design is product design. `read_file`, `grep_search`, `apply_patch`, `git_diff`, checkpoints, and command tools should be optimized as an agent-computer interface, with tests around how agents are expected to use them.

### SWE-Adept

SWE-Adept proposes separate localization and resolution agents, adaptive planning, structured problem solving, progress tracking, Git-backed operations, shared working memory, and indexed checkpoints for reverting failed edits. See [SWE-Adept](https://arxiv.org/abs/2603.01327).

SmolClaw implication: Phase 2 and Phase 3 should prioritize a task ledger, acceptance criteria, verification state, checkpoints indexed to execution steps, and optional subagent roles for localization/review before broad multi-agent autonomy.

### SeaView

SeaView argues that SWE-agent trajectories are hard to analyze because they are long, tool-mediated, and often exceed context windows; visualization helps diagnose errors, compare runs, and understand regressions. See [SeaView](https://arxiv.org/abs/2504.08696).

SmolClaw implication: TUI trace export and replayable run records are not polish. They are required infrastructure for debugging agent behavior and improving evals.

### Guardrails Beat Guidance

This 2026 study of coding-agent rules found that negative constraints were the beneficial rule type, while positive directives could be harmful in isolation. It concludes that safer agent configuration should constrain what agents must not do rather than prescribing everything they should do. See [Guardrails Beat Guidance](https://arxiv.org/abs/2604.11088).

SmolClaw implication: continue moving constraints into code-level permissions, hard denies, guardrails, and approvals. Keep prompt guidance concise and avoid overloading durable instruction files.

### SWE-Agent Trajectory Observation

The 2026 "Wild Code Understanding Journey" paper argues that faithful, replayable traces can be transformed into comparable behavioral profiles for SWE agents, including navigation, evidence selection, synthesis, grounding, and stopping behavior. See [Projecting the Emerging Mindset of SWE Agent](https://arxiv.org/abs/2606.08500).

SmolClaw implication: the goal ledger and eval harness should capture evidence selection and stop reasons, not just pass/fail results.

## Architecture Assessment

| SmolClaw choice | Evidence | Assessment |
| --- | --- | --- |
| Single local CLI/TUI entry point | OpenCode terminal workflow; Anthropic simple-agent guidance | Strongly supported. Keep this as the primary product surface. |
| Workspace-owned filesystem scope | OpenCode external-directory permissions; OpenClaw trust-boundary guidance | Strongly supported. Current hard-deny policy is a good v1; next step is configurable approvals. |
| Tool projection by capability and agent config | OpenCode role-specific agents and permissions; OpenAI agent definitions/tools | Strongly supported. Avoid exposing hidden tools outside enabled capabilities. |
| Structural permission middleware in every mode | OpenCode `.env` defaults and external-directory gates; Guardrails Beat Guidance | Strongly supported. Keep prompt-only safety out of the critical path. |
| Checkpoints and `/undo` | OpenCode `/undo`; Claude Code `/rewind`; SWE-Adept checkpoints | Strongly supported. Extend later to code plus conversation checkpoints. |
| Safety gate requiring exploration before mutation | SWE-bench localization difficulty; SWE-agent ACI; SWE-Adept localization agent | Direction is right, but current evidence gate should become more target-file relevant. |
| Subagent factory | OpenCode subagents; Anthropic orchestrator-workers; SWE-Adept localization/resolution split | Supported when used selectively. Avoid making multi-agent orchestration the default path. |
| TUI stream separation and trace export | OpenClaw stream events; SeaView trajectory analysis; OpenAI traces/evals | Strongly supported. Trace export is roadmap-critical. |
| Gateway kept secondary | OpenClaw security/trust model; untrusted-content risks | Strongly supported. Do not expose remote control before sandbox, pairing, idempotency, and policy are implemented. |
| Local eval harness next | SWE-bench; OpenAI agent evals; SeaView; trajectory-observation paper | Strongly supported. Evals should record trajectories, diffs, commands, results, and stop reasons. |

## Roadmap Implications

### Keep

- Local terminal-first coding focus.
- Shared runtime builder for CLI and gateway.
- Capability-projected tools.
- Permission middleware and hard-deny local safety.
- Mutation checkpoints and `/undo`.
- Goal loop direction.
- TUI stream isolation.

### Prioritize Next

1. Goal ledger with explicit acceptance criteria, target files, evidence, verification commands, blocker state, and stop reason.
2. Trace export that records model calls, tool calls, tool results, safety decisions, approvals, checkpoints, diffs, and test results.
3. Agent-eval harness that runs realistic local repo tasks in isolated workspaces or worktrees and scores behavior from traces plus final tests.
4. Configurable permission policy with `allow`, `ask`, and `deny`, including command prefixes, file globs, external directories, and per-agent overrides.
5. Worktree or sandbox mode before enabling direct local shell or remote-origin work.
6. Project bootstrap that can generate/update concise `AGENTS.md`-style project guidance from repo facts.

### Defer

- Full always-on personal assistant behavior.
- Public or semi-public gateway exposure.
- Messaging channels with tool-enabled agents.
- Plugin/skill marketplace behavior.
- Autonomous git push or broad command access.

## Risks To Watch

- Overfitting to product imitation. OpenCode validates the local coding shape; OpenClaw validates remote safety patterns. SmolClaw should not inherit both scopes at once.
- Prompt-instruction bloat. Research favors constraints and structural guardrails over piling on positive directives.
- Eval theater. Unit tests prove internals, but agent reliability needs realistic tasks, trace grading, and regression scoring.
- Hidden side effects. Every mutation, command, remote fetch, and approval decision should be traceable.
- Gateway optimism. Remote control changes the threat model. Treat channel content as untrusted even if the sender is trusted.

## Source Index

- [OpenCode intro](https://opencode.ai/docs/)
- [OpenCode agents](https://opencode.ai/docs/agents/)
- [OpenCode permissions](https://opencode.ai/docs/permissions/)
- [OpenCode tools](https://opencode.ai/docs/tools/)
- [OpenCode rules](https://opencode.ai/docs/rules/)
- [OpenCode policies](https://opencode.ai/docs/policies/)
- [OpenClaw architecture](https://docs.openclaw.ai/concepts/architecture)
- [OpenClaw agent loop](https://docs.openclaw.ai/concepts/agent-loop)
- [OpenClaw security](https://docs.openclaw.ai/gateway/security)
- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Claude Code best practices](https://code.claude.com/docs/en/best-practices)
- [OpenAI Agents SDK guide](https://developers.openai.com/api/docs/guides/agents)
- [OpenAI tools guide](https://developers.openai.com/api/docs/guides/tools)
- [OpenAI guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
- [OpenAI agent evals](https://developers.openai.com/api/docs/guides/agent-evals)
- [ReAct](https://arxiv.org/abs/2210.03629)
- [SWE-bench](https://arxiv.org/abs/2310.06770)
- [SWE-agent](https://arxiv.org/abs/2405.15793)
- [SWE-Adept](https://arxiv.org/abs/2603.01327)
- [SeaView](https://arxiv.org/abs/2504.08696)
- [Guardrails Beat Guidance](https://arxiv.org/abs/2604.11088)
- [Projecting the Emerging Mindset of SWE Agent](https://arxiv.org/abs/2606.08500)
