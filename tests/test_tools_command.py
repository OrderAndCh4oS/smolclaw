import os
import subprocess

import pytest

from app.execution_grants import ExecutionGrant, SHELL_SESSION_EFFECT
from app.shell_sessions import DockerShellSessionService
from app.tools.command import (
    GitAddTool,
    GitBranchTool,
    GitCheckoutTool,
    GitCommitTool,
    GitDiffTool,
    GitPullTool,
    GitPushTool,
    GitStatusTool,
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
