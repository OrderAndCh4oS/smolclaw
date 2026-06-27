"""Shell session service boundaries."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Protocol

from app.agent_command import AgentCommandExecutor, AgentCommandRequest, coerce_agent_command_executor
from app.execution_grants import ExecutionGrant, SHELL_SESSION_EFFECT
from app.workspace import WorkspaceContext


@dataclass(frozen=True)
class ShellSessionCommandResult:
    exit_code: int
    output: str
    timed_out: bool = False


class ShellSessionService(Protocol):
    def execute(
        self,
        *,
        session_id: str,
        command: str,
        cwd: str | None = None,
        timeout: int = 120,
        network_access: bool = False,
        execution_grant: ExecutionGrant | None = None,
    ) -> ShellSessionCommandResult:
        ...

    def requires_image_management_approval(self) -> bool:
        ...


class ShellSessionStore(Protocol):
    def get_cwd(self, session_id: str) -> str | None:
        ...

    def set_cwd(self, session_id: str, cwd: str) -> None:
        ...


class RuntimeShellSessionStore:
    """Runtime-state-backed shell session store."""

    _STATE_KEY = "shell_sessions"

    def __init__(self, shared_state: MutableMapping):
        self.shared_state = shared_state

    def get_cwd(self, session_id: str) -> str | None:
        sessions = self.shared_state.setdefault(self._STATE_KEY, {})
        saved = sessions.get(session_id) if isinstance(sessions, dict) else None
        return saved.get("cwd") if isinstance(saved, dict) else None

    def set_cwd(self, session_id: str, cwd: str) -> None:
        sessions = self.shared_state.setdefault(self._STATE_KEY, {})
        sessions[session_id] = {"cwd": cwd}


class DockerShellSessionService:
    """Docker-backed shell command session with explicit lifecycle state."""

    _CWD_SENTINEL = "__SMOLCLAW_SHELL_CWD__="

    def __init__(
        self,
        *,
        workspace: WorkspaceContext,
        shared_state: dict | None = None,
        command_runner: Callable | None = None,
        command_executor: AgentCommandExecutor | None = None,
        session_store: ShellSessionStore | None = None,
    ):
        self.workspace = workspace
        self.shared_state = shared_state if shared_state is not None else {}
        self.command_runner = command_runner
        self.command_executor = coerce_agent_command_executor(
            command_runner,
            command_executor=command_executor,
        )
        self.session_store = session_store or RuntimeShellSessionStore(self.shared_state)

    def execute(
        self,
        *,
        session_id: str,
        command: str,
        cwd: str | None = None,
        timeout: int = 120,
        network_access: bool = False,
        execution_grant: ExecutionGrant | None = None,
    ) -> ShellSessionCommandResult:
        if not _grant_allows(execution_grant, SHELL_SESSION_EFFECT):
            return ShellSessionCommandResult(
                exit_code=126,
                output="Error: Approval required for Docker shell session execution.",
            )
        start_cwd, err = self._session_cwd(session_id, cwd)
        if err:
            return ShellSessionCommandResult(exit_code=126, output=err)
        script = self._wrap_command(command)
        try:
            run_kwargs = {
                "cwd": start_cwd,
                "timeout": timeout,
                "execution_grant": execution_grant,
            }
            if network_access:
                run_kwargs["network_access"] = True
            result = self.command_executor.run(AgentCommandRequest(
                args=["bash", "-lc", script],
                cwd=run_kwargs["cwd"],
                timeout=run_kwargs["timeout"],
                network_access=bool(run_kwargs.get("network_access")),
                execution_grant=run_kwargs.get("execution_grant"),
            ))
        except FileNotFoundError:
            return ShellSessionCommandResult(exit_code=127, output="Error: command not found: bash")
        except subprocess.TimeoutExpired as exc:
            output = _decode_process_output(exc.stdout) + _decode_process_output(exc.stderr)
            return ShellSessionCommandResult(exit_code=124, output=output, timed_out=True)
        output = (result.stdout or "") + (result.stderr or "")
        clean_output, next_cwd = self._extract_next_cwd(output)
        if next_cwd:
            self._store_session_cwd(session_id, next_cwd)
        return ShellSessionCommandResult(exit_code=result.returncode, output=clean_output)

    def requires_image_management_approval(self) -> bool:
        checker = getattr(self.command_executor, "requires_image_management_approval", None)
        return bool(checker()) if callable(checker) else False

    def _session_cwd(self, session_id: str, requested_cwd: str | None) -> tuple[str | None, str | None]:
        saved = self.session_store.get_cwd(session_id)
        return self.workspace.resolve_contained_path(saved or requested_cwd or ".", label="cwd")

    def _store_session_cwd(self, session_id: str, cwd: str):
        cwd = self._host_cwd_from_runner(cwd)
        host_cwd, err = self.workspace.resolve_contained_path(cwd, label="cwd")
        if err:
            return
        self.session_store.set_cwd(session_id, host_cwd)

    def _host_cwd_from_runner(self, cwd: str) -> str:
        runner = getattr(self.command_executor, "runner", None)
        policy = getattr(runner, "policy", None)
        container_workspace = getattr(policy, "container_workspace", None)
        if not container_workspace:
            return cwd
        container_workspace = container_workspace.rstrip("/")
        if cwd == container_workspace:
            return self.workspace.root_dir
        prefix = container_workspace + "/"
        if cwd.startswith(prefix):
            return self.workspace.resolve_path(cwd[len(prefix):])
        return cwd

    def _wrap_command(self, command: str) -> str:
        return (
            "{ "
            + command
            + "\n}; __smolclaw_code=$?; "
            + f"printf '\\n{self._CWD_SENTINEL}%s\\n' \"$PWD\"; "
            + "exit $__smolclaw_code"
        )

    def _extract_next_cwd(self, output: str) -> tuple[str, str | None]:
        lines = output.splitlines()
        for index in range(len(lines) - 1, -1, -1):
            line = lines[index]
            if line.startswith(self._CWD_SENTINEL):
                cwd = line[len(self._CWD_SENTINEL):]
                clean = "\n".join(lines[:index] + lines[index + 1:])
                if output.endswith("\n") and clean:
                    clean += "\n"
                return clean, cwd
        return output, None


def _grant_allows(grant: ExecutionGrant | None, effect: str) -> bool:
    return bool(grant is not None and grant.allows(effect))


def _decode_process_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
