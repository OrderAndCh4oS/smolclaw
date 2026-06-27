import os
import subprocess

import pytest

from app.worktree import DirtyCopyPolicy, WorktreeRunner


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


def test_worktree_apply_back_applies_new_isolated_file(temp_dir):
    repo = _git_repo(temp_dir)
    ctx = WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(repo, "run-1")
    with open(os.path.join(ctx.path, "new.py"), "w", encoding="utf-8") as handle:
        handle.write("print('new')\n")

    result = ctx.apply_back()

    assert result == "Applied isolated diff to base repository."
    with open(os.path.join(repo, "new.py"), encoding="utf-8") as handle:
        assert handle.read() == "print('new')\n"
    ctx.cleanup()


def test_dirty_copy_excludes_state_cache_and_secret_paths(temp_dir):
    repo = _git_repo(temp_dir)
    os.makedirs(os.path.join(repo, ".smolclaw", "stores"), exist_ok=True)
    os.makedirs(os.path.join(repo, "node_modules", "pkg"), exist_ok=True)
    with open(os.path.join(repo, "app.py"), "a", encoding="utf-8") as handle:
        handle.write("print('dirty')\n")
    with open(os.path.join(repo, ".env.local"), "w", encoding="utf-8") as handle:
        handle.write("API_KEY=secret\n")
    with open(os.path.join(repo, ".smolclaw", "stores", "trace.json"), "w", encoding="utf-8") as handle:
        handle.write("{}\n")
    with open(os.path.join(repo, "node_modules", "pkg", "index.js"), "w", encoding="utf-8") as handle:
        handle.write("module.exports = {}\n")

    ctx = WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(
        repo,
        "run-1",
        copy_dirty=True,
    )

    assert ctx.created_by_git_worktree is False
    assert ctx.isolation_metadata.dirty_copy is True
    assert ctx.isolation_metadata.copied_file_count >= 1
    assert ctx.isolation_metadata.excluded_path_count >= 3
    assert ctx.isolation_metadata.warning_count >= 1
    assert os.path.exists(os.path.join(ctx.path, "app.py"))
    assert not os.path.exists(os.path.join(ctx.path, ".env.local"))
    assert not os.path.exists(os.path.join(ctx.path, ".smolclaw"))
    assert not os.path.exists(os.path.join(ctx.path, "node_modules"))
    ctx.cleanup()


def test_dirty_copy_refuses_private_key_paths(temp_dir):
    repo = _git_repo(temp_dir)
    with open(os.path.join(repo, "id_rsa"), "w", encoding="utf-8") as handle:
        handle.write("private key\n")

    with pytest.raises(ValueError, match="private-key-like"):
        WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(
            repo,
            "run-1",
            copy_dirty=True,
        )


def test_dirty_copy_refuses_private_key_paths_outside_excludes(temp_dir):
    repo = _git_repo(temp_dir)
    with open(os.path.join(repo, "deploy.secretkey"), "w", encoding="utf-8") as handle:
        handle.write("private key\n")
    policy = DirtyCopyPolicy(
        exclude_patterns=(".git",),
        private_key_patterns=("*.secretkey",),
    )

    with pytest.raises(ValueError, match="private-key-like"):
        WorktreeRunner(
            parent_dir=os.path.join(temp_dir, "worktrees"),
            dirty_copy_policy=policy,
        ).create(repo, "run-1", copy_dirty=True)


def test_dirty_copy_creates_baseline_commit_with_only_excluded_files(temp_dir):
    repo = os.path.join(temp_dir, "repo")
    os.makedirs(repo, exist_ok=True)
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@example.invalid"], repo)
    _run(["git", "config", "user.name", "Test User"], repo)
    _run(["git", "commit", "--allow-empty", "-m", "initial"], repo)
    with open(os.path.join(repo, ".env.local"), "w", encoding="utf-8") as handle:
        handle.write("API_KEY=secret\n")

    ctx = WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(
        repo,
        "run-1",
        copy_dirty=True,
    )

    _run(["git", "rev-parse", "--verify", "HEAD"], ctx.path)
    assert ctx.isolation_metadata.copied_file_count == 0
    assert not os.path.exists(os.path.join(ctx.path, ".env.local"))
    ctx.cleanup()


def test_dirty_copy_warns_but_allows_warn_thresholds(temp_dir):
    repo = _git_repo(temp_dir)
    policy = DirtyCopyPolicy(warn_file_count=0, warn_total_bytes=1, warn_file_bytes=1)

    ctx = WorktreeRunner(
        parent_dir=os.path.join(temp_dir, "worktrees"),
        dirty_copy_policy=policy,
    ).create(repo, "run-1", copy_dirty=True)

    assert ctx.isolation_metadata.warning_count >= 2
    assert any("files" in item for item in ctx.isolation_metadata.warnings)
    ctx.cleanup()


def test_apply_back_requires_confirmation_for_deletions(temp_dir):
    repo = _git_repo(temp_dir)
    ctx = WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(repo, "run-1")
    os.remove(os.path.join(ctx.path, "app.py"))

    review = ctx.apply_back()

    assert review.startswith("Review required")
    assert os.path.exists(os.path.join(repo, "app.py"))
    result = ctx.apply_back(confirm=True)
    assert result == "Applied isolated diff to base repository."
    assert not os.path.exists(os.path.join(repo, "app.py"))
    ctx.cleanup()


def test_diff_summary_reports_changed_file_counts(temp_dir):
    repo = _git_repo(temp_dir)
    ctx = WorktreeRunner(parent_dir=os.path.join(temp_dir, "worktrees")).create(repo, "run-1")
    with open(os.path.join(ctx.path, "new.py"), "w", encoding="utf-8") as handle:
        handle.write("print('new')\n")

    summary = ctx.diff_summary()

    assert summary.added_count == 1
    assert summary.modified_count == 0
    assert summary.deleted_count == 0
    assert summary.changed_files == ("new.py",)
    assert summary.requires_confirmation is False
    ctx.cleanup()
