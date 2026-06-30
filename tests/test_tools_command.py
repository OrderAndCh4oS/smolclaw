import os
import subprocess

import pytest

from app.execution_grants import ExecutionGrant, SHELL_SESSION_EFFECT
from app.shell_sessions import DockerShellSessionService
from app.tools.command import (
    GitAddTool,
    GitAttachHeadToBranchTool,
    GitBranchTool,
    GitBranchCreateTool,
    GitBranchDeleteTool,
    GitCherryPickAbortTool,
    GitCherryPickContinueTool,
    GitCherryPickTool,
    GitCheckoutTool,
    GitCommitTool,
    GitDiffTool,
    GitFetchTool,
    GitLogTool,
    GitMergeAbortTool,
    GitMergeContinueTool,
    GitMergeTool,
    GitPullTool,
    GitPushTool,
    GitPushRefspecTool,
    GitRestorePathsTool,
    GitRestoreStagedTool,
    GitShowTool,
    GitStashApplyTool,
    GitStashListTool,
    GitStashPushTool,
    GitStatusTool,
    GitStatusRichTool,
    GitUpstreamTool,
    RunCommandTool,
    ShellSessionTool,
)
from app.tools.base import normalize_tool_result
from app.workspace import WorkspaceContext


def _git(repo: str, *args: str):
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _current_branch(repo: str) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


@pytest.fixture
def git_workspace(temp_dir):
    _git(temp_dir, "init")
    _git(temp_dir, "config", "user.email", "test@example.com")
    _git(temp_dir, "config", "user.name", "Test User")
    with open(os.path.join(temp_dir, "app.py"), "w") as f:
        f.write("print('hello')\n")
    _git(temp_dir, "add", "app.py")
    _git(temp_dir, "commit", "-m", "initial")
    return WorkspaceContext.from_root(temp_dir).ensure_dirs()


class TestGitTools:
    @pytest.mark.asyncio
    async def test_git_status(self, git_workspace):
        with open(os.path.join(git_workspace.root_dir, "app.py"), "a") as f:
            f.write("print('changed')\n")

        result = await GitStatusTool(git_workspace).execute()

        assert "exit code 0" in result
        assert "M app.py" in result

    @pytest.mark.asyncio
    async def test_git_diff(self, git_workspace):
        with open(os.path.join(git_workspace.root_dir, "app.py"), "a") as f:
            f.write("print('changed')\n")

        result = await GitDiffTool(git_workspace).execute()

        assert "exit code 0" in result
        assert "+print('changed')" in result

    @pytest.mark.asyncio
    async def test_git_branch_lists_branches(self, git_workspace):
        _git(git_workspace.root_dir, "checkout", "-b", "feature/test")

        result = await GitBranchTool(git_workspace).execute()

        assert "exit code 0" in result
        assert "feature/test" in result

    @pytest.mark.asyncio
    async def test_git_checkout_existing_branch(self, git_workspace):
        original_branch = _current_branch(git_workspace.root_dir)
        _git(git_workspace.root_dir, "checkout", "-b", "feature/test")
        _git(git_workspace.root_dir, "checkout", original_branch)

        result = await GitCheckoutTool(git_workspace).execute(branch="feature/test")

        assert "exit code 0" in result
        assert "Switched to branch 'feature/test'" in result

    @pytest.mark.asyncio
    async def test_git_checkout_can_create_branch(self, git_workspace):
        result = await GitCheckoutTool(git_workspace).execute(branch="feature/new", create=True)

        assert "exit code 0" in result
        assert "feature/new" in result

    @pytest.mark.asyncio
    async def test_git_add_and_commit(self, git_workspace):
        with open(os.path.join(git_workspace.root_dir, "app.py"), "a") as f:
            f.write("print('changed')\n")

        add_result = await GitAddTool(git_workspace).execute(paths=["app.py"])
        commit_result = await GitCommitTool(git_workspace).execute(message="update app")

        assert "exit code 0" in add_result
        assert "exit code 0" in commit_result
        assert "update app" in commit_result

    @pytest.mark.asyncio
    async def test_git_add_blocks_external_paths(self, git_workspace):
        result = await GitAddTool(git_workspace).execute(paths=["../outside.txt"])

        assert result.startswith("Error:")
        assert "outside workspace" in result

    @pytest.mark.asyncio
    async def test_git_add_requires_explicit_paths(self, git_workspace):
        result = await GitAddTool(git_workspace).execute(paths=[])

        assert result == "Error: provide at least one path"

    @pytest.mark.asyncio
    async def test_git_checkout_rejects_invalid_branch(self, git_workspace):
        result = await GitCheckoutTool(git_workspace).execute(branch="-bad")

        assert result == "Error: invalid branch: -bad"

    @pytest.mark.asyncio
    async def test_git_push_and_pull_with_local_remote(self, git_workspace, temp_dir):
        branch = _current_branch(git_workspace.root_dir)
        remote = os.path.join(temp_dir, "remote.git")
        clone = os.path.join(temp_dir, "clone")
        subprocess.run(["git", "init", "--bare", remote], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _git(git_workspace.root_dir, "remote", "add", "origin", remote)

        push_result = await GitPushTool(git_workspace).execute(remote="origin", branch=branch, set_upstream=True)

        subprocess.run(["git", "clone", remote, clone], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _git(clone, "config", "user.email", "test@example.com")
        _git(clone, "config", "user.name", "Test User")
        with open(os.path.join(clone, "app.py"), "a") as f:
            f.write("print('remote')\n")
        _git(clone, "add", "app.py")
        _git(clone, "commit", "-m", "remote update")
        _git(clone, "push", "origin", branch)

        pull_result = await GitPullTool(git_workspace).execute(remote="origin", branch=branch)

        assert "exit code 0" in push_result
        assert "exit code 0" in pull_result
        with open(os.path.join(git_workspace.root_dir, "app.py")) as f:
            assert "print('remote')" in f.read()

    @pytest.mark.asyncio
    async def test_git_status_rich_reports_detached_head(self, git_workspace):
        _git(git_workspace.root_dir, "checkout", "--detach")

        result = await GitStatusRichTool(git_workspace).execute()

        assert "exit code 0" in result
        assert "branch: <detached>" in result
        assert "operation: none" in result

    @pytest.mark.asyncio
    async def test_git_log_and_show_inspect_history(self, git_workspace):
        log_result = await GitLogTool(git_workspace).execute(max_count=1)
        show_result = await GitShowTool(git_workspace).execute(ref="HEAD", path="app.py")

        assert "exit code 0" in log_result
        assert "initial" in log_result
        assert "exit code 0" in show_result
        assert "app.py" in show_result

    @pytest.mark.asyncio
    async def test_git_fetch_updates_remote_refs(self, git_workspace, temp_dir):
        remote = os.path.join(temp_dir, "remote.git")
        subprocess.run(["git", "init", "--bare", remote], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _git(git_workspace.root_dir, "remote", "add", "origin", remote)

        result = await GitFetchTool(git_workspace).execute(remote="origin")

        assert "exit code 0" in result

    @pytest.mark.asyncio
    async def test_git_attach_head_to_branch_recovers_detached_commit(self, git_workspace):
        _git(git_workspace.root_dir, "checkout", "--detach")
        with open(os.path.join(git_workspace.root_dir, "app.py"), "a") as f:
            f.write("print('detached')\n")
        _git(git_workspace.root_dir, "add", "app.py")
        _git(git_workspace.root_dir, "commit", "-m", "detached work")

        result = await GitAttachHeadToBranchTool(git_workspace).execute(branch="recovered/work")

        assert "exit code 0" in result
        assert _current_branch(git_workspace.root_dir) == "recovered/work"
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=git_workspace.root_dir,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout
        assert "detached work" in log

    @pytest.mark.asyncio
    async def test_git_push_refspec_publishes_detached_head(self, git_workspace, temp_dir):
        remote = os.path.join(temp_dir, "remote.git")
        subprocess.run(["git", "init", "--bare", remote], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _git(git_workspace.root_dir, "remote", "add", "origin", remote)
        _git(git_workspace.root_dir, "checkout", "--detach")
        with open(os.path.join(git_workspace.root_dir, "app.py"), "a") as f:
            f.write("print('detached push')\n")
        _git(git_workspace.root_dir, "add", "app.py")
        _git(git_workspace.root_dir, "commit", "-m", "detached push")

        result = await GitPushRefspecTool(git_workspace).execute(target_branch="feature/detached")

        assert "exit code 0" in result
        listed = subprocess.run(
            ["git", "ls-remote", "--heads", remote, "feature/detached"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout
        assert "refs/heads/feature/detached" in listed

    @pytest.mark.asyncio
    async def test_git_push_refspec_rejects_raw_destination_refspec(self, git_workspace):
        result = await GitPushRefspecTool(git_workspace).execute(target_branch="HEAD:bad")

        assert result == "Error: invalid target_branch: HEAD:bad"

    @pytest.mark.asyncio
    async def test_git_branch_create_delete_and_upstream(self, git_workspace, temp_dir):
        base_branch = _current_branch(git_workspace.root_dir)
        remote = os.path.join(temp_dir, "remote.git")
        subprocess.run(["git", "init", "--bare", remote], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _git(git_workspace.root_dir, "remote", "add", "origin", remote)
        create_result = await GitBranchCreateTool(git_workspace).execute(branch="feature/new", checkout=True)
        push_result = await GitPushTool(git_workspace).execute(remote="origin", branch="feature/new", set_upstream=True)
        upstream_result = await GitUpstreamTool(git_workspace).execute()
        _git(git_workspace.root_dir, "checkout", base_branch)
        delete_result = await GitBranchDeleteTool(git_workspace).execute(branch="feature/new", force=True)

        assert "exit code 0" in create_result
        assert "exit code 0" in push_result
        assert "origin/feature/new" in upstream_result
        assert "exit code 0" in delete_result

    @pytest.mark.asyncio
    async def test_git_branch_delete_rejects_current_branch(self, git_workspace):
        branch = _current_branch(git_workspace.root_dir)

        result = await GitBranchDeleteTool(git_workspace).execute(branch=branch, force=True)

        assert result == f"Error: refusing to delete current branch: {branch}"

    @pytest.mark.asyncio
    async def test_git_merge_continue_rejects_without_merge(self, git_workspace):
        result = await GitMergeContinueTool(git_workspace).execute()

        assert result == "Error: no merge is in progress"

    @pytest.mark.asyncio
    async def test_git_merge_and_abort(self, git_workspace):
        base_branch = _current_branch(git_workspace.root_dir)
        _git(git_workspace.root_dir, "checkout", "-b", "feature/conflict")
        with open(os.path.join(git_workspace.root_dir, "app.py"), "w") as f:
            f.write("print('feature')\n")
        _git(git_workspace.root_dir, "add", "app.py")
        _git(git_workspace.root_dir, "commit", "-m", "feature change")
        _git(git_workspace.root_dir, "checkout", base_branch)
        with open(os.path.join(git_workspace.root_dir, "app.py"), "w") as f:
            f.write("print('master')\n")
        _git(git_workspace.root_dir, "add", "app.py")
        _git(git_workspace.root_dir, "commit", "-m", "master change")

        merge_result = await GitMergeTool(git_workspace).execute(ref="feature/conflict")
        abort_result = await GitMergeAbortTool(git_workspace).execute()

        assert "exit code 1" in merge_result
        assert "CONFLICT" in merge_result
        assert "exit code 0" in abort_result

    @pytest.mark.asyncio
    async def test_git_cherry_pick_continue_and_abort_reject_without_operation(self, git_workspace):
        continue_result = await GitCherryPickContinueTool(git_workspace).execute()
        abort_result = await GitCherryPickAbortTool(git_workspace).execute()

        assert continue_result == "Error: no cherry-pick is in progress"
        assert abort_result == "Error: no cherry-pick is in progress"

    @pytest.mark.asyncio
    async def test_git_cherry_pick_applies_commit(self, git_workspace):
        base_branch = _current_branch(git_workspace.root_dir)
        _git(git_workspace.root_dir, "checkout", "-b", "feature/pick")
        with open(os.path.join(git_workspace.root_dir, "app.py"), "a") as f:
            f.write("print('pick')\n")
        _git(git_workspace.root_dir, "add", "app.py")
        _git(git_workspace.root_dir, "commit", "-m", "pick change")
        pick_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=git_workspace.root_dir,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        _git(git_workspace.root_dir, "checkout", base_branch)

        result = await GitCherryPickTool(git_workspace).execute(ref=pick_sha)

        assert "exit code 0" in result
        with open(os.path.join(git_workspace.root_dir, "app.py")) as f:
            assert "print('pick')" in f.read()

    @pytest.mark.asyncio
    async def test_git_restore_staged_and_paths(self, git_workspace):
        with open(os.path.join(git_workspace.root_dir, "app.py"), "a") as f:
            f.write("print('changed')\n")
        _git(git_workspace.root_dir, "add", "app.py")

        unstage_result = await GitRestoreStagedTool(git_workspace).execute(paths=["app.py"])
        restore_result = await GitRestorePathsTool(git_workspace).execute(paths=["app.py"])

        assert "exit code 0" in unstage_result
        assert "exit code 0" in restore_result
        with open(os.path.join(git_workspace.root_dir, "app.py")) as f:
            assert "print('changed')" not in f.read()

    @pytest.mark.asyncio
    async def test_git_restore_paths_blocks_external_path(self, git_workspace):
        result = await GitRestorePathsTool(git_workspace).execute(paths=["../outside.txt"])

        assert result.startswith("Error:")
        assert "outside workspace" in result

    @pytest.mark.asyncio
    async def test_git_stash_push_list_and_apply(self, git_workspace):
        with open(os.path.join(git_workspace.root_dir, "app.py"), "a") as f:
            f.write("print('stash')\n")

        push_result = await GitStashPushTool(git_workspace).execute(message="save stash")
        list_result = await GitStashListTool(git_workspace).execute()
        apply_result = await GitStashApplyTool(git_workspace).execute()

        assert "exit code 0" in push_result
        assert "save stash" in list_result
        assert "exit code 0" in apply_result
        with open(os.path.join(git_workspace.root_dir, "app.py")) as f:
            assert "print('stash')" in f.read()

    @pytest.mark.asyncio
    async def test_git_stash_apply_rejects_invalid_ref(self, git_workspace):
        result = await GitStashApplyTool(git_workspace).execute(stash_ref="stash@{0}:bad")

        assert result == "Error: invalid stash_ref: stash@{0}:bad"


class TestRunCommandTool:
    @pytest.mark.asyncio
    async def test_allows_pytest_family(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        result = await tool.execute(command="python -m pytest --version")

        assert "exit code 0" in result
        assert "pytest" in result

    def test_timeout_output_bytes_are_formatted(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=args[0],
                timeout=1,
                output=b"stdout bytes\n",
                stderr=b"stderr bytes\n",
            )

        tool = RunCommandTool(workspace, command_runner=fake_run)

        result = tool._run(["npm", "test"], workspace.root_dir, timeout=1)

        assert result.startswith("timed out")
        assert "stdout bytes" in result
        assert "stderr bytes" in result

    @pytest.mark.asyncio
    async def test_blocks_denied_command(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        result = await tool.execute(command="rm file.txt")

        assert result.startswith("Denied:")
        assert "not allowlisted" in result
        assert normalize_tool_result(result).status == "denied"

    @pytest.mark.asyncio
    async def test_blocks_cwd_escape(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        result = await tool.execute(command="git status", cwd="/etc")

        assert result.startswith("Error:")
        assert "outside workspace" in result

    def test_redirect_command_policy_is_mutating(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        policy = tool.get_call_policy({"command": "echo hi > out.txt"})

        assert policy.mutates_state is True

    def test_package_build_script_policy_is_mutating(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        policy = tool.get_call_policy({"command": "npm run build"})

        assert policy.mutates_state is True

    def test_network_access_declares_network_effect(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        policy = tool.get_call_policy({"command": "python -m pytest", "network_access": True})

        assert "network" in policy.effects

    def test_image_management_declares_effect_when_provider_requires_it(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        fake_run.requires_image_management_approval = lambda: True
        tool = RunCommandTool(workspace, command_runner=fake_run)

        policy = tool.get_call_policy({"command": "python -m pytest"})

        assert "image_management" in policy.effects

    def test_network_access_declared_for_package_install_commands(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        policy = tool.get_call_policy({"command": "npm install left-pad"})

        assert "network" in policy.effects

    def test_network_access_not_declared_for_local_test_commands(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        policy = tool.get_call_policy({"command": "npm test"})

        assert "network" not in policy.effects

    @pytest.mark.asyncio
    async def test_network_access_is_forwarded_to_command_runner(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok\n", stderr="")

        tool = RunCommandTool(workspace, command_runner=fake_run)

        result = await tool.execute(command="python -m pytest", network_access=True)

        assert "exit code 0" in result
        assert calls[0][1]["network_access"] is True


class TestShellSessionTool:
    @pytest.mark.asyncio
    async def test_persists_session_cwd_from_container_path(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        os.makedirs(os.path.join(temp_dir, "pkg"))
        calls = []

        class FakeDockerRunner:
            class policy:
                container_workspace = "/workspace"

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="moved\n__SMOLCLAW_SHELL_CWD__=/workspace/pkg\n",
                stderr="",
            )

        fake_run.runner = FakeDockerRunner()
        shared_state = {}
        grant = ExecutionGrant(
            tool_name="shell_session",
            arguments_hash="hash",
            approval_id="apr-shell",
            effects=frozenset({SHELL_SESSION_EFFECT}),
        )
        shared_state["active_execution_grant"] = grant
        tool = ShellSessionTool(
            workspace,
            shared_state=shared_state,
            service_factory=lambda ws, state: DockerShellSessionService(
                workspace=ws,
                shared_state=state,
                command_runner=fake_run,
            ),
        )

        first = await tool.execute(command="cd pkg")
        second = await tool.execute(command="pwd")

        assert "moved" in first
        assert "__SMOLCLAW_SHELL_CWD__" not in first
        assert calls[1][1]["cwd"] == os.path.realpath(os.path.join(temp_dir, "pkg"))
        assert shared_state["shell_sessions"]["default"]["cwd"] == os.path.realpath(os.path.join(temp_dir, "pkg"))
        assert "exit code 0" in second

    @pytest.mark.asyncio
    async def test_forwards_network_access(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="__SMOLCLAW_SHELL_CWD__=/tmp\n",
                stderr="",
            )

        shared_state = {
            "active_execution_grant": ExecutionGrant(
                tool_name="shell_session",
                arguments_hash="hash",
                approval_id="apr-shell",
                effects=frozenset({SHELL_SESSION_EFFECT}),
            )
        }
        tool = ShellSessionTool(
            workspace,
            shared_state=shared_state,
            service_factory=lambda ws, state: DockerShellSessionService(
                workspace=ws,
                shared_state=state,
                command_runner=fake_run,
            ),
        )

        await tool.execute(command="curl https://example.com", network_access=True)

        assert calls[0][0][:2] == ["bash", "-lc"]
        assert calls[0][1]["network_access"] is True

    def test_network_access_declares_network_effect(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = ShellSessionTool(
            workspace,
            service_factory=lambda _ws, _state: _FakeShellService(),
        )

        policy = tool.get_call_policy({"command": "curl https://example.com", "network_access": True})

        assert "network" in policy.effects
        assert "shell_session" in policy.effects

    @pytest.mark.asyncio
    async def test_requires_shell_session_grant(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        tool = ShellSessionTool(
            workspace,
            service_factory=lambda ws, state: DockerShellSessionService(
                workspace=ws,
                shared_state=state,
                command_runner=fake_run,
            ),
        )

        result = await tool.execute(command="pwd")

        assert "Approval required" in result
        assert calls == []


class _FakeShellService:
    def requires_image_management_approval(self):
        return False
