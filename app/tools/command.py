import os
import shlex
import subprocess

from app.tools.base import Tool, ToolCallPolicy
from app.tools.permissions import COMMAND_EXECUTION, SHELL_READ, SHELL_WRITE
from app.workspace import WorkspaceContext


class _WorkspaceCommandMixin:
    def __init__(self, workspace: WorkspaceContext | str):
        if isinstance(workspace, WorkspaceContext):
            self.workspace = workspace
        else:
            self.workspace = WorkspaceContext.from_root(workspace)

    def _resolve_cwd(self, cwd: str | None = None) -> tuple[str | None, str | None]:
        return self.workspace.resolve_contained_path(cwd or ".", label="cwd")

    def _run(self, args: list[str], cwd: str, timeout: int = 30, max_output_chars: int = 20000) -> str:
        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return f"Error: command not found: {args[0]}"
        except subprocess.TimeoutExpired as e:
            output = (e.stdout or "") + (e.stderr or "")
            return self._format_output(124, output, max_output_chars, timed_out=True)
        return self._format_output(
            result.returncode,
            (result.stdout or "") + (result.stderr or ""),
            max_output_chars,
        )

    def _format_output(self, exit_code: int, output: str, max_output_chars: int, timed_out: bool = False) -> str:
        truncated = len(output) > max_output_chars
        if truncated:
            head_size = max_output_chars // 2
            tail_size = max_output_chars - head_size
            output = (
                output[:head_size]
                + f"\n... truncated to {max_output_chars} chars ...\n"
                + output[-tail_size:]
            )
        status = "timed out" if timed_out else f"exit code {exit_code}"
        body = output.rstrip() or "<no output>"
        return f"{status}\n{body}"


class GitStatusTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({SHELL_READ}))

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return "Show concise git status for the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "Workspace-relative directory",
                    "default": ".",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        return self._run(["git", "status", "--short", "--branch"], cwd, timeout=10)


class GitDiffTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({SHELL_READ}))

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return "Show git diff for the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "Workspace-relative directory",
                    "default": ".",
                },
                "staged": {
                    "type": "boolean",
                    "description": "Show staged diff instead of unstaged diff",
                    "default": False,
                },
                "path": {
                    "type": "string",
                    "description": "Optional workspace-relative path to diff",
                },
                "max_output_chars": {
                    "type": "integer",
                    "description": "Maximum output characters",
                    "default": 30000,
                    "minimum": 1000,
                    "maximum": 100000,
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        args = ["git", "diff"]
        if kwargs.get("staged", False):
            args.append("--staged")
        path = kwargs.get("path")
        if path:
            resolved, err = self.workspace.resolve_contained_path(path, label="path")
            if err:
                return err
            args.extend(["--", os.path.relpath(resolved, cwd)])
        return self._run(args, cwd, timeout=10, max_output_chars=self._coerce_output_limit(kwargs.get("max_output_chars", 30000)))

    def _coerce_output_limit(self, value) -> int:
        try:
            return min(max(int(value), 1000), 100000)
        except (TypeError, ValueError):
            return 30000


class RunCommandTool(_WorkspaceCommandMixin, Tool):
    DENIED_TOKENS = {
        "rm",
        "mv",
        "install",
        "add",
        "checkout",
        "clean",
        "reset",
        "restore",
        "switch",
    }

    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({COMMAND_EXECUTION}))

    def get_call_policy(self, arguments: dict | None = None) -> ToolCallPolicy:
        command = (arguments or {}).get("command") or ""
        tags = {COMMAND_EXECUTION}
        mutates = self._command_may_mutate(command)
        tags.add(SHELL_WRITE if mutates else SHELL_READ)
        return ToolCallPolicy(mutates_state=mutates, tags=frozenset(tags))

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return "Run an allowlisted project command in the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run"},
                "cwd": {
                    "type": "string",
                    "description": "Workspace-relative working directory",
                    "default": ".",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 120,
                    "minimum": 1,
                    "maximum": 600,
                },
                "max_output_chars": {
                    "type": "integer",
                    "description": "Maximum output characters",
                    "default": 20000,
                    "minimum": 1000,
                    "maximum": 100000,
                },
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        try:
            args = shlex.split(kwargs["command"])
        except ValueError as e:
            return f"Error: invalid command: {e}"
        if not args:
            return "Error: command is required"
        allowed, reason = self._is_allowed(args)
        if not allowed:
            return f"Error: command is not allowlisted: {reason}"
        timeout = self._coerce_int(kwargs.get("timeout_seconds", 120), minimum=1, maximum=600, default=120)
        max_output_chars = self._coerce_int(kwargs.get("max_output_chars", 20000), minimum=1000, maximum=100000, default=20000)
        return self._run(args, cwd, timeout=timeout, max_output_chars=max_output_chars)

    def _is_allowed(self, args: list[str]) -> tuple[bool, str]:
        if any(token in self.DENIED_TOKENS for token in args):
            return False, "contains a denied token"

        if args[0] == "git":
            return len(args) > 1 and args[1] in {"status", "diff", "log", "show", "branch"}, "git command must be read-only"
        if args[0] == "pytest":
            return True, ""
        if args[:3] == ["python", "-m", "pytest"]:
            return True, ""
        if args[0] in {"npm", "pnpm", "yarn", "bun"}:
            return self._package_command_allowed(args)
        if args[0] == "cargo":
            return len(args) > 1 and args[1] in {"test", "check"}, "cargo command must be test or check"
        if args[:2] == ["go", "test"]:
            return True, ""
        return False, f"unsupported command family: {args[0]}"

    def _command_may_mutate(self, command: str) -> bool:
        try:
            args = shlex.split(command)
        except ValueError:
            return True
        if not args:
            return False
        if any(marker in command for marker in (">", ">>", "2>", ">|")):
            return True
        if any(token in self.DENIED_TOKENS for token in args):
            return True
        if args[0] == "git":
            return not (len(args) > 1 and args[1] in {"status", "diff", "log", "show", "branch"})
        if args[0] in {"pytest", "cargo"}:
            return False
        if args[:3] == ["python", "-m", "pytest"]:
            return False
        if args[:2] == ["go", "test"]:
            return False
        if args[0] in {"npm", "pnpm", "yarn", "bun"}:
            return not self._package_command_is_read_only(args)
        return True

    def _package_command_allowed(self, args: list[str]) -> tuple[bool, str]:
        if len(args) >= 2 and args[1] == "test":
            return True, ""
        if len(args) >= 3 and args[1] == "run" and not args[2].startswith("-"):
            return True, ""
        return False, f"{args[0]} command must be test or run <script>"

    def _package_command_is_read_only(self, args: list[str]) -> bool:
        if len(args) >= 2 and args[1] == "test":
            return True
        return len(args) >= 3 and args[1] == "run" and args[2] in {"test", "check", "lint"}

    def _coerce_int(self, value, *, minimum: int, maximum: int, default: int) -> int:
        try:
            return min(max(int(value), minimum), maximum)
        except (TypeError, ValueError):
            return default
