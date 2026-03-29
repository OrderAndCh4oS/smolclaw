import os

from app.tools.base import Tool, ToolCallPolicy


class ReadFileTool(Tool):
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

    def __init__(self, allowed_dir: str = None):
        self.allowed_dir = os.path.realpath(allowed_dir) if allowed_dir else None

    def _check_path(self, path: str) -> str | None:
        real = os.path.realpath(path)
        if self.allowed_dir and not real.startswith(self.allowed_dir + os.sep) and real != self.allowed_dir:
            return f"Error: path '{path}' is outside allowed directory"
        return None

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        err = self._check_path(path)
        if err:
            return err
        try:
            with open(path) as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except Exception as e:
            return f"Error: {e}"


class WriteFileTool(Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({"filesystem", "write"}))

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

    def __init__(self, allowed_dir: str = None):
        self.allowed_dir = os.path.realpath(allowed_dir) if allowed_dir else None

    def _check_path(self, path: str) -> str | None:
        real = os.path.realpath(path)
        if self.allowed_dir and not real.startswith(self.allowed_dir + os.sep) and real != self.allowed_dir:
            return f"Error: path '{path}' is outside allowed directory"
        return None

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        content = kwargs["content"]
        err = self._check_path(path)
        if err:
            return err
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error: {e}"


class EditFileTool(Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({"filesystem", "write"}))

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

    def __init__(self, allowed_dir: str = None):
        self.allowed_dir = os.path.realpath(allowed_dir) if allowed_dir else None

    def _check_path(self, path: str) -> str | None:
        real = os.path.realpath(path)
        if self.allowed_dir and not real.startswith(self.allowed_dir + os.sep) and real != self.allowed_dir:
            return f"Error: path '{path}' is outside allowed directory"
        return None

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        old_text = kwargs["old_text"]
        new_text = kwargs["new_text"]
        err = self._check_path(path)
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


class ListDirTool(Tool):
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

    def __init__(self, allowed_dir: str = None):
        self.allowed_dir = os.path.realpath(allowed_dir) if allowed_dir else None

    def _check_path(self, path: str) -> str | None:
        real = os.path.realpath(path)
        if self.allowed_dir and not real.startswith(self.allowed_dir + os.sep) and real != self.allowed_dir:
            return f"Error: path '{path}' is outside allowed directory"
        return None

    async def execute(self, **kwargs) -> str:
        path = kwargs["path"]
        err = self._check_path(path)
        if err:
            return err
        try:
            entries = sorted(os.listdir(path))
            return "\n".join(entries)
        except Exception as e:
            return f"Error: {e}"
