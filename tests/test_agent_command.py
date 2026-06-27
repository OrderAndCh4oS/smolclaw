import subprocess

from app.agent_command import (
    AgentCommandRequest,
    CommandRunnerAgentExecutor,
    coerce_agent_command_executor,
)
from app.command_policy import CommandPolicyClassifier
from app.command_runner import CommandResult


class RecordingCommandRunner:
    def __init__(self):
        self.calls = []

    def run(self, args, *, cwd=None, input_text=None, timeout=600, network_access=False, execution_grant=None):
        self.calls.append({
            "args": args,
            "cwd": cwd,
            "input_text": input_text,
            "timeout": timeout,
            "network_access": network_access,
            "execution_grant": execution_grant,
        })
        return CommandResult(args=args, returncode=3, stdout="out", stderr="err")


def test_command_runner_agent_executor_uses_structured_request():
    runner = RecordingCommandRunner()
    executor = CommandRunnerAgentExecutor(runner)
    grant = object()

    result = executor.run(AgentCommandRequest(
        args=["pytest"],
        cwd="/workspace",
        input_text="input",
        timeout=9,
        network_access=True,
        execution_grant=grant,
    ))

    assert result.returncode == 3
    assert runner.calls == [{
        "args": ["pytest"],
        "cwd": "/workspace",
        "input_text": "input",
        "timeout": 9,
        "network_access": True,
        "execution_grant": grant,
    }]


def test_coerce_agent_command_executor_preserves_existing_executor():
    runner = RecordingCommandRunner()
    executor = CommandRunnerAgentExecutor(runner)

    assert coerce_agent_command_executor(executor) is executor


def test_coerce_agent_command_executor_wraps_subprocess_callable():
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    executor = coerce_agent_command_executor(fake_run)
    result = executor.run(AgentCommandRequest(args=["git", "status"], cwd="/repo", timeout=4))

    assert result.stdout == "ok"
    assert calls[0][0] == ["git", "status"]
    assert calls[0][1]["cwd"] == "/repo"


def test_command_policy_classifier_centralizes_run_command_rules():
    classifier = CommandPolicyClassifier()

    assert classifier.is_allowed(["python", "-m", "pytest"])[0] is True
    assert classifier.is_allowed(["rm", "file"])[0] is False
    assert classifier.may_mutate("echo hi > out.txt") is True
    assert classifier.may_mutate("git status") is False
    assert classifier.is_approval_bypassable(["npm", "install"]) is True
