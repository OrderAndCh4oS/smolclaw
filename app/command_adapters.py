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

from app.command_runner import CommandRunner, SubprocessCommandRunner
from app.runtime_config import AdapterSelection


SUPPORTED_COMMAND_PROVIDERS = frozenset({"subprocess"})


@dataclass(frozen=True)
class CommandAdapterBundle:
    infrastructure_runner: CommandRunner
    agent_runner: Callable[..., subprocess.CompletedProcess]


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
        **_kwargs,
    ) -> subprocess.CompletedProcess:
        input_text = self._coerce_input(input, text=text)
        result = self.runner.run(
            list(args),
            cwd=cwd,
            input_text=input_text,
            timeout=int(timeout) if timeout is not None else 600,
        )
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


def build_command_adapter_bundle(
    selection: AdapterSelection | None = None,
    *,
    process_factory: Callable[..., subprocess.Popen] | None = None,
    environ: Mapping[str, str] | None = None,
) -> CommandAdapterBundle:
    provider = (selection.provider if selection is not None else None) or "subprocess"
    if provider not in SUPPORTED_COMMAND_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_COMMAND_PROVIDERS))
        raise ValueError(
            f"Unsupported command adapter provider '{provider}'. "
            f"Supported providers: {supported}."
        )
    runner = SubprocessCommandRunner(process_factory=process_factory, environ=environ)
    return CommandAdapterBundle(
        infrastructure_runner=runner,
        agent_runner=AgentSubprocessAdapter(runner),
    )
