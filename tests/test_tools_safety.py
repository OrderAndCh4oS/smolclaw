import os

import pytest

from app.tools.base import Tool, ToolCallPolicy
from app.tools.middleware import MiddlewareChain
from app.tools.permissions import FILESYSTEM_READ, FILESYSTEM_WRITE, SHELL_WRITE
from app.tools.safety import SafetyMiddleware, SafetyState
from app.workspace import WorkspaceContext


class FakeTool(Tool):
    def __init__(self, name, policy=None):
        self._name = name
        self._policy = policy or ToolCallPolicy()

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def get_call_policy(self, arguments=None) -> ToolCallPolicy:
        return self._policy

    async def execute(self, **kwargs) -> str:
        return f"{self._name} ok"


def _chain(workspace):
    state = SafetyState(workspace=workspace)
    state.begin_task("task")
    return state, MiddlewareChain([SafetyMiddleware(state)])


class TestSafetyMiddleware:
    @pytest.mark.asyncio
    async def test_blocks_edit_before_exploration(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        path = os.path.join(temp_dir, "app.py")
        with open(path, "w") as f:
            f.write("print('hi')\n")
        _, chain = _chain(workspace)

        result = await chain.run(
            FakeTool("edit_file", ToolCallPolicy(mutates_state=True, tags=frozenset({FILESYSTEM_WRITE}))),
            {"path": "app.py", "old_text": "hi", "new_text": "bye"},
        )

        assert result.startswith("Error: safety gate blocked")
        assert "run git_status" in result
        assert "find_files or grep_search" in result
        assert "read target file first: app.py" in result

    @pytest.mark.asyncio
    async def test_allows_edit_after_status_search_and_target_read(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        with open(os.path.join(temp_dir, "app.py"), "w") as f:
            f.write("print('hi')\n")
        _, chain = _chain(workspace)

        await chain.run(FakeTool("git_status"), {})
        await chain.run(FakeTool("find_files"), {"path": ".", "pattern": "*.py"})
        await chain.run(
            FakeTool("read_file", ToolCallPolicy(tags=frozenset({FILESYSTEM_READ}))),
            {"path": "app.py"},
        )
        result = await chain.run(
            FakeTool("edit_file", ToolCallPolicy(mutates_state=True, tags=frozenset({FILESYSTEM_WRITE}))),
            {"path": "app.py", "old_text": "hi", "new_text": "bye"},
        )

        assert result == "edit_file ok"

    @pytest.mark.asyncio
    async def test_blocks_unread_target_even_after_other_file_read(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        for name in ("app.py", "other.py"):
            with open(os.path.join(temp_dir, name), "w") as f:
                f.write("print('hi')\n")
        _, chain = _chain(workspace)

        await chain.run(FakeTool("git_status"), {})
        await chain.run(FakeTool("grep_search"), {"path": ".", "query": "hi"})
        await chain.run(FakeTool("read_file"), {"path": "other.py"})
        result = await chain.run(
            FakeTool("edit_file", ToolCallPolicy(mutates_state=True, tags=frozenset({FILESYSTEM_WRITE}))),
            {"path": "app.py", "old_text": "hi", "new_text": "bye"},
        )

        assert result.startswith("Error: safety gate blocked")
        assert "read target file first: app.py" in result

    @pytest.mark.asyncio
    async def test_blocks_write_capable_shell_before_exploration(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        _, chain = _chain(workspace)

        result = await chain.run(
            FakeTool("run_command", ToolCallPolicy(mutates_state=True, tags=frozenset({SHELL_WRITE}))),
            {"command": "echo hi > out.txt"},
        )

        assert result.startswith("Error: safety gate blocked")
        assert "run git_status" in result

    def test_begin_task_resets_normal_turn_state(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        state = SafetyState(workspace=workspace)
        state.begin_task("turn-1")
        state.did_git_status = True
        state.did_search = True

        state.begin_task("turn-2")

        assert state.did_git_status is False
        assert state.did_search is False
