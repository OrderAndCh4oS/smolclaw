"""Agent-facing command execution abstractions."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.command_runner import CommandResult, CommandRunner
from app.execution_grants import ExecutionGrant


@dataclass(frozen=True)
class AgentCommandRequest:
    args: list[str]
    cwd: str | None = None
    input_text: str | None = None
    timeout: int = 600
    network_access: bool = False
    execution_grant: ExecutionGrant | None = None


class AgentCommandExecutor(Protocol):
    def run(self, request: AgentCommandRequest) -> CommandResult:
        ...

    def requires_image_management_approval(self) -> bool:
        ...


class CommandRunnerAgentExecutor:
    """Expose a CommandRunner through the agent command executor contract."""

    is_agent_command_executor = True

    def __init__(self, runner: CommandRunner):
        self.runner = runner

    def run(self, request: AgentCommandRequest) -> CommandResult:
        kwargs = {
            "cwd": request.cwd,
            "input_text": request.input_text,
            "timeout": request.timeout,
            "network_access": request.network_access,
        }
        if request.execution_grant is not None:
            kwargs["execution_grant"] = request.execution_grant
        return self.runner.run(request.args, **kwargs)

    @property
    def supports_docker_sandbox(self) -> bool:
        return bool(getattr(self.runner, "supports_docker_sandbox", False))

    @property
    def supports_shell_sessions(self) -> bool:
        return bool(getattr(self.runner, "supports_shell_sessions", False))

    def requires_image_management_approval(self) -> bool:
        checker = getattr(self.runner, "requires_image_management_approval", None)
        return bool(checker()) if callable(checker) else False


class SubprocessCallableAgentExecutor:
    """Adapt the legacy subprocess.run-shaped command seam."""

    is_agent_command_executor = True

    def __init__(self, command_runner: Callable[..., subprocess.CompletedProcess]):
        self.command_runner = command_runner

    def run(self, request: AgentCommandRequest) -> CommandResult:
        kwargs = {
            "cwd": request.cwd,
            "text": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "timeout": request.timeout,
            "check": False,
        }
        if request.network_access:
            kwargs["network_access"] = True
        if request.execution_grant is not None:
            kwargs["execution_grant"] = request.execution_grant
        result = self.command_runner(request.args, **kwargs)
        return CommandResult(
            args=list(request.args),
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

    @property
    def supports_docker_sandbox(self) -> bool:
        return bool(getattr(self.command_runner, "supports_docker_sandbox", False))

    @property
    def supports_shell_sessions(self) -> bool:
        return bool(getattr(self.command_runner, "supports_shell_sessions", False))

    @property
    def runner(self):
        return getattr(self.command_runner, "runner", None)

    def requires_image_management_approval(self) -> bool:
        checker = getattr(self.command_runner, "requires_image_management_approval", None)
        return bool(checker()) if callable(checker) else False


class AgentExecutorSubprocessAdapter:
    """Expose an AgentCommandExecutor through a subprocess.run-shaped callable."""

    def __init__(self, executor: AgentCommandExecutor):
        self.executor = executor

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
        result = self.executor.run(AgentCommandRequest(
            args=list(args),
            cwd=cwd,
            input_text=_coerce_input(input, text=text),
            timeout=int(timeout) if timeout is not None else 600,
            network_access=network_access,
            execution_grant=execution_grant,
        ))
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

    @property
    def supports_docker_sandbox(self) -> bool:
        return bool(getattr(self.executor, "supports_docker_sandbox", False))

    @property
    def supports_shell_sessions(self) -> bool:
        return bool(getattr(self.executor, "supports_shell_sessions", False))

    @property
    def runner(self):
        return getattr(self.executor, "runner", None)

    def requires_image_management_approval(self) -> bool:
        checker = getattr(self.executor, "requires_image_management_approval", None)
        return bool(checker()) if callable(checker) else False


def coerce_agent_command_executor(
    command_runner: Callable[..., subprocess.CompletedProcess] | CommandRunner | None = None,
    *,
    command_executor: AgentCommandExecutor | None = None,
) -> AgentCommandExecutor:
    if command_executor is not None:
        return command_executor
    if getattr(command_runner, "is_agent_command_executor", False):
        return command_runner  # type: ignore[return-value]
    if command_runner is None:
        return SubprocessCallableAgentExecutor(subprocess.run)
    if hasattr(command_runner, "run") and not callable(command_runner):
        return CommandRunnerAgentExecutor(command_runner)  # type: ignore[arg-type]
    if hasattr(command_runner, "run") and callable(getattr(command_runner, "run")) and not _looks_like_subprocess_callable(command_runner):
        return CommandRunnerAgentExecutor(command_runner)  # type: ignore[arg-type]
    return SubprocessCallableAgentExecutor(command_runner)  # type: ignore[arg-type]


def _looks_like_subprocess_callable(value) -> bool:
    return callable(value) and not isinstance(value, CommandRunnerAgentExecutor)


def _coerce_input(value, *, text: bool | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace") if text else value.decode(errors="replace")
    return str(value)
