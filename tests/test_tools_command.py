import os
import subprocess

import pytest

from app.tools.command import GitDiffTool, GitStatusTool, RunCommandTool
from app.workspace import WorkspaceContext


def _git(repo: str, *args: str):
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


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


class TestRunCommandTool:
    @pytest.mark.asyncio
    async def test_allows_pytest_family(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        result = await tool.execute(command="python -m pytest --version")

        assert "exit code 0" in result
        assert "pytest" in result

    def test_timeout_output_bytes_are_formatted(self, temp_dir, monkeypatch):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=args[0],
                timeout=1,
                output=b"stdout bytes\n",
                stderr=b"stderr bytes\n",
            )

        monkeypatch.setattr("app.tools.command.subprocess.run", fake_run)

        result = tool._run(["npm", "test"], workspace.root_dir, timeout=1)

        assert result.startswith("timed out")
        assert "stdout bytes" in result
        assert "stderr bytes" in result

    @pytest.mark.asyncio
    async def test_blocks_denied_command(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = RunCommandTool(workspace)

        result = await tool.execute(command="rm file.txt")

        assert result.startswith("Error:")
        assert "not allowlisted" in result

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
