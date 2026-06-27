"""Tests for permission modes and PermissionMiddleware."""

import os
import subprocess

import pytest

from app.approvals import ApprovalRequestStore
from app.tools.command import RunCommandTool
from app.tools.base import Tool, ToolCallPolicy, normalize_tool_result
from app.tools.middleware import MiddlewareChain
from app.tools.permissions import PERMISSION_MODES, PermissionMiddleware
from app.tools.policy import (
    PermissionPolicy,
    PermissionRule,
    PolicyPermissionMiddleware,
    baseline_policy_for_mode,
    load_permission_policy,
)
from app.run_trace import RunTraceStore
from app.workspace import WorkspaceContext


class FakeTool(Tool):
    def __init__(self, tool_name="fake"):
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Fake {self._name}"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return f"{self._name} executed"


class PolicyTool(FakeTool):
    def __init__(self, tool_name="fake", policy=None, policy_fn=None):
        super().__init__(tool_name=tool_name)
        self._policy = policy
        self._policy_fn = policy_fn

    def get_call_policy(self, arguments=None) -> ToolCallPolicy:
        if self._policy_fn is not None:
            return self._policy_fn(arguments or {})
        return self._policy or ToolCallPolicy()


class TestPolicyPermissionMiddleware:
    @pytest.mark.asyncio
    async def test_policy_denies_command_pattern(self):
        policy = PermissionPolicy(rules=(
            PermissionRule(
                subject="command",
                pattern="npm install*",
                action="deny",
                reason="dependency installs require review",
            ),
        ))
        chain = MiddlewareChain([PolicyPermissionMiddleware("full", policy=policy)])

        result = await chain.run(FakeTool("run_command"), {"command": "npm install left-pad"})

        assert result.startswith("Error:")
        assert "dependency installs require review" in result

    @pytest.mark.asyncio
    async def test_policy_ask_blocks_with_approval_required(self):
        policy = PermissionPolicy(rules=(
            PermissionRule(
                subject="path",
                pattern="../shared/*",
                action="ask",
                reason="external shared path",
            ),
        ))
        chain = MiddlewareChain([PolicyPermissionMiddleware("full", policy=policy)])

        result = await chain.run(FakeTool("read_file"), {"path": "../shared/config.json"})

        assert result.startswith("Error: Approval required")
        assert "external shared path" in result

    @pytest.mark.asyncio
    async def test_policy_ask_creates_pending_approval_and_allows_approved_exact_retry(self, temp_dir):
        approval_store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
        shared_state = {
            "approval_store": approval_store,
            "session_key": "session-a",
        }
        policy = PermissionPolicy(rules=(
            PermissionRule(
                subject="command",
                pattern="npm install*",
                action="ask",
                reason="dependency installs require review",
            ),
        ))
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("full", policy=policy, shared_state=shared_state),
        ])

        first = await chain.run(FakeTool("run_command"), {"command": "npm install left-pad"})
        pending = approval_store.list("session-a", status="pending")
        approval_store.approve("session-a", pending[0].id)
        second = await chain.run(FakeTool("run_command"), {"command": "npm install left-pad"})
        third = await chain.run(FakeTool("run_command"), {"command": "npm install left-pad"})

        assert "Approval id: apr-" in first
        assert len(pending) == 1
        assert pending[0].scope == "once"
        assert pending[0].requested_action == "ask"
        assert pending[0].matched_subject == "command"
        assert pending[0].matched_pattern == "npm install*"
        assert second == "run_command executed"
        assert third.startswith("Error: Approval required")

    @pytest.mark.asyncio
    async def test_policy_approved_call_does_not_allow_changed_arguments(self, temp_dir):
        approval_store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
        shared_state = {
            "approval_store": approval_store,
            "session_key": "session-a",
        }
        policy = PermissionPolicy(rules=(
            PermissionRule(subject="command", pattern="npm install*", action="ask"),
        ))
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("full", policy=policy, shared_state=shared_state),
        ])

        await chain.run(FakeTool("run_command"), {"command": "npm install left-pad"})
        pending = approval_store.list("session-a", status="pending")
        approval_store.approve("session-a", pending[0].id)
        changed = await chain.run(FakeTool("run_command"), {"command": "npm install is-odd"})

        assert changed.startswith("Error: Approval required")
        assert len(approval_store.list("session-a", status="pending")) == 1

    @pytest.mark.asyncio
    async def test_policy_cannot_override_secret_hard_deny(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        policy = PermissionPolicy(rules=(
            PermissionRule(subject="path", pattern=".env", action="allow"),
        ))
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("full", workspace=workspace, policy=policy),
        ])

        result = await chain.run(FakeTool("read_file"), {"path": ".env"})

        assert result.startswith("Error:")
        assert "secret path" in result

    @pytest.mark.asyncio
    async def test_policy_cannot_override_mode_deny(self):
        policy = PermissionPolicy(rules=(
            PermissionRule(subject="tool", pattern="write_file", action="allow"),
        ))
        chain = MiddlewareChain([PolicyPermissionMiddleware("plan", policy=policy)])

        result = await chain.run(FakeTool("write_file"), {"path": "allowed.txt"})

        assert result.startswith("Error:")
        assert "'plan'" in result

    @pytest.mark.asyncio
    async def test_policy_emits_permission_decision_trace(self, temp_dir):
        trace_store = RunTraceStore(os.path.join(temp_dir, "traces"))
        recorder = trace_store.start_run("session-a")
        shared_state = {"trace_recorder": recorder}
        policy = PermissionPolicy(rules=(
            PermissionRule(subject="tool", pattern="read_file", action="allow", reason="ok"),
        ))
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("full", policy=policy, shared_state=shared_state),
        ])

        result = await chain.run(FakeTool("read_file"), {"path": "README.md"})
        recorder.finish("complete", stop_reason="test")

        assert result == "read_file executed"
        events = trace_store.load_events("session-a", recorder.run_id)
        decisions = [event for event in events if event.event == "permission.decided"]
        assert decisions[0].data["action"] == "allow"
        assert decisions[0].data["source"] == "rule"
        assert decisions[0].data["matched_subject"] == "tool"
        assert decisions[0].data["matched_pattern"] == "read_file"

    @pytest.mark.asyncio
    async def test_policy_ask_traces_approval_metadata(self, temp_dir):
        approval_store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
        trace_store = RunTraceStore(os.path.join(temp_dir, "traces"))
        recorder = trace_store.start_run("session-a")
        shared_state = {
            "approval_store": approval_store,
            "session_key": "session-a",
            "trace_recorder": recorder,
        }
        policy = PermissionPolicy(rules=(
            PermissionRule(
                subject="command",
                pattern="npm install*",
                action="ask",
                reason="dependency installs require review",
            ),
        ))
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("full", policy=policy, shared_state=shared_state),
        ])

        first = await chain.run(FakeTool("run_command"), {"command": "npm install left-pad"})
        pending = approval_store.list("session-a", status="pending")
        approval_store.approve("session-a", pending[0].id)
        second = await chain.run(FakeTool("run_command"), {"command": "npm install left-pad"})
        recorder.finish("complete", stop_reason="test")

        assert first.startswith("Error: Approval required")
        assert second == "run_command executed"
        events = trace_store.load_events("session-a", recorder.run_id)
        requested = [event for event in events if event.event == "approval.requested"][0]
        resolved = [event for event in events if event.event == "approval.resolved"][0]
        assert requested.data["approval_id"] == pending[0].id
        assert requested.data["scope"] == "once"
        assert requested.data["matched_subject"] == "command"
        assert requested.data["matched_pattern"] == "npm install*"
        assert requested.data["arguments_hash"] == pending[0].arguments_hash
        assert resolved.data["approval_id"] == pending[0].id
        assert resolved.data["scope"] == "once"

    def test_baseline_policy_for_mode_exports_mode_blocks(self):
        policy = baseline_policy_for_mode("plan")
        tool_rules = {rule.pattern for rule in policy.rules if rule.subject == "tool"}

        assert "write_file" in tool_rules
        assert policy.default_action == "allow"

    def test_baseline_policy_for_execute_asks_for_installs_and_node_probes(self):
        policy = baseline_policy_for_mode("execute")
        command_rules = {
            rule.pattern: rule.action
            for rule in policy.rules
            if rule.subject == "command"
        }
        capability_rules = {
            rule.pattern: rule.action
            for rule in policy.rules
            if rule.subject == "capability"
        }

        assert command_rules["npm install*"] == "ask"
        assert command_rules["npm i*"] == "ask"
        assert command_rules["node -e*"] == "ask"
        assert capability_rules["network"] == "ask"
        assert capability_rules["image_management"] == "ask"
        assert capability_rules["shell_session"] == "ask"

    @pytest.mark.asyncio
    async def test_network_effect_requires_approval(self):
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("execute", policy=PermissionPolicy()),
        ])
        tool = PolicyTool(
            "run_command",
            policy=ToolCallPolicy(effects=frozenset({"command_read", "network"})),
        )

        result = await chain.run(tool, {"command": "python -m pytest", "network_access": True})

        assert str(result).startswith("Error: Approval required")
        assert "network access requires approval" in result

    @pytest.mark.asyncio
    async def test_approved_call_scopes_execution_grant(self, temp_dir):
        approval_store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
        shared_state = {
            "approval_store": approval_store,
            "session_key": "session-a",
        }
        observed = []

        class GrantTool(PolicyTool):
            async def execute(self, **kwargs):
                observed.append(shared_state.get("active_execution_grant"))
                return "ok"

        tool = GrantTool(
            "run_command",
            policy=ToolCallPolicy(effects=frozenset({"command_read", "network"})),
        )
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("execute", policy=PermissionPolicy(), shared_state=shared_state),
        ])

        first = await chain.run(tool, {"command": "python -m pytest", "network_access": True})
        pending = approval_store.list("session-a", status="pending")
        approval_store.approve("session-a", pending[0].id)
        second = await chain.run(tool, {"command": "python -m pytest", "network_access": True})

        assert str(first).startswith("Error: Approval required")
        assert second == "ok"
        assert observed[0].allows("network")
        assert shared_state.get("active_execution_grant") is None

    @pytest.mark.asyncio
    async def test_approved_call_requires_stored_effect_coverage(self, temp_dir):
        approval_store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
        shared_state = {
            "approval_store": approval_store,
            "session_key": "session-a",
        }
        observed = []
        arguments = {"command": "python -m pytest", "network_access": True}
        stale_request = approval_store.request(
            "session-a",
            tool_name="run_command",
            arguments=arguments,
            granted_effects=("command_read",),
        )
        approval_store.approve("session-a", stale_request.id)

        class GrantTool(PolicyTool):
            async def execute(self, **kwargs):
                observed.append(shared_state.get("active_execution_grant"))
                return "ok"

        tool = GrantTool(
            "run_command",
            policy=ToolCallPolicy(effects=frozenset({"command_read", "network"})),
        )
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("execute", policy=PermissionPolicy(), shared_state=shared_state),
        ])

        result = await chain.run(tool, arguments)
        request = approval_store.get("session-a", stale_request.id)

        assert str(result).startswith("Error: Approval required")
        assert observed == []
        assert request.status == "pending"
        assert set(request.granted_effects) == {"command_read", "network"}

    @pytest.mark.asyncio
    async def test_policy_approval_required_normalizes_as_denied(self):
        chain = MiddlewareChain([PolicyPermissionMiddleware("execute")])

        result = await chain.run(FakeTool("run_command"), {"command": "npm install left-pad"})

        assert str(result).startswith("Error: Approval required")
        assert normalize_tool_result(result).status == "denied"

    @pytest.mark.asyncio
    async def test_approved_install_command_bypasses_intrinsic_allowlist_once(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        approval_store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
        shared_state = {
            "approval_store": approval_store,
            "session_key": "session-a",
        }
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="installed\n", stderr="")

        tool = RunCommandTool(workspace, shared_state=shared_state, command_runner=fake_run)
        chain = MiddlewareChain([
            PolicyPermissionMiddleware("execute", policy=PermissionPolicy(), shared_state=shared_state),
        ])

        first = await chain.run(tool, {"command": "npm install left-pad"})
        pending = approval_store.list("session-a", status="pending")
        approval_store.approve("session-a", pending[0].id)
        second = await chain.run(tool, {"command": "npm install left-pad"})

        assert normalize_tool_result(first).status == "denied"
        assert calls == [["npm", "install", "left-pad"]]
        assert "exit code 0" in second

    def test_load_permission_policy_reads_workspace_file(self, temp_dir, monkeypatch):
        monkeypatch.delenv("SMOLCLAW_PERMISSION_POLICY", raising=False)
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        policy_dir = os.path.join(temp_dir, ".smolclaw")
        os.makedirs(policy_dir, exist_ok=True)
        with open(os.path.join(policy_dir, "permissions.yaml"), "w", encoding="utf-8") as handle:
            handle.write(
                "rules:\n"
                "  - subject: command\n"
                "    pattern: npm install*\n"
                "    action: ask\n"
                "    reason: dependency changes need approval\n"
            )

        policy = load_permission_policy(workspace, include_user=False)

        assert len(policy.rules) == 1
        assert policy.rules[0].subject == "command"
        assert policy.rules[0].action == "ask"

    def test_load_permission_policy_never_reads_agents_md(self, temp_dir, monkeypatch):
        monkeypatch.delenv("SMOLCLAW_PERMISSION_POLICY", raising=False)
        with open(os.path.join(temp_dir, "AGENTS.md"), "w", encoding="utf-8") as handle:
            handle.write(
                "default_action: deny\n"
                "rules:\n"
                "  - subject: tool\n"
                "    pattern: read_file\n"
                "    action: deny\n"
            )
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

        policy = load_permission_policy(workspace, include_user=False)

        assert policy.default_action == "allow"
        assert policy.rules == ()

    def test_load_permission_policy_uses_user_rules_before_workspace_rules(self, temp_dir, monkeypatch):
        monkeypatch.delenv("SMOLCLAW_PERMISSION_POLICY", raising=False)
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        user_policy = os.path.join(temp_dir, "user-permissions.yaml")
        with open(user_policy, "w", encoding="utf-8") as handle:
            handle.write(
                "rules:\n"
                "  - subject: tool\n"
                "    pattern: read_file\n"
                "    action: allow\n"
                "    reason: user override\n"
            )
        policy_dir = os.path.join(temp_dir, ".smolclaw")
        os.makedirs(policy_dir, exist_ok=True)
        with open(os.path.join(policy_dir, "permissions.yaml"), "w", encoding="utf-8") as handle:
            handle.write(
                "rules:\n"
                "  - subject: tool\n"
                "    pattern: read_file\n"
                "    action: deny\n"
                "    reason: project deny\n"
            )

        policy = load_permission_policy(
            workspace,
            explicit_paths=(user_policy,),
            include_user=False,
        )

        assert [rule.action for rule in policy.rules] == ["allow", "deny"]


class TestFullMode:
    @pytest.mark.asyncio
    async def test_allows_write_file(self):
        mw = PermissionMiddleware("full")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("write_file"), {})
        assert result == "write_file executed"

    @pytest.mark.asyncio
    async def test_allows_exec(self):
        mw = PermissionMiddleware("full")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("exec"), {})
        assert result == "exec executed"

    @pytest.mark.asyncio
    async def test_allows_sequential_pipeline(self):
        mw = PermissionMiddleware("full")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("sequential_pipeline"), {})
        assert result == "sequential_pipeline executed"


class TestPlanMode:
    @pytest.mark.asyncio
    async def test_blocks_write_file(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("write_file"), {})
        assert result.startswith("Error:")
        assert "not permitted" in result
        assert "'plan'" in result

    @pytest.mark.asyncio
    async def test_blocks_edit_file(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("edit_file"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_memory_store(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("memory_store"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_memory_relate(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("memory_relate"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_allows_read_file(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("read_file"), {})
        assert result == "read_file executed"

    @pytest.mark.asyncio
    async def test_allows_memory_search(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("memory_search"), {})
        assert result == "memory_search executed"

    @pytest.mark.asyncio
    async def test_allows_contradiction_resolution(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool(
                "contradiction_review",
                policy_fn=lambda arguments: ToolCallPolicy(
                    mutates_state=arguments.get("action") == "resolve",
                    tags=frozenset({"memory", "contradiction"}),
                ),
            ),
            {"action": "resolve"},
        )
        assert result == "contradiction_review executed"

    @pytest.mark.asyncio
    async def test_allows_web_search(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("web_search"), {})
        assert result == "web_search executed"

    @pytest.mark.asyncio
    async def test_blocks_spawn_agent(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("spawn_agent"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_sequential_pipeline(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("sequential_pipeline"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_fanout_pipeline(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("fanout_pipeline"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_route(self):
        mw = PermissionMiddleware("plan")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("route"), {})
        assert result.startswith("Error:")


class TestExecuteMode:
    @pytest.mark.asyncio
    async def test_blocks_sequential_pipeline(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("sequential_pipeline"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_fanout_pipeline(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("fanout_pipeline"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_route(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("route"), {})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_allows_exec(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("exec"), {})
        assert result == "exec executed"

    @pytest.mark.asyncio
    async def test_allows_write_file(self):
        mw = PermissionMiddleware("execute")
        chain = MiddlewareChain([mw])
        result = await chain.run(FakeTool("write_file"), {})
        assert result == "write_file executed"


class TestResearchMode:
    @pytest.mark.asyncio
    async def test_allows_memory_store(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("memory_store", policy=ToolCallPolicy(mutates_state=True, tags=frozenset({"memory"}))),
            {},
        )
        assert result == "memory_store executed"

    @pytest.mark.asyncio
    async def test_blocks_write_file(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("write_file", policy=ToolCallPolicy(mutates_state=True, tags=frozenset({"filesystem", "write"}))),
            {},
        )
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_exec(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("exec", policy=ToolCallPolicy(mutates_state=True, tags=frozenset({"shell"}))),
            {},
        )
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_delegation(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("route", policy=ToolCallPolicy(delegates=True, tags=frozenset({"orchestration"}))),
            {},
        )
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_allows_contradiction_resolution(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool(
                "contradiction_review",
                policy_fn=lambda arguments: ToolCallPolicy(
                    mutates_state=arguments.get("action") == "resolve",
                    tags=frozenset({"memory", "contradiction"}),
                ),
            ),
            {"action": "resolve"},
        )
        assert result == "contradiction_review executed"

    @pytest.mark.asyncio
    async def test_allows_non_mutating_contradiction_review(self):
        mw = PermissionMiddleware("research")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool(
                "contradiction_review",
                policy_fn=lambda arguments: ToolCallPolicy(
                    mutates_state=arguments.get("action") == "resolve",
                    tags=frozenset({"memory", "contradiction"}),
                ),
            ),
            {"action": "list"},
        )
        assert result == "contradiction_review executed"


class TestDelegateOnlyMode:
    @pytest.mark.asyncio
    async def test_allows_route(self):
        mw = PermissionMiddleware("delegate_only")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("route", policy=ToolCallPolicy(delegates=True, tags=frozenset({"orchestration"}))),
            {},
        )
        assert result == "route executed"

    @pytest.mark.asyncio
    async def test_allows_spawn_agent(self):
        mw = PermissionMiddleware("delegate_only")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("spawn_agent", policy=ToolCallPolicy(delegates=True, tags=frozenset({"subagent"}))),
            {},
        )
        assert result == "spawn_agent executed"

    @pytest.mark.asyncio
    async def test_blocks_memory_store(self):
        mw = PermissionMiddleware("delegate_only")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool("memory_store", policy=ToolCallPolicy(mutates_state=True, tags=frozenset({"memory"}))),
            {},
        )
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_blocks_contradiction_resolution(self):
        mw = PermissionMiddleware("delegate_only")
        chain = MiddlewareChain([mw])
        result = await chain.run(
            PolicyTool(
                "contradiction_review",
                policy_fn=lambda arguments: ToolCallPolicy(
                    mutates_state=arguments.get("action") == "resolve",
                    tags=frozenset({"memory", "contradiction"}),
                ),
            ),
            {"action": "resolve"},
        )
        assert result.startswith("Error:")
        assert "mutates_state" in result


class TestUnknownMode:
    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown permission mode"):
            PermissionMiddleware("unknown_mode")


class TestPathPolicy:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["full", "execute", "research"])
    async def test_blocks_secret_env_paths_in_all_modes(self, mode):
        mw = PermissionMiddleware(mode)
        chain = MiddlewareChain([mw])

        result = await chain.run(FakeTool("read_file"), {"path": ".env.local"})

        assert result.startswith("Error:")
        assert "secret path" in result

    @pytest.mark.asyncio
    async def test_allows_env_example(self):
        mw = PermissionMiddleware("full")
        chain = MiddlewareChain([mw])

        result = await chain.run(FakeTool("read_file"), {"path": ".env.example"})

        assert result == "read_file executed"

    @pytest.mark.asyncio
    async def test_blocks_external_workspace_path(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        outside = os.path.realpath(os.path.join(temp_dir, "..", "outside.txt"))
        mw = PermissionMiddleware("full", workspace=workspace)
        chain = MiddlewareChain([mw])

        result = await chain.run(FakeTool("read_file"), {"path": outside})

        assert result.startswith("Error:")
        assert "external path" in result

    @pytest.mark.asyncio
    async def test_blocks_external_run_command_cwd(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        outside = os.path.realpath(os.path.join(temp_dir, ".."))
        mw = PermissionMiddleware("full", workspace=workspace)
        chain = MiddlewareChain([mw])

        result = await chain.run(FakeTool("run_command"), {"command": "git status", "cwd": outside})

        assert result.startswith("Error:")
        assert "external path" in result

    @pytest.mark.asyncio
    async def test_blocks_secret_git_diff_path(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        mw = PermissionMiddleware("full", workspace=workspace)
        chain = MiddlewareChain([mw])

        result = await chain.run(FakeTool("git_diff"), {"path": ".env.local"})

        assert result.startswith("Error:")
        assert "secret path" in result

    @pytest.mark.asyncio
    async def test_blocks_secret_apply_patch_target(self):
        mw = PermissionMiddleware("full")
        chain = MiddlewareChain([mw])
        patch_text = "\n".join([
            "*** Begin Patch",
            "*** Add File: .env.test",
            "+TOKEN=secret",
            "*** End Patch",
        ])

        result = await chain.run(FakeTool("apply_patch"), {"patch_text": patch_text})

        assert result.startswith("Error:")
        assert "secret path" in result


class TestPermissionModes:
    def test_full_blocks_nothing(self):
        assert PERMISSION_MODES["full"].blocked_tools == frozenset()

    def test_plan_blocks_expected_tools(self):
        expected = {
            "apply_patch",
            "write_file",
            "edit_file",
            "memory_store",
            "research_source_store",
            "memory_relate",
            "sequential_pipeline",
            "fanout_pipeline",
            "route",
            "spawn_agent",
        }
        assert PERMISSION_MODES["plan"].blocked_tools == frozenset(expected)

    def test_execute_blocks_expected_tools(self):
        expected = {"sequential_pipeline", "fanout_pipeline", "route", "spawn_agent"}
        assert PERMISSION_MODES["execute"].blocked_tools == frozenset(expected)

    def test_research_blocks_expected_tools(self):
        expected = {
            "apply_patch",
            "write_file",
            "edit_file",
            "memory_relate",
            "sequential_pipeline",
            "fanout_pipeline",
            "route",
            "spawn_agent",
        }
        assert PERMISSION_MODES["research"].blocked_tools == frozenset(expected)

    def test_delegate_only_blocks_expected_tools(self):
        expected = {
            "apply_patch",
            "write_file",
            "edit_file",
            "memory_store",
            "research_source_store",
            "memory_relate",
        }
        assert PERMISSION_MODES["delegate_only"].blocked_tools == frozenset(expected)
