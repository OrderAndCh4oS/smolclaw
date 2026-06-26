"""Git worktree isolation helpers for local agent runs."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

from app.command_runner import CommandRunner, SubprocessCommandRunner


STATE_EXCLUDES = (".smolclaw/**", "stores/**", "memory/**", "research/**")


@dataclass
class WorktreeContext:
    base_repo: str
    path: str
    run_id: str
    command_runner: CommandRunner = field(default_factory=SubprocessCommandRunner, repr=False)
    created_by_git_worktree: bool = True
    _cleaned: bool = field(default=False, init=False, repr=False)

    def diff(self, paths: list[str] | None = None) -> str:
        args = ["git", "-C", self.path, "diff", "--no-ext-diff", "--"]
        if paths:
            args.extend(paths)
        else:
            args.extend(["."])
            args.extend(f":(exclude){pattern}" for pattern in STATE_EXCLUDES)
        result = _run(args, command_runner=self.command_runner, timeout=20)
        return result.stdout if result.returncode == 0 else result.stdout + result.stderr

    def apply_back(self, paths: list[str] | None = None) -> str:
        diff_text = self.diff(paths=paths)
        if not diff_text.strip():
            return "No isolated changes to apply."
        result = _run(
            ["git", "-C", self.base_repo, "apply", "--index", "-"],
            command_runner=self.command_runner,
            input_text=diff_text,
            timeout=30,
        )
        if result.returncode != 0:
            return f"Error: failed to apply isolated diff: {(result.stderr or result.stdout).strip()}"
        return "Applied isolated diff to base repository."

    def cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        if self.created_by_git_worktree:
            _run(
                ["git", "-C", self.base_repo, "worktree", "remove", "--force", self.path],
                command_runner=self.command_runner,
                timeout=30,
            )
        shutil.rmtree(self.path, ignore_errors=True)


class WorktreeRunner:
    def __init__(self, *, parent_dir: str | None = None, command_runner: CommandRunner | None = None):
        self.parent_dir = parent_dir
        self.command_runner = command_runner or SubprocessCommandRunner()

    def create(
        self,
        base_repo: str,
        run_id: str,
        *,
        copy_dirty: bool = False,
    ) -> WorktreeContext:
        base_repo = _repo_root(base_repo, command_runner=self.command_runner)
        if not copy_dirty:
            dirty = _git_status_porcelain(base_repo, command_runner=self.command_runner)
            if dirty:
                raise ValueError(
                    "Cannot create isolated worktree from a dirty repository. "
                    "Commit/stash changes or use copy_dirty=True."
                )
        parent_dir = self.parent_dir or tempfile.mkdtemp(prefix="smolclaw-worktrees-")
        os.makedirs(parent_dir, exist_ok=True)
        path = os.path.join(parent_dir, run_id)
        if copy_dirty:
            shutil.copytree(base_repo, path, ignore=shutil.ignore_patterns(".git"))
            _run(["git", "init"], command_runner=self.command_runner, cwd=path, timeout=20)
            _run(["git", "add", "."], command_runner=self.command_runner, cwd=path, timeout=20)
            _run([
                "git",
                "-c",
                "user.email=smolclaw@example.invalid",
                "-c",
                "user.name=SmolClaw",
                "commit",
                "-m",
                "smolclaw dirty copy baseline",
            ], command_runner=self.command_runner, cwd=path, timeout=20)
            return WorktreeContext(
                base_repo=base_repo,
                path=path,
                run_id=run_id,
                command_runner=self.command_runner,
                created_by_git_worktree=False,
            )
        result = _run([
            "git",
            "-C",
            base_repo,
            "worktree",
            "add",
            "--detach",
            path,
            "HEAD",
        ], command_runner=self.command_runner, timeout=30)
        if result.returncode != 0:
            raise ValueError(f"Failed to create worktree: {(result.stderr or result.stdout).strip()}")
        return WorktreeContext(
            base_repo=base_repo,
            path=path,
            run_id=run_id,
            command_runner=self.command_runner,
        )


def _repo_root(path: str, *, command_runner: CommandRunner | None = None) -> str:
    result = _run(
        ["git", "-C", os.path.abspath(path), "rev-parse", "--show-toplevel"],
        command_runner=command_runner,
        timeout=10,
    )
    if result.returncode != 0:
        raise ValueError(f"Not a git repository: {path}")
    return os.path.realpath(result.stdout.strip())


def _git_status_porcelain(repo: str, *, command_runner: CommandRunner | None = None) -> str:
    result = _run(
        ["git", "-C", repo, "status", "--porcelain"],
        command_runner=command_runner,
        timeout=10,
    )
    if result.returncode != 0:
        raise ValueError(f"Failed to inspect git status: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def _run(
    args: list[str],
    *,
    command_runner: CommandRunner | None = None,
    cwd: str | None = None,
    input_text: str | None = None,
    timeout: int,
):
    runner = command_runner or SubprocessCommandRunner()
    return runner.run(
        args,
        cwd=cwd,
        input_text=input_text,
        timeout=timeout,
    )
