import os

import pytest

from app.tools.filesystem import (
    ApplyPatchTool,
    EditFileTool,
    FindFilesTool,
    GrepSearchTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
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


class TestFindFilesTool:
    @pytest.mark.asyncio
    async def test_finds_files_by_glob(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        os.makedirs(os.path.join(temp_dir, "src"), exist_ok=True)
        with open(os.path.join(temp_dir, "src", "app.py"), "w") as f:
            f.write("")
        with open(os.path.join(temp_dir, "README.md"), "w") as f:
            f.write("")

        tool = FindFilesTool(workspace=workspace)
        result = await tool.execute(pattern="**/*.py")

        assert "src/app.py" in result
        assert "README.md" not in result

    @pytest.mark.asyncio
    async def test_blocks_escape_from_workspace(self, temp_dir):
        tool = FindFilesTool(allowed_dir=temp_dir)
        result = await tool.execute(path="/etc", pattern="*")

        assert result.startswith("Error:")
        assert "outside workspace" in result


class TestApplyPatchTool:
    @pytest.mark.asyncio
    async def test_add_update_delete_file(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        tool = ApplyPatchTool(workspace=workspace)

        add_result = await tool.execute(patch_text="\n".join([
            "*** Begin Patch",
            "*** Add File: src/app.py",
            "+print('hello')",
            "*** End Patch",
        ]))
        assert "add src/app.py" in add_result

        update_result = await tool.execute(patch_text="\n".join([
            "*** Begin Patch",
            "*** Update File: src/app.py",
            "@@",
            "-print('hello')",
            "+print('hi')",
            "*** End Patch",
        ]))
        assert "update src/app.py" in update_result
        with open(os.path.join(temp_dir, "src", "app.py")) as f:
            assert f.read() == "print('hi')\n"

        delete_result = await tool.execute(patch_text="\n".join([
            "*** Begin Patch",
            "*** Delete File: src/app.py",
            "*** End Patch",
        ]))
        assert "delete src/app.py" in delete_result
        assert not os.path.exists(os.path.join(temp_dir, "src", "app.py"))

    @pytest.mark.asyncio
    async def test_blocks_escape_from_workspace(self, temp_dir):
        tool = ApplyPatchTool(allowed_dir=temp_dir)
        result = await tool.execute(patch_text="\n".join([
            "*** Begin Patch",
            "*** Add File: ../outside.txt",
            "+nope",
            "*** End Patch",
        ]))

        assert result.startswith("Error:")
        assert "outside workspace" in result


class TestGrepSearchTool:
    @pytest.mark.asyncio
    async def test_searches_workspace_relative_path(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        notes_dir = os.path.join(temp_dir, "notes")
        os.makedirs(notes_dir, exist_ok=True)
        with open(os.path.join(notes_dir, "todo.md"), "w") as f:
            f.write("Ship the CLI\nAdd grep search\n")

        tool = GrepSearchTool(workspace=workspace)
        result = await tool.execute(query="grep", path="notes")

        assert "notes/todo.md:2:5: Add grep search" in result

    @pytest.mark.asyncio
    async def test_include_glob_filters_files(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        with open(os.path.join(temp_dir, "app.py"), "w") as f:
            f.write("needle\n")
        with open(os.path.join(temp_dir, "notes.md"), "w") as f:
            f.write("needle\n")

        tool = GrepSearchTool(workspace=workspace)
        result = await tool.execute(query="needle", include_glob="*.py")

        assert "app.py:1:1: needle" in result
        assert "notes.md" not in result

    @pytest.mark.asyncio
    async def test_blocks_escape_from_workspace(self, temp_dir):
        tool = GrepSearchTool(allowed_dir=temp_dir)
        result = await tool.execute(query="root", path="/etc")

        assert result.startswith("Error:")
        assert "outside workspace" in result


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
