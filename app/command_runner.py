"""Infrastructure command execution helpers.

This runner is for SmolClaw harness operations such as git, worktree, Jira,
and GitHub CLI calls. It is not the agent-facing ``run_command`` tool policy.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


class CommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        input_text: str | None = None,
        timeout: int = 600,
    ) -> CommandResult:
        ...


_ACTIVE_PROCESS_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen] = set()


def _register_process(process: subprocess.Popen):
    with _ACTIVE_PROCESS_LOCK:
        _ACTIVE_PROCESSES.add(process)


def _unregister_process(process: subprocess.Popen):
    with _ACTIVE_PROCESS_LOCK:
        _ACTIVE_PROCESSES.discard(process)


def terminate_active_processes():
    with _ACTIVE_PROCESS_LOCK:
        processes = list(_ACTIVE_PROCESSES)
    for process in processes:
        if process.poll() is not None:
            _unregister_process(process)
            continue
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.name == "posix" and getattr(process, "_smolclaw_own_process_group", False):
                os.killpg(process.pid, 15)
            else:
                process.terminate()
    _wait_then_kill(processes)


def _wait_then_kill(processes: list[subprocess.Popen], *, grace_seconds: float = 3.0):
    import time

    deadline = time.time() + grace_seconds
    for process in processes:
        remaining = max(0, deadline - time.time())
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=remaining)
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if os.name == "posix" and getattr(process, "_smolclaw_own_process_group", False):
                    os.killpg(process.pid, 9)
                else:
                    process.kill()
        _unregister_process(process)


class SubprocessCommandRunner:
    def __init__(
        self,
        *,
        process_factory: Callable[..., subprocess.Popen] | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.process_factory = process_factory or subprocess.Popen
        self.environ = environ if environ is not None else os.environ

    def run(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        input_text: str | None = None,
        timeout: int = 600,
    ) -> CommandResult:
        process: subprocess.Popen | None = None
        own_process_group = os.name == "posix" and not self.environ.get("SMOLCLAW_WORK_LOOP_JOB_ID")
        try:
            process = self.process_factory(
                args,
                cwd=cwd,
                stdin=subprocess.PIPE if input_text is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=own_process_group,
            )
            process._smolclaw_own_process_group = own_process_group
            _register_process(process)
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            return CommandResult(args=args, returncode=process.returncode, stdout=stdout, stderr=stderr)
        except FileNotFoundError as exc:
            return CommandResult(args=args, returncode=127, stderr=str(exc))
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                terminate_active_processes()
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return CommandResult(args=args, returncode=124, stdout=stdout, stderr=stderr or "Command timed out.")
        finally:
            if process is not None:
                _unregister_process(process)
