import os

import pytest

from app.tools.factory import build_tool_registry
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

    @pytest.mark.asyncio
    async def test_exec_defaults_to_allowed_dir(self, temp_dir):
        tool = ExecTool(allowed_dir=temp_dir)
        result = await tool.execute(command="pwd")
        assert os.path.realpath(result) == os.path.realpath(temp_dir)

    @pytest.mark.asyncio
    async def test_exec_allows_relative_working_dir_within_allowed_dir(self, temp_dir):
        child_dir = os.path.join(temp_dir, "nested")
        os.makedirs(child_dir, exist_ok=True)
        tool = ExecTool(allowed_dir=temp_dir)
        result = await tool.execute(command="pwd", working_dir="nested")
        assert os.path.realpath(result) == os.path.realpath(child_dir)

    @pytest.mark.asyncio
    async def test_exec_blocks_working_dir_escape(self, temp_dir):
        tool = ExecTool(allowed_dir=temp_dir)
        result = await tool.execute(command="pwd", working_dir=os.path.dirname(temp_dir))
        assert result.startswith("Error:")
        assert "outside allowed directory" in result


class TestExecToolFactory:
    def test_build_tool_registry_scopes_exec_to_workspace(self, temp_dir):
        registry = build_tool_registry(
            smol_rag=None,
            memory_docs_dir=temp_dir,
            workspace=temp_dir,
            mode="direct",
        )

        exec_tool = registry._tools["exec"]
        assert isinstance(exec_tool, ExecTool)
        assert exec_tool.allowed_dir == os.path.realpath(temp_dir)
