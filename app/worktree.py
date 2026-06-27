"""Git worktree isolation helpers for local agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
import os
import shutil
import tempfile
from typing import Any

from app.command_runner import CommandRunner, SubprocessCommandRunner


STATE_EXCLUDES = (".smolclaw/**", "stores/**", "memory/**", "research/**")
DEFAULT_DIRTY_COPY_EXCLUDES = (
    ".git",
    ".smolclaw",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    ".turbo",
    "coverage",
    ".DS_Store",
    ".env*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
)
PRIVATE_KEY_PATTERNS = ("*.pem", "*.key", "id_rsa*", "id_ed25519*")


@dataclass(frozen=True)
class DirtyCopyPolicy:
    exclude_patterns: tuple[str, ...] = DEFAULT_DIRTY_COPY_EXCLUDES
    private_key_patterns: tuple[str, ...] = PRIVATE_KEY_PATTERNS
    warn_file_count: int = 25_000
    warn_total_bytes: int = 1_073_741_824
    warn_file_bytes: int = 52_428_800
    refuse_file_count: int = 100_000
    refuse_total_bytes: int = 5_368_709_120
    refuse_file_bytes: int = 262_144_000
    allow_private_key_paths: bool = False
    apply_confirm_files: int = 10
    apply_confirm_bytes: int = 204_800
    apply_confirm_lines: int = 1_000


@dataclass(frozen=True)
class DirtyCopyPreflight:
    copied_paths: tuple[str, ...] = ()
    copied_file_count: int = 0
    copied_byte_count: int = 0
    excluded_paths: tuple[str, ...] = ()
    excluded_roots: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorktreeIsolationMetadata:
    mode: str = "git-worktree"
    dirty_copy: bool = False
    copied_file_count: int = 0
    copied_byte_count: int = 0
    excluded_path_count: int = 0
    excluded_roots: tuple[str, ...] = ()
    warning_count: int = 0
    warnings: tuple[str, ...] = ()

    @classmethod
    def for_git_worktree(cls) -> "WorktreeIsolationMetadata":
        return cls(mode="git-worktree", dirty_copy=False)

    @classmethod
    def for_dirty_copy(cls, preflight: DirtyCopyPreflight) -> "WorktreeIsolationMetadata":
        return cls(
            mode="dirty-copy",
            dirty_copy=True,
            copied_file_count=preflight.copied_file_count,
            copied_byte_count=preflight.copied_byte_count,
            excluded_path_count=len(preflight.excluded_paths),
            excluded_roots=preflight.excluded_roots,
            warning_count=len(preflight.warnings),
            warnings=preflight.warnings,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dirty_copy": self.dirty_copy,
            "copied_file_count": self.copied_file_count,
            "copied_byte_count": self.copied_byte_count,
            "excluded_path_count": self.excluded_path_count,
            "excluded_roots": list(self.excluded_roots),
            "warning_count": self.warning_count,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class WorktreeDiffSummary:
    changed_files: tuple[str, ...] = ()
    added_count: int = 0
    modified_count: int = 0
    deleted_count: int = 0
    diff_bytes: int = 0
    line_changes: int = 0
    risky_paths: tuple[str, ...] = ()
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_files": list(self.changed_files),
            "added_count": self.added_count,
            "modified_count": self.modified_count,
            "deleted_count": self.deleted_count,
            "diff_bytes": self.diff_bytes,
            "line_changes": self.line_changes,
            "risky_paths": list(self.risky_paths),
            "requires_confirmation": self.requires_confirmation,
        }

    def format_review(self) -> str:
        lines = [
            "Review required before applying isolated diff.",
            f"Changed files: {len(self.changed_files)}",
            f"Added: {self.added_count}",
            f"Modified: {self.modified_count}",
            f"Deleted: {self.deleted_count}",
            f"Line changes: {self.line_changes}",
            f"Diff bytes: {self.diff_bytes}",
        ]
        if self.risky_paths:
            lines.append(f"Risky paths: {', '.join(self.risky_paths[:10])}")
        lines.append("Run /worktree apply --confirm to apply these isolated changes.")
        return "\n".join(lines)


@dataclass
class WorktreeContext:
    base_repo: str
    path: str
    run_id: str
    command_runner: CommandRunner = field(default_factory=SubprocessCommandRunner, repr=False)
    created_by_git_worktree: bool = True
    isolation_metadata: WorktreeIsolationMetadata = field(default_factory=WorktreeIsolationMetadata.for_git_worktree)
    dirty_copy_policy: DirtyCopyPolicy = field(default_factory=DirtyCopyPolicy, repr=False)
    _cleaned: bool = field(default=False, init=False, repr=False)

    def diff(self, paths: list[str] | None = None) -> str:
        _mark_untracked_intent_to_add(self.path, paths=paths, command_runner=self.command_runner)
        args = ["git", "-C", self.path, "diff", "--no-ext-diff", "--"]
        if paths:
            args.extend(paths)
        else:
            args.extend(["."])
            args.extend(f":(exclude){pattern}" for pattern in STATE_EXCLUDES)
        result = _run(args, command_runner=self.command_runner, timeout=20)
        return result.stdout if result.returncode == 0 else result.stdout + result.stderr

    def diff_summary(self, paths: list[str] | None = None) -> WorktreeDiffSummary:
        return _summarize_diff(
            self.diff(paths=paths),
            policy=self.dirty_copy_policy,
        )

    def apply_back(self, paths: list[str] | None = None, *, confirm: bool = False) -> str:
        diff_text = self.diff(paths=paths)
        if not diff_text.strip():
            return "No isolated changes to apply."
        summary = _summarize_diff(diff_text, policy=self.dirty_copy_policy)
        if summary.requires_confirmation and not confirm:
            return summary.format_review()
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
    def __init__(
        self,
        *,
        parent_dir: str | None = None,
        command_runner: CommandRunner | None = None,
        dirty_copy_policy: DirtyCopyPolicy | None = None,
    ):
        self.parent_dir = parent_dir
        self.command_runner = command_runner or SubprocessCommandRunner()
        self.dirty_copy_policy = dirty_copy_policy or DirtyCopyPolicy()

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
            preflight = analyze_dirty_copy(base_repo, policy=self.dirty_copy_policy)
            _copy_dirty_tree(base_repo, path, preflight)
            _require_success(
                _run(["git", "init"], command_runner=self.command_runner, cwd=path, timeout=20),
                "Failed to initialize dirty-copy repository",
            )
            _require_success(
                _run(["git", "add", "."], command_runner=self.command_runner, cwd=path, timeout=20),
                "Failed to stage dirty-copy baseline",
            )
            _require_success(
                _run([
                    "git",
                    "-c",
                    "user.email=smolclaw@example.invalid",
                    "-c",
                    "user.name=SmolClaw",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "smolclaw dirty copy baseline",
                ], command_runner=self.command_runner, cwd=path, timeout=20),
                "Failed to commit dirty-copy baseline",
            )
            return WorktreeContext(
                base_repo=base_repo,
                path=path,
                run_id=run_id,
                command_runner=self.command_runner,
                created_by_git_worktree=False,
                isolation_metadata=WorktreeIsolationMetadata.for_dirty_copy(preflight),
                dirty_copy_policy=self.dirty_copy_policy,
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
            isolation_metadata=WorktreeIsolationMetadata.for_git_worktree(),
            dirty_copy_policy=self.dirty_copy_policy,
        )


def analyze_dirty_copy(base_repo: str, *, policy: DirtyCopyPolicy | None = None) -> DirtyCopyPreflight:
    policy = policy or DirtyCopyPolicy()
    copied_paths: list[str] = []
    excluded_paths: list[str] = []
    excluded_roots: list[str] = []
    warnings: list[str] = []
    copied_bytes = 0
    largest_file = 0
    private_key_paths: list[str] = []

    for root, dirs, files in os.walk(base_repo):
        dirs.sort()
        files.sort()
        rel_root = _relative_path(base_repo, root)
        kept_dirs = []
        for directory in dirs:
            rel_dir = _join_rel(rel_root, directory)
            if _matches_any(rel_dir, policy.exclude_patterns):
                excluded_paths.append(rel_dir)
                _append_unique(excluded_roots, rel_dir)
            else:
                kept_dirs.append(directory)
        dirs[:] = kept_dirs
        for filename in files:
            rel_path = _join_rel(rel_root, filename)
            abs_path = os.path.join(root, filename)
            if _matches_any(rel_path, policy.private_key_patterns):
                private_key_paths.append(rel_path)
            if _matches_any(rel_path, policy.exclude_patterns):
                excluded_paths.append(rel_path)
                continue
            if os.path.islink(abs_path):
                excluded_paths.append(rel_path)
                warnings.append(f"Excluded symlink from dirty copy: {rel_path}")
                continue
            try:
                size = os.path.getsize(abs_path)
            except OSError:
                excluded_paths.append(rel_path)
                warnings.append(f"Excluded unreadable path from dirty copy: {rel_path}")
                continue
            largest_file = max(largest_file, size)
            copied_paths.append(rel_path)
            copied_bytes += size

    if private_key_paths and not policy.allow_private_key_paths:
        raise ValueError(
            "Dirty copy refused because private-key-like paths were found: "
            + ", ".join(private_key_paths[:10])
        )
    if len(copied_paths) > policy.refuse_file_count:
        raise ValueError(f"Dirty copy refused: {len(copied_paths)} files exceeds limit {policy.refuse_file_count}.")
    if copied_bytes > policy.refuse_total_bytes:
        raise ValueError(f"Dirty copy refused: {copied_bytes} bytes exceeds limit {policy.refuse_total_bytes}.")
    if largest_file > policy.refuse_file_bytes:
        raise ValueError(f"Dirty copy refused: largest file {largest_file} bytes exceeds limit {policy.refuse_file_bytes}.")

    if len(copied_paths) > policy.warn_file_count:
        warnings.append(f"Dirty copy includes {len(copied_paths)} files.")
    if copied_bytes > policy.warn_total_bytes:
        warnings.append(f"Dirty copy includes {copied_bytes} bytes.")
    if largest_file > policy.warn_file_bytes:
        warnings.append(f"Dirty copy includes a large file of {largest_file} bytes.")
    if excluded_paths:
        warnings.append(f"Dirty copy excluded {len(excluded_paths)} path(s).")

    return DirtyCopyPreflight(
        copied_paths=tuple(copied_paths),
        copied_file_count=len(copied_paths),
        copied_byte_count=copied_bytes,
        excluded_paths=tuple(excluded_paths),
        excluded_roots=tuple(excluded_roots),
        warnings=tuple(_unique_ordered(warnings)),
    )


def _copy_dirty_tree(base_repo: str, destination: str, preflight: DirtyCopyPreflight):
    os.makedirs(destination, exist_ok=True)
    for rel_path in preflight.copied_paths:
        source = os.path.join(base_repo, rel_path)
        target = os.path.join(destination, rel_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)


def _summarize_diff(diff_text: str, *, policy: DirtyCopyPolicy | None = None) -> WorktreeDiffSummary:
    policy = policy or DirtyCopyPolicy()
    changed_files: list[str] = []
    statuses: dict[str, str] = {}
    current_file: str | None = None
    line_changes = 0
    risky_paths: list[str] = []
    binary_touched = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                current_file = _diff_path(parts[3])
                changed_files.append(current_file)
                statuses[current_file] = "modified"
                if _matches_any(current_file, policy.exclude_patterns):
                    _append_unique(risky_paths, current_file)
            continue
        if current_file and line.startswith("new file mode"):
            statuses[current_file] = "added"
        elif current_file and line.startswith("deleted file mode"):
            statuses[current_file] = "deleted"
        elif line.startswith("Binary files "):
            binary_touched = True
        elif (line.startswith("+") and not line.startswith("+++")) or (
            line.startswith("-") and not line.startswith("---")
        ):
            line_changes += 1
    added = sum(1 for status in statuses.values() if status == "added")
    deleted = sum(1 for status in statuses.values() if status == "deleted")
    modified = len(statuses) - added - deleted
    requires_confirmation = (
        len(changed_files) > policy.apply_confirm_files
        or len(diff_text.encode("utf-8")) > policy.apply_confirm_bytes
        or line_changes > policy.apply_confirm_lines
        or deleted > 0
        or binary_touched
        or bool(risky_paths)
    )
    return WorktreeDiffSummary(
        changed_files=tuple(_unique_ordered(changed_files)),
        added_count=added,
        modified_count=modified,
        deleted_count=deleted,
        diff_bytes=len(diff_text.encode("utf-8")),
        line_changes=line_changes,
        risky_paths=tuple(risky_paths),
        requires_confirmation=requires_confirmation,
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


def _mark_untracked_intent_to_add(
    repo: str,
    *,
    paths: list[str] | None,
    command_runner: CommandRunner | None = None,
):
    args = ["git", "-C", repo, "ls-files", "--others", "--exclude-standard", "--"]
    if paths:
        args.extend(paths)
    else:
        args.extend(["."])
        args.extend(f":(exclude){pattern}" for pattern in STATE_EXCLUDES)
    result = _run(args, command_runner=command_runner, timeout=20)
    if result.returncode != 0:
        return
    untracked_paths = [line for line in result.stdout.splitlines() if line.strip()]
    if not untracked_paths:
        return
    for index in range(0, len(untracked_paths), 200):
        _run(
            ["git", "-C", repo, "add", "-N", "--", *untracked_paths[index:index + 200]],
            command_runner=command_runner,
            timeout=20,
        )


def _relative_path(base: str, path: str) -> str:
    rel_path = os.path.relpath(path, base)
    if rel_path == ".":
        return ""
    return rel_path.replace(os.sep, "/")


def _join_rel(root: str, name: str) -> str:
    return name if not root else f"{root}/{name}"


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    name = path.rsplit("/", 1)[-1]
    parts = path.split("/")
    for pattern in patterns:
        if pattern in parts or fnmatch(path, pattern) or fnmatch(name, pattern):
            return True
    return False


def _diff_path(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _append_unique(target: list[str], value: str):
    if value not in target:
        target.append(value)


def _unique_ordered(values) -> list[str]:
    unique: list[str] = []
    for value in values:
        _append_unique(unique, value)
    return unique


def _require_success(result, message: str):
    if result.returncode != 0:
        raise ValueError(f"{message}: {(result.stderr or result.stdout).strip()}")


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
