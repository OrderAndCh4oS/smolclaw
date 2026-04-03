import os

import pytest

from app.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from app.workspace import WorkspaceContext


class TestReadFileTool:
    @pytest.mark.asyncio
    async def test_read_file(self, temp_dir):
        path = os.path.join(temp_dir, "test.txt")
        with open(path, "w") as f:
            f.write("hello world")
        tool = ReadFileTool()
        result = await tool.execute(path=path)
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        tool = ReadFileTool()
        result = await tool.execute(path="/nonexistent/file.txt")
        assert result.startswith("Error:")


class TestWriteFileTool:
    @pytest.mark.asyncio
    async def test_write_file(self, temp_dir):
        path = os.path.join(temp_dir, "out.txt")
        tool = WriteFileTool()
        result = await tool.execute(path=path, content="written")
        assert "Written" in result
        with open(path) as f:
            assert f.read() == "written"

    @pytest.mark.asyncio
    async def test_write_file_creates_dirs(self, temp_dir):
        path = os.path.join(temp_dir, "a", "b", "c.txt")
        tool = WriteFileTool()
        await tool.execute(path=path, content="deep")
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "deep"


class TestEditFileTool:
    @pytest.mark.asyncio
    async def test_edit_file(self, temp_dir):
        path = os.path.join(temp_dir, "edit.txt")
        with open(path, "w") as f:
            f.write("hello world")
        tool = EditFileTool()
        result = await tool.execute(path=path, old_text="world", new_text="there")
        assert "Edited" in result
        with open(path) as f:
            assert f.read() == "hello there"

    @pytest.mark.asyncio
    async def test_edit_file_old_text_not_found(self, temp_dir):
        path = os.path.join(temp_dir, "edit2.txt")
        with open(path, "w") as f:
            f.write("hello world")
        tool = EditFileTool()
        result = await tool.execute(path=path, old_text="missing", new_text="x")
        assert result.startswith("Error:")


class TestListDirTool:
    @pytest.mark.asyncio
    async def test_list_dir(self, temp_dir):
        for name in ["a.txt", "b.txt", "c.txt"]:
            with open(os.path.join(temp_dir, name), "w") as f:
                f.write("")
        tool = ListDirTool()
        result = await tool.execute(path=temp_dir)
        assert "a.txt" in result
        assert "b.txt" in result
        assert "c.txt" in result


class TestAllowedDir:
    @pytest.mark.asyncio
    async def test_allowed_dir_blocks_escape(self, temp_dir):
        tool = ReadFileTool(allowed_dir=temp_dir)
        result = await tool.execute(path="/etc/passwd")
        assert result.startswith("Error:")
        assert "outside workspace" in result


class TestWorkspaceRelativePaths:
    @pytest.mark.asyncio
    async def test_read_file_resolves_relative_to_workspace_root(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        nested_dir = os.path.join(temp_dir, "notes")
        os.makedirs(nested_dir, exist_ok=True)
        with open(os.path.join(nested_dir, "todo.md"), "w") as f:
            f.write("ship it")

        tool = ReadFileTool(workspace=workspace)
        result = await tool.execute(path="notes/todo.md")

        assert result == "ship it"

    @pytest.mark.asyncio
    async def test_list_dir_dot_resolves_to_workspace_root(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        os.makedirs(os.path.join(temp_dir, "notes"), exist_ok=True)

        tool = ListDirTool(workspace=workspace)
        result = await tool.execute(path=".")

        assert "notes" in result
