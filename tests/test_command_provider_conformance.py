import os

from app.command_adapters import AgentSubprocessAdapter
from app.command_runner import CommandResult
from app.sandbox import DockerCommandRunner
from app.workspace import WorkspaceContext


class RecordingRunner:
    def __init__(self, result=None, results=None):
        self.calls = []
        self.result = result or CommandResult(args=[], returncode=7, stdout="out", stderr="err")
        self.results = list(results or [])

    def run(self, args, *, cwd=None, input_text=None, timeout=600, network_access=False):
        self.calls.append({
            "args": args,
            "cwd": cwd,
            "input_text": input_text,
            "timeout": timeout,
            "network_access": network_access,
        })
        if self.results:
            result = self.results.pop(0)
            return CommandResult(
                args=args,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return CommandResult(
            args=args,
            returncode=self.result.returncode,
            stdout=self.result.stdout,
            stderr=self.result.stderr,
        )


def test_agent_subprocess_adapter_contract_for_output_timeout_and_nonzero():
    runner = RecordingRunner()
    adapter = AgentSubprocessAdapter(runner)

    result = adapter(["tool"], cwd="/tmp", input="input", text=True, timeout=9)

    assert result.args == ["tool"]
    assert result.returncode == 7
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert runner.calls == [{
        "args": ["tool"],
        "cwd": "/tmp",
        "input_text": "input",
        "timeout": 9,
        "network_access": False,
    }]


def test_docker_provider_contract_for_containment_env_and_metadata(temp_dir):
    host_runner = RecordingRunner(results=[
        CommandResult(args=[], returncode=0, stdout="image"),
        CommandResult(args=[], returncode=7, stdout="out", stderr="err"),
    ])
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    runner = DockerCommandRunner(
        workspace=workspace,
        host_runner=host_runner,
        environ={
            "OPENAI_API_KEY": "secret",
            "CI": "true",
        },
    )

    result = runner.run(["tool"], cwd=temp_dir, input_text="input", timeout=9)
    escaped = runner.run(["tool"], cwd="/")

    docker_args = host_runner.calls[-1]["args"]
    assert result.returncode == 7
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert host_runner.calls[-1]["input_text"] == "input"
    assert host_runner.calls[-1]["timeout"] == 9
    assert ["--workdir", "/workspace"] == docker_args[docker_args.index("--workdir"):docker_args.index("--workdir") + 2]
    assert f"{os.path.realpath(temp_dir)}:/workspace:rw" in docker_args
    assert "OPENAI_API_KEY=secret" not in docker_args
    assert "CI=true" in docker_args
    assert runner.metadata["provider"] == "docker"
    assert runner.metadata["network"] == "none"
    assert escaped.returncode == 126
    assert "outside workspace" in escaped.stderr
