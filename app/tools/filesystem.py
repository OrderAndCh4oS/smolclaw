import os
import fnmatch
import re

from app.tools.base import Tool, ToolCallPolicy
from app.tools.permissions import FILESYSTEM_READ, FILESYSTEM_WRITE
from app.workspace import WorkspaceContext


class _WorkspacePathMixin:
    def __init__(self, workspace: WorkspaceContext | str | None = None):
        if isinstance(workspace, WorkspaceContext):
            self.workspace = workspace
        elif workspace:
            self.workspace = WorkspaceContext.from_root(workspace)
        else:
            self.workspace = None

    def _resolve_path(self, path: str) -> tuple[str | None, str | None]:
        if self.workspace is None:
            expanded = os.path.expanduser(path)
            return os.path.realpath(expanded), None
        return self.workspace.resolve_contained_path(path, label="path")


class ReadFileTool(_WorkspacePathMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({FILESYSTEM_READ}))

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        }

    def __init__(self, workspace: WorkspaceContext | str | None = None, allowed_dir: str | None = None):
        super().__init__(workspace=workspace or allowed_dir)

    async def execute(self, **kwargs) -> str:
        path, err = self._resolve_path(kwargs["path"])
        if err:
            return err
        try:
            with open(path) as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except Exception as e:
            return f"Error: {e}"


class WriteFileTool(_WorkspacePathMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({"filesystem", "write", FILESYSTEM_WRITE}))

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file, creating parent directories if needed."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        }

    def __init__(self, workspace: WorkspaceContext | str | None = None, allowed_dir: str | None = None):
        super().__init__(workspace=workspace or allowed_dir)

    async def execute(self, **kwargs) -> str:
        path, err = self._resolve_path(kwargs["path"])
        content = kwargs["content"]
        if err:
            return err
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error: {e}"


class EditFileTool(_WorkspacePathMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({"filesystem", "write", FILESYSTEM_WRITE}))

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Replace old_text with new_text in a file."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit"},
                "old_text": {"type": "string", "description": "Text to find"},
                "new_text": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    def __init__(self, workspace: WorkspaceContext | str | None = None, allowed_dir: str | None = None):
        super().__init__(workspace=workspace or allowed_dir)

    async def execute(self, **kwargs) -> str:
        path, err = self._resolve_path(kwargs["path"])
        old_text = kwargs["old_text"]
        new_text = kwargs["new_text"]
        if err:
            return err
        try:
            with open(path) as f:
                content = f.read()
            if old_text not in content:
                return f"Error: old_text not found in {path}"
            content = content.replace(old_text, new_text, 1)
            with open(path, "w") as f:
                f.write(content)
            return f"Edited {path}"
        except Exception as e:
            return f"Error: {e}"


class ListDirTool(_WorkspacePathMixin, Tool):
    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List files and directories at the given path."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
            },
            "required": ["path"],
        }

    def __init__(self, workspace: WorkspaceContext | str | None = None, allowed_dir: str | None = None):
        super().__init__(workspace=workspace or allowed_dir)

    async def execute(self, **kwargs) -> str:
        path, err = self._resolve_path(kwargs["path"])
        if err:
            return err
        try:
            entries = sorted(os.listdir(path))
            return "\n".join(entries)
        except Exception as e:
            return f"Error: {e}"


class FindFilesTool(_WorkspacePathMixin, Tool):
    DEFAULT_EXCLUDED_DIRS = {
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".nltk_data",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }

    @property
    def name(self) -> str:
        return "find_files"

    @property
    def description(self) -> str:
        return "Find files in the workspace by glob pattern."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, for example '**/*.py' or 'package.json'",
                    "default": "**/*",
                },
                "path": {
                    "type": "string",
                    "description": "Workspace-relative directory to search",
                    "default": ".",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of paths to return",
                    "default": 200,
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
            "required": [],
        }

    def __init__(self, workspace: WorkspaceContext | str | None = None, allowed_dir: str | None = None):
        super().__init__(workspace=workspace or allowed_dir)

    async def execute(self, **kwargs) -> str:
        root, err = self._resolve_path(kwargs.get("path") or ".")
        if err:
            return err
        if not os.path.isdir(root):
            return f"Error: directory not found: {root}"

        pattern = kwargs.get("pattern") or "**/*"
        max_results = self._coerce_max_results(kwargs.get("max_results", 200))
        if isinstance(max_results, str):
            return max_results

        matches = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name for name in sorted(dirnames)
                if name not in self.DEFAULT_EXCLUDED_DIRS
            ]
            for filename in sorted(filenames):
                file_path = os.path.join(dirpath, filename)
                rel_path = self._display_path(file_path)
                rel_from_root = os.path.relpath(file_path, root)
                if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_from_root, pattern) or fnmatch.fnmatch(filename, pattern):
                    matches.append(rel_path)
                    if len(matches) >= max_results:
                        matches.append(f"... truncated at {max_results} matches")
                        return "\n".join(matches)

        if not matches:
            return "No files found."
        return "\n".join(matches)

    def _coerce_max_results(self, value) -> int | str:
        try:
            max_results = int(value)
        except (TypeError, ValueError):
            return "Error: max_results must be an integer"
        if max_results < 1:
            return "Error: max_results must be at least 1"
        return min(max_results, 1000)

    def _display_path(self, path: str) -> str:
        if self.workspace is None:
            return path
        try:
            return os.path.relpath(path, self.workspace.root_dir)
        except ValueError:
            return path


class ApplyPatchTool(_WorkspacePathMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({"filesystem", "write", FILESYSTEM_WRITE}))

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "Apply a structured patch to workspace files. Supports Add File, "
            "Update File, and Delete File sections."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "patch_text": {
                    "type": "string",
                    "description": "Patch text wrapped in *** Begin Patch and *** End Patch markers",
                },
            },
            "required": ["patch_text"],
        }

    def __init__(self, workspace: WorkspaceContext | str | None = None, allowed_dir: str | None = None):
        super().__init__(workspace=workspace or allowed_dir)

    async def execute(self, **kwargs) -> str:
        try:
            operations = self._parse_patch(kwargs["patch_text"])
            changed = []
            for operation in operations:
                kind = operation["kind"]
                path, err = self._resolve_path(operation["path"])
                if err:
                    return err
                if kind == "add":
                    self._add_file(path, operation["lines"])
                elif kind == "delete":
                    self._delete_file(path)
                elif kind == "update":
                    self._update_file(path, operation["hunks"])
                changed.append(f"{kind} {operation['path']}")
            return "Applied patch:\n" + "\n".join(changed)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {e}"

    def _parse_patch(self, patch_text: str) -> list[dict]:
        lines = patch_text.splitlines()
        if not lines or lines[0] != "*** Begin Patch":
            raise ValueError("patch must start with *** Begin Patch")
        if lines[-1] != "*** End Patch":
            raise ValueError("patch must end with *** End Patch")

        operations = []
        i = 1
        while i < len(lines) - 1:
            line = lines[i]
            if line.startswith("*** Add File: "):
                path = line.removeprefix("*** Add File: ").strip()
                i += 1
                content = []
                while i < len(lines) - 1 and not lines[i].startswith("*** "):
                    if not lines[i].startswith("+"):
                        raise ValueError(f"add file lines must start with '+': {path}")
                    content.append(lines[i][1:])
                    i += 1
                operations.append({"kind": "add", "path": path, "lines": content})
                continue
            if line.startswith("*** Delete File: "):
                path = line.removeprefix("*** Delete File: ").strip()
                operations.append({"kind": "delete", "path": path})
                i += 1
                continue
            if line.startswith("*** Update File: "):
                path = line.removeprefix("*** Update File: ").strip()
                i += 1
                hunks = []
                current = []
                while i < len(lines) - 1 and not lines[i].startswith("*** "):
                    if lines[i].startswith("@@"):
                        if current:
                            hunks.append(current)
                            current = []
                    elif lines[i].startswith((" ", "+", "-")):
                        current.append(lines[i])
                    else:
                        raise ValueError(f"invalid update line for {path}: {lines[i]}")
                    i += 1
                if current:
                    hunks.append(current)
                if not hunks:
                    raise ValueError(f"update file has no hunks: {path}")
                operations.append({"kind": "update", "path": path, "hunks": hunks})
                continue
            raise ValueError(f"unknown patch header: {line}")
        return operations

    def _add_file(self, path: str, lines: list[str]):
        if os.path.exists(path):
            raise ValueError(f"file already exists: {path}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("\n".join(lines))
            if lines:
                f.write("\n")

    def _delete_file(self, path: str):
        if not os.path.isfile(path):
            raise ValueError(f"file not found: {path}")
        os.remove(path)

    def _update_file(self, path: str, hunks: list[list[str]]):
        if not os.path.isfile(path):
            raise ValueError(f"file not found: {path}")
        with open(path) as f:
            content = f.read()
        original_lines = content.splitlines()
        had_trailing_newline = content.endswith("\n")
        updated = list(original_lines)
        search_start = 0

        for hunk in hunks:
            old_lines = [line[1:] for line in hunk if line.startswith((" ", "-"))]
            new_lines = [line[1:] for line in hunk if line.startswith((" ", "+"))]
            index = self._find_subsequence(updated, old_lines, search_start)
            if index is None:
                raise ValueError(f"hunk did not match file: {path}")
            updated[index:index + len(old_lines)] = new_lines
            search_start = index + len(new_lines)

        with open(path, "w") as f:
            f.write("\n".join(updated))
            if had_trailing_newline or updated:
                f.write("\n")

    def _find_subsequence(self, lines: list[str], target: list[str], start: int) -> int | None:
        if not target:
            return start
        end = len(lines) - len(target) + 1
        for index in range(start, max(start, end)):
            if lines[index:index + len(target)] == target:
                return index
        return None


class GrepSearchTool(_WorkspacePathMixin, Tool):
    DEFAULT_EXCLUDED_DIRS = {
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".nltk_data",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }

    @property
    def name(self) -> str:
        return "grep_search"

    @property
    def description(self) -> str:
        return (
            "Search text files under a workspace path with a grep-style regex. "
            "Results are limited and formatted as path:line:column: text."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Regex pattern to search for"},
                "path": {
                    "type": "string",
                    "description": "Workspace-relative file or directory to search",
                    "default": ".",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether the regex match is case-sensitive",
                    "default": False,
                },
                "include_glob": {
                    "type": "string",
                    "description": "Optional filename glob filter, for example '*.py'",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matches to return",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
            "required": ["query"],
        }

    def __init__(self, workspace: WorkspaceContext | str | None = None, allowed_dir: str | None = None):
        super().__init__(workspace=workspace or allowed_dir)

    async def execute(self, **kwargs) -> str:
        path, err = self._resolve_path(kwargs.get("path") or ".")
        if err:
            return err

        query = kwargs["query"]
        flags = 0 if kwargs.get("case_sensitive", False) else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error as e:
            return f"Error: invalid regex: {e}"

        include_glob = kwargs.get("include_glob")
        max_results = self._coerce_max_results(kwargs.get("max_results", 100))
        if isinstance(max_results, str):
            return max_results

        files = [path] if os.path.isfile(path) else self._iter_files(path, include_glob)
        matches: list[str] = []
        truncated = False

        for file_path in files:
            result = self._search_file(file_path, pattern, max_results - len(matches))
            matches.extend(result)
            if len(matches) >= max_results:
                truncated = True
                break

        if not matches:
            return "No matches found."
        if truncated:
            matches.append(f"... truncated at {max_results} matches")
        return "\n".join(matches)

    def _coerce_max_results(self, value) -> int | str:
        try:
            max_results = int(value)
        except (TypeError, ValueError):
            return "Error: max_results must be an integer"
        if max_results < 1:
            return "Error: max_results must be at least 1"
        return min(max_results, 1000)

    def _iter_files(self, root: str, include_glob: str | None):
        if not os.path.isdir(root):
            return []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name for name in dirnames
                if name not in self.DEFAULT_EXCLUDED_DIRS
            ]
            for filename in sorted(filenames):
                if include_glob and not fnmatch.fnmatch(filename, include_glob):
                    continue
                yield os.path.join(dirpath, filename)

    def _search_file(self, path: str, pattern: re.Pattern, remaining: int) -> list[str]:
        if remaining <= 0:
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            return []
        except OSError:
            return []

        results = []
        display_path = self._display_path(path)
        for line_number, line in enumerate(lines, start=1):
            for match in pattern.finditer(line):
                column = match.start() + 1
                text = line.rstrip("\n")
                results.append(f"{display_path}:{line_number}:{column}: {text}")
                if len(results) >= remaining:
                    return results
        return results

    def _display_path(self, path: str) -> str:
        if self.workspace is None:
            return path
        try:
            return os.path.relpath(path, self.workspace.root_dir)
        except ValueError:
            return path
