import asyncio
import re

from app.tools.base import Tool

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
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
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

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def execute(self, **kwargs) -> str:
        command = kwargs["command"]
        working_dir = kwargs.get("working_dir")

        for pattern in BLOCKED_PATTERNS:
            if pattern.search(command):
                return f"Error: command blocked by safety filter"

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
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
