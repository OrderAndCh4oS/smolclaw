import os
import re
import shlex
import subprocess

from app.tools.base import Tool, ToolCallPolicy, ToolRuntimeContext
from app.tools.permissions import COMMAND_EXECUTION, SHELL_READ, SHELL_WRITE
from app.workspace import WorkspaceContext


_GIT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _validate_git_ref(value: str, *, label: str) -> str | None:
    if not value:
        return f"Error: {label} is required"
    if (
        value.startswith("-")
        or value.endswith("/")
        or ".." in value
        or "@{" in value
        or "\\" in value
        or not _GIT_REF_RE.match(value)
    ):
        return f"Error: invalid {label}: {value}"
    return None


def _coerce_bool(value) -> bool:
    return bool(value)


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
            output = self._decode_process_output(e.stdout) + self._decode_process_output(e.stderr)
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

    @staticmethod
    def _decode_process_output(value) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)


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


class GitBranchTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({SHELL_READ}))

    @property
    def name(self) -> str:
        return "git_branch"

    @property
    def description(self) -> str:
        return "List local and remote Git branches for the workspace."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "all": {"type": "boolean", "description": "Include remote-tracking branches", "default": True},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        args = ["git", "branch"]
        if kwargs.get("all", True):
            args.append("--all")
        return self._run(args, cwd, timeout=10)


class GitAddTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_add"

    @property
    def description(self) -> str:
        return "Stage workspace files for commit."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Workspace-relative files or directories to stage",
                },
            },
            "required": ["paths"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        paths = list(kwargs.get("paths") or [])
        if not paths:
            return "Error: provide at least one path"
        args = ["git", "add", "--"]
        for path in paths:
            resolved, err = self.workspace.resolve_contained_path(path, label="path")
            if err:
                return err
            args.append(os.path.relpath(resolved, cwd))
        return self._run(args, cwd, timeout=30)


class GitCommitTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return "Create a Git commit from currently staged changes."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "message": {"type": "string", "description": "Commit message"},
            },
            "required": ["message"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        message = str(kwargs.get("message") or "").strip()
        if not message:
            return "Error: commit message is required"
        return self._run(["git", "commit", "-m", message], cwd, timeout=60, max_output_chars=40000)


class GitPushTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_push"

    @property
    def description(self) -> str:
        return "Push the current or specified branch to a Git remote."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                "branch": {"type": "string", "description": "Branch to push; omit to push current branch"},
                "set_upstream": {"type": "boolean", "description": "Set upstream for the branch", "default": False},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        remote = str(kwargs.get("remote") or "origin").strip()
        branch = str(kwargs.get("branch") or "").strip()
        for label, value in (("remote", remote), ("branch", branch)):
            if value:
                ref_err = _validate_git_ref(value, label=label)
                if ref_err:
                    return ref_err
        args = ["git", "push"]
        if _coerce_bool(kwargs.get("set_upstream")):
            args.append("--set-upstream")
        if branch:
            args.extend([remote, branch])
        elif remote != "origin":
            args.append(remote)
        return self._run(args, cwd, timeout=120, max_output_chars=40000)


class GitPullTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_pull"

    @property
    def description(self) -> str:
        return "Pull changes from a Git remote into the current branch."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                "branch": {"type": "string", "description": "Optional branch to pull"},
                "rebase": {"type": "boolean", "description": "Use git pull --rebase", "default": False},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        remote = str(kwargs.get("remote") or "origin").strip()
        branch = str(kwargs.get("branch") or "").strip()
        for label, value in (("remote", remote), ("branch", branch)):
            if value:
                ref_err = _validate_git_ref(value, label=label)
                if ref_err:
                    return ref_err
        args = ["git", "pull"]
        if _coerce_bool(kwargs.get("rebase")):
            args.append("--rebase")
        if branch:
            args.extend([remote, branch])
        elif remote != "origin":
            args.append(remote)
        return self._run(args, cwd, timeout=120, max_output_chars=40000)


class GitCheckoutTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_checkout"

    @property
    def description(self) -> str:
        return "Check out an existing Git branch, or create and check out a new branch."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "branch": {"type": "string", "description": "Branch name to check out"},
                "create": {"type": "boolean", "description": "Create the branch before checking it out", "default": False},
            },
            "required": ["branch"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        branch = str(kwargs.get("branch") or "").strip()
        ref_err = _validate_git_ref(branch, label="branch")
        if ref_err:
            return ref_err
        args = ["git", "checkout"]
        if _coerce_bool(kwargs.get("create")):
            args.append("-b")
        args.append(branch)
        return self._run(args, cwd, timeout=60, max_output_chars=40000)


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

    def __init__(self, workspace: WorkspaceContext | str, shared_state: dict | None = None):
        super().__init__(workspace)
        self.shared_state = shared_state if shared_state is not None else {}

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return RunCommandTool(runtime_ctx.workspace or self.workspace, shared_state=runtime_ctx.shared_state)

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
            if self._has_approved_bypass() and self._is_approval_bypassable(args):
                allowed = True
            else:
                return f"Denied: command is not allowlisted: {reason}"
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

    def _has_approved_bypass(self) -> bool:
        return bool(self.shared_state.get("allow_denied_command_once"))

    def _is_approval_bypassable(self, args: list[str]) -> bool:
        if args[0] in {"npm", "pnpm", "yarn", "bun"} and len(args) > 1:
            return args[1] in {"install", "i", "add", "view"}
        if args[:2] == ["node", "-e"]:
            return True
        return False

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
