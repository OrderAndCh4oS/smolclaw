"""Command adapter provider wiring.

The infrastructure command runner is used by SmolClaw itself for worktrees,
work-loop providers, and other host-side integrations. The agent command
runner exposes the subprocess.run-shaped callable expected by command tools.
Both are built from the same runtime adapter selection so adapter config is
respected consistently.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agent_command import AgentCommandExecutor, CommandRunnerAgentExecutor
from app.command_runner import CommandRunner, SubprocessCommandRunner
from app.execution_grants import ExecutionGrant
from app.runtime_config import AdapterSelection
from app.sandbox import DockerCommandRunner, sandbox_policy_from_selection
from app.workspace import WorkspaceContext


SUPPORTED_COMMAND_PROVIDERS = frozenset({"subprocess", "docker"})


@dataclass(frozen=True)
class CommandAdapterBundle:
    infrastructure_runner: CommandRunner
    agent_runner: Callable[..., subprocess.CompletedProcess]
    agent_executor: AgentCommandExecutor
    sandbox_metadata: dict[str, Any] | None = None


class AgentSubprocessAdapter:
    """Expose a CommandRunner through the subset of subprocess.run we use."""

    def __init__(self, runner: CommandRunner):
        self.runner = runner

    def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: str | None = None,
        input=None,
        text: bool | None = None,
        stdout=None,
        stderr=None,
        timeout: int | float | None = None,
        check: bool = False,
        network_access: bool = False,
        execution_grant: ExecutionGrant | None = None,
        **_kwargs,
    ) -> subprocess.CompletedProcess:
        input_text = self._coerce_input(input, text=text)
        run_kwargs = {
            "cwd": cwd,
            "input_text": input_text,
            "timeout": int(timeout) if timeout is not None else 600,
            "network_access": network_access,
        }
        if execution_grant is not None:
            run_kwargs["execution_grant"] = execution_grant
        result = self.runner.run(list(args), **run_kwargs)
        completed = subprocess.CompletedProcess(
            args=list(args),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        if check and completed.returncode:
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed

    @staticmethod
    def _coerce_input(value, *, text: bool | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace") if text else value.decode(errors="replace")
        return str(value)

    @property
    def supports_docker_sandbox(self) -> bool:
        return bool(getattr(self.runner, "supports_docker_sandbox", False))

    @property
    def supports_shell_sessions(self) -> bool:
        return bool(getattr(self.runner, "supports_shell_sessions", False))

    def requires_image_management_approval(self) -> bool:
        checker = getattr(self.runner, "requires_image_management_approval", None)
        return bool(checker()) if callable(checker) else False


def build_command_adapter_bundle(
    selection: AdapterSelection | None = None,
    *,
    workspace: WorkspaceContext | str | None = None,
    process_factory: Callable[..., subprocess.Popen] | None = None,
    environ: Mapping[str, str] | None = None,
    sandbox_host_runner: CommandRunner | None = None,
) -> CommandAdapterBundle:
    provider = (selection.provider if selection is not None else None) or "subprocess"
    if provider not in SUPPORTED_COMMAND_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_COMMAND_PROVIDERS))
        raise ValueError(
            f"Unsupported command adapter provider '{provider}'. "
            f"Supported providers: {supported}."
        )
    runner = SubprocessCommandRunner(process_factory=process_factory, environ=environ)
    if provider == "docker":
        if workspace is None:
            raise ValueError("Docker command adapter provider requires a workspace.")
        workspace_ctx = workspace if isinstance(workspace, WorkspaceContext) else WorkspaceContext.from_root(workspace)
        sandbox_runner = DockerCommandRunner(
            workspace=workspace_ctx,
            policy=sandbox_policy_from_selection(selection),
            host_runner=sandbox_host_runner or runner,
            environ=environ,
        )
        return CommandAdapterBundle(
            infrastructure_runner=runner,
            agent_runner=AgentSubprocessAdapter(sandbox_runner),
            agent_executor=CommandRunnerAgentExecutor(sandbox_runner),
            sandbox_metadata=sandbox_runner.metadata,
        )
    return CommandAdapterBundle(
        infrastructure_runner=runner,
        agent_runner=AgentSubprocessAdapter(runner),
        agent_executor=CommandRunnerAgentExecutor(runner),
    )
