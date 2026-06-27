"""Sandbox backends for agent-controlled command execution."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.command_runner import CommandResult, CommandRunner, SubprocessCommandRunner
from app.execution_grants import ExecutionGrant, IMAGE_MANAGEMENT_EFFECT, NETWORK_EFFECT
from app.workspace import WorkspaceContext


DEFAULT_CONTAINER_IMAGE = "python:3.14-slim"
DEFAULT_CONTAINER_WORKSPACE = "/workspace"
DEFAULT_CONTAINER_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
DEFAULT_ENV_ALLOWLIST = ("CI", "LANG", "LC_ALL", "TERM")
TOOLCHAIN_IMAGE_RECOMMENDATIONS = {
    "python": "python:3.14-slim",
    "node": "node:22-bookworm-slim",
    "rust": "rust:1-bookworm",
    "go": "golang:1.24-bookworm",
}
TOOLCHAIN_MARKERS = {
    "python": ("pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "poetry.lock"),
    "node": ("package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"),
    "rust": ("Cargo.toml",),
    "go": ("go.mod",),
}
SENSITIVE_ENV_MARKERS = (
    "TOKEN",
    "KEY",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "OPENAI_",
    "ANTHROPIC_",
    "VOYAGE_",
    "AWS_",
    "AZURE_",
    "GOOGLE_",
    "GITHUB_",
    "SSH_",
)


class SandboxContext(Protocol):
    source_root: str
    state_root: str

    def run_command(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        input_text: str | None = None,
        timeout: int = 600,
    ) -> CommandResult:
        ...

    def export_diff(self) -> str:
        ...

    def cleanup(self) -> None:
        ...


class SandboxBackend(Protocol):
    def prepare(self, workspace: WorkspaceContext, run_id: str) -> SandboxContext:
        ...


@dataclass(frozen=True)
class SandboxEnvironmentPolicy:
    allowlist: tuple[str, ...] = DEFAULT_ENV_ALLOWLIST
    home: str = "/tmp"
    path: str = DEFAULT_CONTAINER_PATH

    def build(self, environ: Mapping[str, str]) -> tuple[dict[str, str], dict[str, Any]]:
        sandbox_env = {
            "HOME": self.home,
            "PATH": self.path,
        }
        allowed_from_host: list[str] = []
        for key in self.allowlist:
            if key in environ:
                sandbox_env[key] = environ[key]
                allowed_from_host.append(key)
        stripped_sensitive = [
            key
            for key in environ
            if key not in sandbox_env and _is_sensitive_env_key(key)
        ]
        return sandbox_env, {
            "allowed_host_keys": sorted(allowed_from_host),
            "injected_keys": sorted(set(sandbox_env) - set(allowed_from_host)),
            "stripped_sensitive_count": len(stripped_sensitive),
            "host_path_passthrough": False,
        }


SandboxEnvPolicy = SandboxEnvironmentPolicy


@dataclass(frozen=True)
class SandboxPolicy:
    image: str = DEFAULT_CONTAINER_IMAGE
    executable: str = "docker"
    container_workspace: str = DEFAULT_CONTAINER_WORKSPACE
    network: str = "none"
    approved_network: str = "bridge"
    user: str = field(default_factory=lambda: _default_user())
    cpus: str = "2"
    memory: str = "2g"
    pids_limit: int = 256
    tmpfs_size: str = "512m"
    read_only_root: bool = True
    network_proxy_env: Mapping[str, str] = field(default_factory=dict)
    auto_pull: bool = True
    auto_build: bool = False
    build_context: str | None = None
    build_dockerfile: str | None = None
    env_policy: SandboxEnvironmentPolicy = field(default_factory=SandboxEnvironmentPolicy)

    def metadata(
        self,
        *,
        workspace: WorkspaceContext,
        env_summary: Mapping[str, Any],
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "provider": "docker",
            "image": self.image,
            "executable": self.executable,
            "network": self.network,
            "approved_network": self.approved_network,
            "source_root": workspace.root_dir,
            "state_root": workspace.state_root_dir,
            "container_workspace": self.container_workspace,
            "resource_limits": {
                "cpus": self.cpus,
                "memory": self.memory,
                "pids": self.pids_limit,
                "tmpfs": f"/tmp:size={self.tmpfs_size}",
                "read_only_root": self.read_only_root,
            },
            "env_policy": dict(env_summary),
            "image_management": {
                "auto_pull": self.auto_pull,
                "auto_build": self.auto_build,
                "build_context": self.build_context,
                "build_dockerfile": self.build_dockerfile,
            },
            "warnings": list(warnings or []),
        }


@dataclass
class DockerSandboxContext:
    source_root: str
    state_root: str
    runner: "DockerCommandRunner"

    def run_command(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        input_text: str | None = None,
        timeout: int = 600,
    ) -> CommandResult:
        return self.runner.run(args, cwd=cwd, input_text=input_text, timeout=timeout)

    def export_diff(self) -> str:
        result = self.runner.host_runner.run(
            ["git", "-C", self.source_root, "diff", "--no-ext-diff", "--", "."],
            timeout=30,
        )
        return result.stdout if result.returncode == 0 else result.output

    def cleanup(self) -> None:
        return None


class DockerSandboxBackend:
    def __init__(
        self,
        *,
        policy: SandboxPolicy | None = None,
        host_runner: CommandRunner | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.policy = policy or SandboxPolicy()
        self.host_runner = host_runner
        self.environ = environ

    def prepare(self, workspace: WorkspaceContext, run_id: str) -> DockerSandboxContext:
        runner = DockerCommandRunner(
            workspace=workspace,
            policy=self.policy,
            host_runner=self.host_runner,
            environ=self.environ,
        )
        return DockerSandboxContext(
            source_root=workspace.root_dir,
            state_root=workspace.state_root_dir,
            runner=runner,
        )


class DockerNetworkPolicy:
    def __init__(self, policy: SandboxPolicy):
        self.policy = policy

    def access_error(self, *, network_access: bool, execution_grant: ExecutionGrant | None) -> str | None:
        if not network_access:
            return None
        if not _grant_allows(execution_grant, NETWORK_EFFECT):
            return "Error: Approval required for Docker sandbox network access."
        if not self.policy.network_proxy_env:
            return "Error: Docker sandbox network access requires configured network_proxy_env."
        return None

    def selected_network(self, *, network_access: bool) -> str:
        return self.policy.approved_network if network_access else self.policy.network


class DockerImageManager:
    def __init__(self, *, policy: SandboxPolicy, host_runner: CommandRunner):
        self.policy = policy
        self.host_runner = host_runner
        self._image_ready = False

    def ensure_image(self, *, timeout: int, execution_grant: ExecutionGrant | None = None) -> CommandResult | None:
        if self._image_ready:
            return None
        image = self.policy.image
        result = self.host_runner.run(
            [self.policy.executable, "image", "inspect", image],
            timeout=min(timeout, 30),
        )
        if result.returncode == 0:
            self._image_ready = True
            return None
        if result.returncode in {125, 126, 127} and _looks_like_docker_runtime_failure(result.stderr):
            return CommandResult(
                args=result.args,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=_format_docker_runtime_failure(result.stderr),
            )
        if self.image_management_enabled() and not _grant_allows(execution_grant, IMAGE_MANAGEMENT_EFFECT):
            return CommandResult(
                args=result.args,
                returncode=126,
                stdout=result.stdout,
                stderr=(
                    "Error: Approval required for Docker image build/pull before "
                    f"using sandbox image: {image}"
                ),
            )
        if self.policy.auto_build and self.policy.build_context:
            build_args = [self.policy.executable, "build", "-t", image]
            if self.policy.build_dockerfile:
                build_args.extend(["-f", self.policy.build_dockerfile])
            build_args.append(self.policy.build_context)
            build = self.host_runner.run(build_args, timeout=max(timeout, 1800))
            if build.returncode != 0:
                return CommandResult(
                    args=build.args,
                    returncode=build.returncode,
                    stdout=build.stdout,
                    stderr="Docker sandbox image build failed.\n" + (build.stderr or build.stdout or ""),
                )
            self._image_ready = True
            return None
        if self.policy.auto_pull:
            pull = self.host_runner.run(
                [self.policy.executable, "pull", image],
                timeout=max(timeout, 1800),
            )
            if pull.returncode != 0:
                return CommandResult(
                    args=pull.args,
                    returncode=pull.returncode,
                    stdout=pull.stdout,
                    stderr="Docker sandbox image pull failed.\n" + (pull.stderr or pull.stdout or ""),
                )
            self._image_ready = True
            return None
        return CommandResult(
            args=result.args,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=f"Docker sandbox image is not available and automatic pull/build is disabled: {image}",
        )

    def requires_image_management_approval(self) -> bool:
        if self._image_ready or not self.image_management_enabled():
            return False
        image = self.policy.image
        result = self.host_runner.run(
            [self.policy.executable, "image", "inspect", image],
            timeout=30,
        )
        if result.returncode == 0:
            self._image_ready = True
            return False
        if result.returncode in {125, 126, 127} and _looks_like_docker_runtime_failure(result.stderr):
            return False
        return True

    def image_management_enabled(self) -> bool:
        return bool((self.policy.auto_build and self.policy.build_context) or self.policy.auto_pull)


class DockerCommandBuilder:
    def __init__(
        self,
        *,
        workspace: WorkspaceContext,
        policy: SandboxPolicy,
        sandbox_env: Mapping[str, str],
        network_policy: DockerNetworkPolicy,
    ):
        self.workspace = workspace
        self.policy = policy
        self.sandbox_env = sandbox_env
        self.network_policy = network_policy

    def build(
        self,
        args: list[str],
        *,
        host_cwd: str,
        interactive: bool,
        network_access: bool = False,
    ) -> tuple[list[str], dict[str, str] | None]:
        policy = self.policy
        container_cwd = self.container_cwd(host_cwd)
        network = self.network_policy.selected_network(network_access=network_access)
        extra_env: dict[str, str] = {}
        docker_args = [
            policy.executable,
            "run",
            "--rm",
        ]
        if interactive:
            docker_args.append("-i")
        docker_args.extend([
            "--network",
            network,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            policy.cpus,
            "--memory",
            policy.memory,
            "--pids-limit",
            str(policy.pids_limit),
            "--user",
            policy.user,
            "--workdir",
            container_cwd,
            "--tmpfs",
            f"/tmp:rw,nosuid,nodev,size={policy.tmpfs_size}",
        ])
        if policy.read_only_root:
            docker_args.append("--read-only")
        if network_access:
            for key, value in policy.network_proxy_env.items():
                docker_args.extend(["-e", key])
                extra_env[str(key)] = str(value)
        for key, value in sorted(dict(self.sandbox_env).items()):
            docker_args.extend(["-e", f"{key}={value}"])
        docker_args.extend([
            "-v",
            f"{self.workspace.root_dir}:{policy.container_workspace}:rw",
            policy.image,
            *args,
        ])
        return docker_args, extra_env or None

    def container_cwd(self, host_cwd: str) -> str:
        rel = os.path.relpath(os.path.realpath(host_cwd), self.workspace.root_dir)
        if rel == ".":
            return self.policy.container_workspace
        return self.policy.container_workspace.rstrip("/") + "/" + rel.replace(os.sep, "/")


class DockerCommandRunner:
    """Run agent commands through one-shot Docker containers."""

    supports_docker_sandbox = True
    supports_shell_sessions = True

    def __init__(
        self,
        *,
        workspace: WorkspaceContext,
        policy: SandboxPolicy | None = None,
        host_runner: CommandRunner | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.workspace = workspace
        self.policy = policy or SandboxPolicy()
        self.host_runner = host_runner or SubprocessCommandRunner()
        self.environ = environ if environ is not None else os.environ
        self._sandbox_env, self._env_summary = self.policy.env_policy.build(self.environ)
        self.network_policy = DockerNetworkPolicy(self.policy)
        self.image_manager = DockerImageManager(policy=self.policy, host_runner=self.host_runner)
        self.command_builder = DockerCommandBuilder(
            workspace=self.workspace,
            policy=self.policy,
            sandbox_env=self._sandbox_env,
            network_policy=self.network_policy,
        )
        self.metadata = self.policy.metadata(
            workspace=workspace,
            env_summary=self._env_summary,
            warnings=self._metadata_warnings(),
        )

    def run(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        input_text: str | None = None,
        timeout: int = 600,
        network_access: bool = False,
        execution_grant: ExecutionGrant | None = None,
    ) -> CommandResult:
        if not args:
            return CommandResult(args=args, returncode=2, stderr="No command provided.")
        host_cwd, error = self.workspace.resolve_contained_path(cwd or ".", label="cwd")
        if error:
            return CommandResult(args=args, returncode=126, stderr=error)
        network_error = self.network_policy.access_error(
            network_access=network_access,
            execution_grant=execution_grant,
        )
        if network_error:
            return CommandResult(args=list(args), returncode=126, stderr=network_error)
        image_result = self._ensure_image(timeout=timeout, execution_grant=execution_grant)
        if image_result is not None:
            return CommandResult(args=list(args), returncode=image_result.returncode, stdout=image_result.stdout, stderr=image_result.stderr)
        docker_args, extra_env = self._docker_args(
            args,
            host_cwd=host_cwd or self.workspace.root_dir,
            interactive=input_text is not None,
            network_access=network_access,
        )
        run_kwargs = {
            "input_text": input_text,
            "timeout": timeout,
        }
        if extra_env:
            run_kwargs["extra_env"] = extra_env
        result = self.host_runner.run(docker_args, **run_kwargs)
        if result.returncode in {125, 126, 127} and _looks_like_docker_runtime_failure(result.stderr):
            return CommandResult(
                args=list(args),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=_format_docker_runtime_failure(result.stderr),
            )
        return CommandResult(
            args=list(args),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _docker_args(self, args: list[str], *, host_cwd: str, interactive: bool, network_access: bool = False) -> tuple[list[str], dict[str, str] | None]:
        return self.command_builder.build(
            args,
            host_cwd=host_cwd,
            interactive=interactive,
            network_access=network_access,
        )

    def _ensure_image(self, *, timeout: int, execution_grant: ExecutionGrant | None = None) -> CommandResult | None:
        return self.image_manager.ensure_image(timeout=timeout, execution_grant=execution_grant)

    def requires_image_management_approval(self) -> bool:
        return self.image_manager.requires_image_management_approval()

    def _image_management_enabled(self) -> bool:
        return self.image_manager.image_management_enabled()

    def _network_access_error(self, execution_grant: ExecutionGrant | None) -> str | None:
        return self.network_policy.access_error(network_access=True, execution_grant=execution_grant)

    def _container_cwd(self, host_cwd: str) -> str:
        return self.command_builder.container_cwd(host_cwd)

    def _metadata_warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.workspace.root_dir != self.workspace.state_root_dir:
            warnings.append("Sandbox mounts only the isolated source root; durable state remains on the host.")
        toolchains = detect_project_toolchains(self.workspace)
        if self.policy.image == DEFAULT_CONTAINER_IMAGE:
            missing_toolchains = [toolchain for toolchain in toolchains if toolchain != "python"]
            if missing_toolchains:
                warnings.append(
                    "Generic sandbox image python:3.14-slim may not include project toolchains: "
                    + ", ".join(missing_toolchains)
                    + ". Configure adapters.command.sandbox.image for this project."
                )
        return warnings


def sandbox_policy_from_selection(selection=None) -> SandboxPolicy:
    if isinstance(selection, str) or selection is None:
        return SandboxPolicy(image=selection or DEFAULT_CONTAINER_IMAGE)
    sandbox_config = getattr(selection, "sandbox", None)
    legacy_image = getattr(selection, "model", None)
    if sandbox_config is None:
        return SandboxPolicy(image=legacy_image or DEFAULT_CONTAINER_IMAGE)
    env_allowlist = getattr(sandbox_config, "env_allowlist", None)
    env_policy = SandboxEnvironmentPolicy(
        allowlist=tuple(env_allowlist) if env_allowlist is not None else DEFAULT_ENV_ALLOWLIST,
    )
    return SandboxPolicy(
        image=getattr(sandbox_config, "image", None) or legacy_image or DEFAULT_CONTAINER_IMAGE,
        network=getattr(sandbox_config, "network", "none"),
        approved_network=getattr(sandbox_config, "approved_network", "bridge"),
        cpus=getattr(sandbox_config, "cpus", "2"),
        memory=getattr(sandbox_config, "memory", "2g"),
        pids_limit=getattr(sandbox_config, "pids_limit", 256),
        tmpfs_size=getattr(sandbox_config, "tmpfs_size", "512m"),
        read_only_root=getattr(sandbox_config, "read_only_root", True),
        network_proxy_env=dict(getattr(sandbox_config, "network_proxy_env", {}) or {}),
        auto_pull=getattr(sandbox_config, "auto_pull", True),
        auto_build=getattr(sandbox_config, "auto_build", False),
        build_context=getattr(sandbox_config, "build_context", None),
        build_dockerfile=getattr(sandbox_config, "build_dockerfile", None),
        env_policy=env_policy,
    )


def detect_project_toolchains(workspace: WorkspaceContext) -> tuple[str, ...]:
    detected: list[str] = []
    for toolchain, markers in TOOLCHAIN_MARKERS.items():
        if any(os.path.exists(workspace.resolve_path(marker)) for marker in markers):
            detected.append(toolchain)
    return tuple(detected)


def recommended_sandbox_image(toolchains: tuple[str, ...]) -> str | None:
    if not toolchains:
        return None
    if len(toolchains) == 1:
        return TOOLCHAIN_IMAGE_RECOMMENDATIONS.get(toolchains[0])
    return "custom image with " + ", ".join(toolchains)


def docker_availability_check(command_runner: CommandRunner | None = None) -> CommandResult:
    runner = command_runner or SubprocessCommandRunner()
    result = runner.run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=5)
    if result.returncode in {125, 126, 127} and _looks_like_docker_runtime_failure(result.stderr):
        return CommandResult(
            args=result.args,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=_format_docker_runtime_failure(result.stderr),
        )
    return result


def _default_user() -> str:
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        return f"{os.getuid()}:{os.getgid()}"
    return "1000:1000"


def _is_sensitive_env_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in SENSITIVE_ENV_MARKERS)


def _looks_like_docker_runtime_failure(stderr: str | None) -> bool:
    text = (stderr or "").lower()
    return (
        "docker" in text
        or "cannot connect to the docker daemon" in text
        or "is the docker daemon running" in text
        or "no such file or directory" in text
    )


def _format_docker_runtime_failure(stderr: str | None) -> str:
    detail = (stderr or "").strip()
    message = (
        "Docker sandbox unavailable. Install/start Docker, verify daemon access, "
        "then retry the Docker command provider."
    )
    return f"{message}\n{detail}" if detail else message


def _grant_allows(grant: ExecutionGrant | None, effect: str) -> bool:
    return bool(grant is not None and grant.allows(effect))
