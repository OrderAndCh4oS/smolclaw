"""Git worktree isolation helpers for local agent runs."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field


STATE_EXCLUDES = (".smolclaw/**", "stores/**", "memory/**", "research/**")


@dataclass
class WorktreeContext:
    base_repo: str
    path: str
    run_id: str
    created_by_git_worktree: bool = True
    _cleaned: bool = field(default=False, init=False, repr=False)

    def diff(self, paths: list[str] | None = None) -> str:
        args = ["git", "-C", self.path, "diff", "--no-ext-diff", "--"]
        if paths:
            args.extend(paths)
        else:
            args.extend(["."])
            args.extend(f":(exclude){pattern}" for pattern in STATE_EXCLUDES)
        result = _run(args, timeout=20)
        return result.stdout if result.returncode == 0 else result.stdout + result.stderr

    def apply_back(self, paths: list[str] | None = None) -> str:
        diff_text = self.diff(paths=paths)
        if not diff_text.strip():
            return "No isolated changes to apply."
        result = subprocess.run(
            ["git", "-C", self.base_repo, "apply", "--index", "-"],
            input=diff_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            return f"Error: failed to apply isolated diff: {(result.stderr or result.stdout).strip()}"
        return "Applied isolated diff to base repository."

    def cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        if self.created_by_git_worktree:
            _run(["git", "-C", self.base_repo, "worktree", "remove", "--force", self.path], timeout=30)
        shutil.rmtree(self.path, ignore_errors=True)


class WorktreeRunner:
    def __init__(self, *, parent_dir: str | None = None):
        self.parent_dir = parent_dir

    def create(
        self,
        base_repo: str,
        run_id: str,
        *,
        copy_dirty: bool = False,
    ) -> WorktreeContext:
        base_repo = _repo_root(base_repo)
        if not copy_dirty:
            dirty = _git_status_porcelain(base_repo)
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
            _run(["git", "init"], cwd=path, timeout=20)
            _run(["git", "add", "."], cwd=path, timeout=20)
            _run([
                "git",
                "-c",
                "user.email=smolclaw@example.invalid",
                "-c",
                "user.name=SmolClaw",
                "commit",
                "-m",
                "smolclaw dirty copy baseline",
            ], cwd=path, timeout=20)
            return WorktreeContext(base_repo=base_repo, path=path, run_id=run_id, created_by_git_worktree=False)
        result = _run([
            "git",
            "-C",
            base_repo,
            "worktree",
            "add",
            "--detach",
            path,
            "HEAD",
        ], timeout=30)
        if result.returncode != 0:
            raise ValueError(f"Failed to create worktree: {(result.stderr or result.stdout).strip()}")
        return WorktreeContext(base_repo=base_repo, path=path, run_id=run_id)


def _repo_root(path: str) -> str:
    result = _run(["git", "-C", os.path.abspath(path), "rev-parse", "--show-toplevel"], timeout=10)
    if result.returncode != 0:
        raise ValueError(f"Not a git repository: {path}")
    return os.path.realpath(result.stdout.strip())


def _git_status_porcelain(repo: str) -> str:
    result = _run(["git", "-C", repo, "status", "--porcelain"], timeout=10)
    if result.returncode != 0:
        raise ValueError(f"Failed to inspect git status: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def _run(args: list[str], *, cwd: str | None = None, timeout: int):
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
