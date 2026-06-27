import subprocess

import pytest

from app.command_adapters import AgentSubprocessAdapter, build_command_adapter_bundle
from app.command_runner import CommandResult
from app.runtime_config import AdapterSelection, RuntimeAdapterConfig
from app.sandbox import DockerCommandRunner
from app.workspace import WorkspaceContext


class FakeInfrastructureRunner:
    def __init__(self):
        self.calls = []

    def run(self, args, *, cwd=None, input_text=None, timeout=600, network_access=False):
        self.calls.append({
            "args": args,
            "cwd": cwd,
            "input_text": input_text,
            "timeout": timeout,
            "network_access": network_access,
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
        "network_access": False,
    }]


def test_command_adapter_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported command adapter provider 'remote'"):
        build_command_adapter_bundle(AdapterSelection("remote"))


def test_docker_command_adapter_requires_workspace():
    with pytest.raises(ValueError, match="requires a workspace"):
        build_command_adapter_bundle(AdapterSelection("docker"))


def test_docker_command_adapter_keeps_infrastructure_local_and_sandboxes_agent(temp_dir):
    sandbox_host = FakeInfrastructureRunner()
    bundle = build_command_adapter_bundle(
        AdapterSelection("docker", "custom-python:latest"),
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        sandbox_host_runner=sandbox_host,
        environ={},
    )

    completed = bundle.agent_runner(["python", "--version"], cwd=temp_dir, timeout=2)

    assert completed.returncode == 0
    assert isinstance(bundle.agent_runner.runner, DockerCommandRunner)
    assert bundle.infrastructure_runner is not bundle.agent_runner.runner
    assert sandbox_host.calls[-1]["args"][:3] == ["docker", "run", "--rm"]
    assert sandbox_host.calls[-1]["args"][-3:] == ["custom-python:latest", "python", "--version"]
    assert bundle.sandbox_metadata["provider"] == "docker"


def test_docker_command_adapter_uses_sandbox_config_over_legacy_model(temp_dir):
    sandbox_host = FakeInfrastructureRunner()
    config = RuntimeAdapterConfig.from_dict({
        "adapters": {
            "command": {
                "provider": "docker",
                "model": "legacy-image:latest",
                "sandbox": {
                    "image": "sandbox-image:latest",
                    "cpus": "6",
                    "memory": "6g",
                },
            },
        },
    })

    bundle = build_command_adapter_bundle(
        config.command,
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        sandbox_host_runner=sandbox_host,
        environ={},
    )
    bundle.agent_runner(["python", "--version"], cwd=temp_dir, timeout=2)

    args = sandbox_host.calls[-1]["args"]
    assert "sandbox-image:latest" in args
    assert "legacy-image:latest" not in args
    assert ["--cpus", "6"] == args[args.index("--cpus"):args.index("--cpus") + 2]
    assert ["--memory", "6g"] == args[args.index("--memory"):args.index("--memory") + 2]
    assert bundle.sandbox_metadata["image"] == "sandbox-image:latest"
