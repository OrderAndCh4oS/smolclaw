import asyncio
import os
import re

from app.tools.base import Tool, ToolCallPolicy
from app.tools.permissions import COMMAND_EXECUTION, SHELL_WRITE

BLOCKED_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+/"),
    re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;\s*:"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+if=/dev/zero"),
    re.compile(r">\s*/dev/sd[a-z]"),
]

MAX_OUTPUT = 10000


class ExecTool(Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({"shell", COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        if self.allowed_dir:
            return "Execute a shell command inside the current workspace and return its output."
        return "Execute a shell command and return its output."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "working_dir": {"type": "string", "description": "Working directory (optional)"},
            },
            "required": ["command"],
        }

    def __init__(self, timeout: float = 30.0, allowed_dir: str | None = None):
        self.timeout = timeout
        self.allowed_dir = os.path.realpath(allowed_dir) if allowed_dir else None

    def _resolve_working_dir(self, working_dir: str | None) -> tuple[str | None, str | None]:
        if not self.allowed_dir:
            return working_dir, None

        if working_dir:
            expanded = os.path.expanduser(working_dir)
            candidate = expanded if os.path.isabs(expanded) else os.path.join(self.allowed_dir, expanded)
        else:
            candidate = self.allowed_dir

        resolved = os.path.realpath(candidate)
        if resolved != self.allowed_dir and not resolved.startswith(self.allowed_dir + os.sep):
            return None, f"Error: working_dir '{working_dir}' is outside allowed directory"
        return resolved, None

    async def execute(self, **kwargs) -> str:
        command = kwargs["command"]
        working_dir = kwargs.get("working_dir")

        for pattern in BLOCKED_PATTERNS:
            if pattern.search(command):
                return f"Error: command blocked by safety filter"

        resolved_working_dir, path_error = self._resolve_working_dir(working_dir)
        if path_error:
            return path_error

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=resolved_working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "Error: command timed out"
        except Exception as e:
            return f"Error: {e}"

        output = stdout.decode(errors="replace")
        if stderr:
            err_text = stderr.decode(errors="replace")
            output = output + "\n" + err_text if output else err_text

        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + "\n... (truncated)"

        return output.strip()
