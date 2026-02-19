import os

import pytest

from app.tools.shell import ExecTool


class TestExecTool:
    @pytest.mark.asyncio
    async def test_exec_echo(self):
        tool = ExecTool()
        result = await tool.execute(command="echo hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_exec_returns_stderr(self):
        tool = ExecTool()
        result = await tool.execute(command="echo error >&2")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_exec_deny_rm_rf(self):
        tool = ExecTool()
        result = await tool.execute(command="rm -rf /")
        assert result.startswith("Error:")
        assert "blocked" in result

    @pytest.mark.asyncio
    async def test_exec_deny_fork_bomb(self):
        tool = ExecTool()
        result = await tool.execute(command=":(){ :|:& };:")
        assert result.startswith("Error:")
        assert "blocked" in result

    @pytest.mark.asyncio
    async def test_exec_timeout(self):
        tool = ExecTool(timeout=1.0)
        result = await tool.execute(command="sleep 10")
        assert result.startswith("Error:")
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_exec_output_truncation(self):
        tool = ExecTool()
        result = await tool.execute(command="python -c \"print('x' * 20000)\"")
        assert "truncated" in result

    @pytest.mark.asyncio
    async def test_exec_working_dir(self, temp_dir):
        tool = ExecTool()
        result = await tool.execute(command="pwd", working_dir=temp_dir)
        assert os.path.realpath(temp_dir) in os.path.realpath(result)
