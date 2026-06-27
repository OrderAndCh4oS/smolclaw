import os

import pytest

from app.command_runner import CommandResult
from app.execution_grants import ExecutionGrant, IMAGE_MANAGEMENT_EFFECT, NETWORK_EFFECT
from app.runtime_config import RuntimeAdapterConfig
from app.sandbox import (
    DockerCommandBuilder,
    DockerCommandRunner,
    DockerImageManager,
    DockerNetworkPolicy,
    SandboxPolicy,
    detect_project_toolchains,
    docker_availability_check,
    recommended_sandbox_image,
    sandbox_policy_from_selection,
)
from app.workspace import WorkspaceContext


class FakeHostRunner:
    def __init__(self, result: CommandResult | None = None, results: list[CommandResult] | None = None):
        self.calls = []
        self.result = result or CommandResult(args=[], returncode=0, stdout="ok", stderr="")
        self.results = list(results or [])

    def run(self, args, *, cwd=None, input_text=None, timeout=600, network_access=False, execution_grant=None, extra_env=None):
        self.calls.append({
            "args": args,
            "cwd": cwd,
            "input_text": input_text,
            "timeout": timeout,
            "network_access": network_access,
            "execution_grant": execution_grant,
            "extra_env": extra_env,
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


def test_docker_command_runner_builds_confined_command_and_strips_secrets(temp_dir):
    host = FakeHostRunner()
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    runner = DockerCommandRunner(
        workspace=workspace,
        host_runner=host,
        environ={
            "OPENAI_API_KEY": "secret",
            "GITHUB_TOKEN": "secret",
            "LANG": "C.UTF-8",
            "PATH": "/host/bin",
        },
    )

    result = runner.run(["python", "-m", "pytest"], cwd=temp_dir, input_text="stdin", timeout=5)

    assert result.args == ["python", "-m", "pytest"]
    assert result.returncode == 0
    call = host.calls[-1]
    args = call["args"]
    assert args[:4] == ["docker", "run", "--rm", "-i"]
    assert ["--network", "none"] == args[args.index("--network"):args.index("--network") + 2]
    assert ["--cap-drop", "ALL"] == args[args.index("--cap-drop"):args.index("--cap-drop") + 2]
    assert ["--security-opt", "no-new-privileges"] == args[args.index("--security-opt"):args.index("--security-opt") + 2]
    assert ["--workdir", "/workspace"] == args[args.index("--workdir"):args.index("--workdir") + 2]
    assert "--read-only" in args
    assert f"{os.path.realpath(temp_dir)}:/workspace:rw" in args
    assert args[-4:] == ["python:3.14-slim", "python", "-m", "pytest"]
    assert "/var/run/docker.sock" not in " ".join(args)
    assert os.path.expanduser("~") not in args
    assert "OPENAI_API_KEY=secret" not in args
    assert "GITHUB_TOKEN=secret" not in args
    assert "PATH=/host/bin" not in args
    assert "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" in args
    assert "LANG=C.UTF-8" in args
    assert call["input_text"] == "stdin"
    assert call["timeout"] == 5
    assert runner.metadata["env_policy"]["stripped_sensitive_count"] == 2
    assert runner.metadata["env_policy"]["host_path_passthrough"] is False


def test_docker_command_runner_maps_subdirectory_cwd(temp_dir):
    host = FakeHostRunner()
    subdir = os.path.join(temp_dir, "pkg")
    os.makedirs(subdir)
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        host_runner=host,
        environ={},
    )

    runner.run(["pwd"], cwd=subdir)

    args = host.calls[-1]["args"]
    assert ["--workdir", "/workspace/pkg"] == args[args.index("--workdir"):args.index("--workdir") + 2]


def test_docker_command_runner_rejects_cwd_outside_workspace(temp_dir):
    host = FakeHostRunner()
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        host_runner=host,
        environ={},
    )

    result = runner.run(["pwd"], cwd="/")

    assert result.returncode == 126
    assert "outside workspace" in result.stderr
    assert host.calls == []


def test_docker_command_runner_uses_custom_image(temp_dir):
    host = FakeHostRunner()
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        policy=SandboxPolicy(image="smolclaw-dev:latest"),
        host_runner=host,
        environ={},
    )

    runner.run(["pytest"])

    assert "smolclaw-dev:latest" in host.calls[-1]["args"]
    assert runner.metadata["image"] == "smolclaw-dev:latest"


def test_sandbox_policy_from_command_config_prefers_sandbox_image():
    config = RuntimeAdapterConfig.from_dict({
        "adapters": {
            "command": {
                "provider": "docker",
                "model": "legacy-image:latest",
                "sandbox": {
                    "image": "sandbox-image:latest",
                    "cpus": "3",
                    "memory": "3g",
                    "pids_limit": 128,
                    "tmpfs_size": "768m",
                    "read_only_root": False,
                    "env_allowlist": ["CUSTOM_FLAG"],
                },
            }
        }
    })

    policy = sandbox_policy_from_selection(config.command)

    assert policy.image == "sandbox-image:latest"
    assert policy.cpus == "3"
    assert policy.memory == "3g"
    assert policy.pids_limit == 128
    assert policy.tmpfs_size == "768m"
    assert policy.read_only_root is False
    env, summary = policy.env_policy.build({"CUSTOM_FLAG": "1", "LANG": "C.UTF-8"})
    assert env["CUSTOM_FLAG"] == "1"
    assert "LANG" not in summary["allowed_host_keys"]


def test_docker_command_runner_formats_docker_runtime_failure(temp_dir):
    host = FakeHostRunner(CommandResult(
        args=[],
        returncode=125,
        stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
    ))
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        host_runner=host,
        environ={},
    )

    result = runner.run(["pytest"])

    assert result.returncode == 125
    assert "Docker sandbox unavailable" in result.stderr
    assert "Docker daemon" in result.stderr


def test_docker_command_runner_network_access_uses_approved_network_and_proxy(temp_dir):
    host = FakeHostRunner()
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        policy=SandboxPolicy(
            approved_network="bridge",
            network_proxy_env={"HTTPS_PROXY": "http://proxy.local:8080"},
        ),
        host_runner=host,
        environ={},
    )

    grant = ExecutionGrant(
        tool_name="run_command",
        arguments_hash="hash",
        approval_id="apr-network",
        effects=frozenset({NETWORK_EFFECT}),
    )

    runner.run(["python", "-m", "pytest"])
    offline_args = host.calls[-1]["args"]
    denied = runner.run(["python", "-m", "pytest"], network_access=True)
    runner.run(["python", "-m", "pytest"], network_access=True, execution_grant=grant)
    online_args = host.calls[-1]["args"]

    assert denied.returncode == 126
    assert "Approval required" in denied.stderr
    assert ["--network", "none"] == offline_args[offline_args.index("--network"):offline_args.index("--network") + 2]
    assert "HTTPS_PROXY=http://proxy.local:8080" not in offline_args
    assert ["--network", "bridge"] == online_args[online_args.index("--network"):online_args.index("--network") + 2]
    assert "HTTPS_PROXY" in online_args
    assert "HTTPS_PROXY=http://proxy.local:8080" not in online_args
    assert host.calls[-1]["extra_env"] == {"HTTPS_PROXY": "http://proxy.local:8080"}


def test_docker_command_runner_rejects_network_without_proxy_config(temp_dir):
    host = FakeHostRunner()
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        policy=SandboxPolicy(approved_network="bridge"),
        host_runner=host,
        environ={},
    )
    grant = ExecutionGrant(
        tool_name="run_command",
        arguments_hash="hash",
        approval_id="apr-network",
        effects=frozenset({NETWORK_EFFECT}),
    )

    result = runner.run(["python", "-m", "pytest"], network_access=True, execution_grant=grant)

    assert result.returncode == 126
    assert "network_proxy_env" in result.stderr
    assert host.calls == []


def test_docker_command_runner_auto_pulls_missing_image(temp_dir):
    host = FakeHostRunner(results=[
        CommandResult(args=[], returncode=1, stderr="missing image"),
        CommandResult(args=[], returncode=0, stdout="pulled"),
        CommandResult(args=[], returncode=0, stdout="ran"),
    ])
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        policy=SandboxPolicy(image="project:latest", auto_pull=True),
        host_runner=host,
        environ={},
    )
    grant = ExecutionGrant(
        tool_name="run_command",
        arguments_hash="hash",
        approval_id="apr-image",
        effects=frozenset({IMAGE_MANAGEMENT_EFFECT}),
    )

    result = runner.run(["pytest"], execution_grant=grant)

    assert result.returncode == 0
    assert host.calls[0]["args"] == ["docker", "image", "inspect", "project:latest"]
    assert host.calls[1]["args"] == ["docker", "pull", "project:latest"]
    assert host.calls[2]["args"][:3] == ["docker", "run", "--rm"]


def test_docker_command_runner_auto_builds_missing_image(temp_dir):
    host = FakeHostRunner(results=[
        CommandResult(args=[], returncode=1, stderr="missing image"),
        CommandResult(args=[], returncode=0, stdout="built"),
        CommandResult(args=[], returncode=0, stdout="ran"),
    ])
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        policy=SandboxPolicy(
            image="project:latest",
            auto_build=True,
            build_context=temp_dir,
            build_dockerfile=os.path.join(temp_dir, "Dockerfile.sandbox"),
        ),
        host_runner=host,
        environ={},
    )
    grant = ExecutionGrant(
        tool_name="run_command",
        arguments_hash="hash",
        approval_id="apr-image",
        effects=frozenset({IMAGE_MANAGEMENT_EFFECT}),
    )

    result = runner.run(["pytest"], execution_grant=grant)

    assert result.returncode == 0
    assert host.calls[1]["args"] == [
        "docker",
        "build",
        "-t",
        "project:latest",
        "-f",
        os.path.join(temp_dir, "Dockerfile.sandbox"),
        temp_dir,
    ]


def test_docker_command_runner_requires_grant_before_image_pull(temp_dir):
    host = FakeHostRunner(results=[
        CommandResult(args=[], returncode=1, stderr="missing image"),
    ])
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        policy=SandboxPolicy(image="project:latest", auto_pull=True),
        host_runner=host,
        environ={},
    )

    result = runner.run(["pytest"])

    assert result.returncode == 126
    assert "Approval required" in result.stderr
    assert len(host.calls) == 1
    assert host.calls[0]["args"] == ["docker", "image", "inspect", "project:latest"]


def test_docker_sandbox_services_are_explicit_boundaries(temp_dir):
    host = FakeHostRunner(results=[
        CommandResult(args=[], returncode=1, stderr="missing image"),
    ])
    policy = SandboxPolicy(
        image="project:latest",
        network_proxy_env={"HTTPS_PROXY": "http://proxy.local:8080"},
    )
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    network_policy = DockerNetworkPolicy(policy)
    builder = DockerCommandBuilder(
        workspace=workspace,
        policy=policy,
        sandbox_env={"HOME": "/tmp"},
        network_policy=network_policy,
    )
    image_manager = DockerImageManager(policy=policy, host_runner=host)
    grant = ExecutionGrant(
        tool_name="run_command",
        arguments_hash="hash",
        approval_id="apr-network",
        effects=frozenset({NETWORK_EFFECT}),
    )

    args, extra_env = builder.build(["pytest"], host_cwd=temp_dir, interactive=False, network_access=True)
    image_result = image_manager.ensure_image(timeout=10)

    assert network_policy.access_error(network_access=True, execution_grant=grant) is None
    assert ["--network", "bridge"] == args[args.index("--network"):args.index("--network") + 2]
    assert extra_env == {"HTTPS_PROXY": "http://proxy.local:8080"}
    assert image_result.returncode == 126
    assert "Approval required" in image_result.stderr


def test_docker_availability_check_formats_missing_docker():
    host = FakeHostRunner(CommandResult(
        args=[],
        returncode=127,
        stderr="[Errno 2] No such file or directory: 'docker'",
    ))

    result = docker_availability_check(host)

    assert result.returncode == 127
    assert "Docker sandbox unavailable" in result.stderr


def test_detect_project_toolchains_and_recommendation(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    with open(os.path.join(temp_dir, "package.json"), "w", encoding="utf-8") as handle:
        handle.write("{}")
    with open(os.path.join(temp_dir, "go.mod"), "w", encoding="utf-8") as handle:
        handle.write("module example.test/app\n")

    toolchains = detect_project_toolchains(workspace)

    assert toolchains == ("node", "go")
    assert recommended_sandbox_image(toolchains) == "custom image with node, go"


def test_docker_metadata_warns_when_generic_image_misses_toolchain(temp_dir):
    with open(os.path.join(temp_dir, "package.json"), "w", encoding="utf-8") as handle:
        handle.write("{}")

    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        host_runner=FakeHostRunner(),
        environ={},
    )

    assert any("may not include project toolchains: node" in warning for warning in runner.metadata["warnings"])


@pytest.mark.skipif(
    not os.getenv("SMOLCLAW_LIVE_DOCKER_TESTS"),
    reason="set SMOLCLAW_LIVE_DOCKER_TESTS=1 to run live Docker smoke tests",
)
def test_live_docker_sandbox_blocks_network_by_default(temp_dir):
    runner = DockerCommandRunner(
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        environ={},
    )

    result = runner.run([
        "python",
        "-c",
        "import socket; socket.create_connection(('example.com', 80), timeout=2)",
    ], timeout=10)

    assert result.returncode != 0
