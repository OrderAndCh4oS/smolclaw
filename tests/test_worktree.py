import os
import subprocess

import pytest

from app.worktree import WorktreeRunner


def _run(args, cwd):
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def _git_repo(temp_dir):
    repo = os.path.join(temp_dir, "repo")
    os.makedirs(repo, exist_ok=True)
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@example.invalid"], repo)
    _run(["git", "config", "user.name", "Test User"], repo)
    with open(os.path.join(repo, "app.py"), "w", encoding="utf-8") as handle:
        handle.write("print('base')\n")
    _run(["git", "add", "app.py"], repo)
    _run(["git", "commit", "-m", "initial"], repo)
    return repo


def test_worktree_creation_and_cleanup(temp_dir):
    repo = _git_repo(temp_dir)
    parent = os.path.join(temp_dir, "worktrees")

    ctx = WorktreeRunner(parent_dir=parent).create(repo, "run-1")

    assert os.path.exists(os.path.join(ctx.path, "app.py"))
    assert os.path.realpath(ctx.base_repo) == os.path.realpath(repo)
    ctx.cleanup()
    assert not os.path.exists(ctx.path)


def test_worktree_refuses_dirty_repo(temp_dir):
    repo = _git_repo(temp_dir)
    with open(os.path.join(repo, "app.py"), "a", encoding="utf-8") as handle:
        handle.write("print('dirty')\n")

    with pytest.raises(ValueError, match="dirty repository"):
        WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(repo, "run-1")


def test_worktree_edit_is_isolated_and_diff_excludes_state(temp_dir):
    repo = _git_repo(temp_dir)
    ctx = WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(repo, "run-1")

    with open(os.path.join(ctx.path, "app.py"), "w", encoding="utf-8") as handle:
        handle.write("print('isolated')\n")
    os.makedirs(os.path.join(ctx.path, ".smolclaw", "stores"), exist_ok=True)
    with open(os.path.join(ctx.path, ".smolclaw", "stores", "trace.json"), "w", encoding="utf-8") as handle:
        handle.write("{}")

    diff = ctx.diff()

    with open(os.path.join(repo, "app.py"), encoding="utf-8") as handle:
        assert handle.read() == "print('base')\n"
    assert "isolated" in diff
    assert ".smolclaw/stores/trace.json" not in diff
    ctx.cleanup()


def test_worktree_apply_back_applies_isolated_diff(temp_dir):
    repo = _git_repo(temp_dir)
    ctx = WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(repo, "run-1")
    with open(os.path.join(ctx.path, "app.py"), "w", encoding="utf-8") as handle:
        handle.write("print('isolated')\n")

    result = ctx.apply_back()

    assert result == "Applied isolated diff to base repository."
    with open(os.path.join(repo, "app.py"), encoding="utf-8") as handle:
        assert handle.read() == "print('isolated')\n"
    ctx.cleanup()
