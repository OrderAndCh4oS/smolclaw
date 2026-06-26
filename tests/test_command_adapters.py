import subprocess

import pytest

from app.command_adapters import AgentSubprocessAdapter, build_command_adapter_bundle
from app.command_runner import CommandResult
from app.runtime_config import AdapterSelection


class FakeInfrastructureRunner:
    def __init__(self):
        self.calls = []

    def run(self, args, *, cwd=None, input_text=None, timeout=600):
        self.calls.append({
            "args": args,
            "cwd": cwd,
            "input_text": input_text,
            "timeout": timeout,
        })
        return CommandResult(args=args, returncode=0, stdout="ok", stderr="")


def test_agent_subprocess_adapter_preserves_subprocess_run_shape():
    runner = FakeInfrastructureRunner()
    adapter = AgentSubprocessAdapter(runner)

    result = adapter(
        ["echo", "hi"],
        cwd="/tmp",
        input=b"hello",
        text=True,
        timeout=3,
        check=False,
    )

    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert result.stdout == "ok"
    assert runner.calls == [{
        "args": ["echo", "hi"],
        "cwd": "/tmp",
        "input_text": "hello",
        "timeout": 3,
    }]


def test_command_adapter_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported command adapter provider 'remote'"):
        build_command_adapter_bundle(AdapterSelection("remote"))
