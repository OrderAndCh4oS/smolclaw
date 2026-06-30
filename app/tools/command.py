import os
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import replace

from app.agent_command import AgentCommandExecutor, AgentCommandRequest, coerce_agent_command_executor
from app.command_policy import CommandPolicyClassifier, DENIED_COMMAND_TOKENS
from app.execution_grants import IMAGE_MANAGEMENT_EFFECT, NETWORK_EFFECT, SHELL_SESSION_EFFECT
from app.runtime_state import RuntimeSharedState
from app.shell_sessions import DockerShellSessionService, ShellSessionService
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
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _command_requires_network_access(command: str) -> bool:
    try:
        args = shlex.split(command)
    except ValueError:
        return False
    if len(args) < 2:
        return False
    if args[0] not in {"npm", "pnpm", "yarn", "bun"}:
        return False
    return args[1] in {"install", "i", "add", "view"}


class _WorkspaceCommandMixin:
    def __init__(
        self,
        workspace: WorkspaceContext | str,
        command_runner: Callable | None = None,
        command_executor: AgentCommandExecutor | None = None,
        shared_state: dict | None = None,
    ):
        if isinstance(workspace, WorkspaceContext):
            self.workspace = workspace
        else:
            self.workspace = WorkspaceContext.from_root(workspace)
        self.command_runner = command_runner or subprocess.run
        self.command_executor = coerce_agent_command_executor(
            self.command_runner,
            command_executor=command_executor,
        )
        self.shared_state = shared_state if shared_state is not None else {}
        self.runtime_state = RuntimeSharedState(self.shared_state)

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return self.__class__(
            runtime_ctx.workspace or self.workspace,
            command_runner=self.command_runner,
            command_executor=self.command_executor,
            shared_state=runtime_ctx.shared_state,
        )

    def get_call_policy(self, arguments: dict | None = None) -> ToolCallPolicy:
        return self._with_provider_effects(self.default_call_policy)

    def _resolve_cwd(self, cwd: str | None = None) -> tuple[str | None, str | None]:
        return self.workspace.resolve_contained_path(cwd or ".", label="cwd")

    def _run(
        self,
        args: list[str],
        cwd: str,
        timeout: int = 30,
        max_output_chars: int = 20000,
        network_access: bool = False,
    ) -> str:
        try:
            run_kwargs = {
                "cwd": cwd,
                "text": True,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "timeout": timeout,
                "check": False,
            }
            execution_grant = self.runtime_state.active_execution_grant
            grant_allows_network = bool(
                execution_grant is not None
                and execution_grant.allows(NETWORK_EFFECT)
            )
            if network_access or grant_allows_network:
                run_kwargs["network_access"] = True
            if execution_grant is not None:
                run_kwargs["execution_grant"] = execution_grant
            result = self.command_executor.run(AgentCommandRequest(
                args=list(args),
                cwd=run_kwargs["cwd"],
                timeout=run_kwargs["timeout"],
                network_access=bool(run_kwargs.get("network_access")),
                execution_grant=run_kwargs.get("execution_grant"),
            ))
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

    def _with_provider_effects(self, policy: ToolCallPolicy) -> ToolCallPolicy:
        effects = set(policy.effects)
        if self._requires_image_management_approval():
            effects.add(IMAGE_MANAGEMENT_EFFECT)
        return replace(policy, effects=frozenset(effects))

    def _requires_image_management_approval(self) -> bool:
        checker = getattr(self.command_executor, "requires_image_management_approval", None)
        return bool(checker()) if callable(checker) else False


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
    DENIED_TOKENS = set(DENIED_COMMAND_TOKENS)

    def __init__(
        self,
        workspace: WorkspaceContext | str,
        shared_state: dict | None = None,
        command_runner: Callable | None = None,
        command_executor: AgentCommandExecutor | None = None,
        command_classifier: CommandPolicyClassifier | None = None,
    ):
        super().__init__(
            workspace,
            command_runner=command_runner,
            command_executor=command_executor,
            shared_state=shared_state,
        )
        self.command_classifier = command_classifier or CommandPolicyClassifier()

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return RunCommandTool(
            runtime_ctx.workspace or self.workspace,
            shared_state=runtime_ctx.shared_state,
            command_runner=self.command_runner,
            command_executor=self.command_executor,
            command_classifier=self.command_classifier,
        )

    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(
            effects=frozenset({"command_read"}),
            tags=frozenset({COMMAND_EXECUTION}),
        )

    def get_call_policy(self, arguments: dict | None = None) -> ToolCallPolicy:
        command = (arguments or {}).get("command") or ""
        tags = {COMMAND_EXECUTION}
        mutates = self.command_classifier.may_mutate(command)
        tags.add(SHELL_WRITE if mutates else SHELL_READ)
        effects = {"command_write" if mutates else "command_read"}
        if (
            _coerce_bool((arguments or {}).get("network_access"))
            or _command_requires_network_access(command)
        ):
            effects.add(NETWORK_EFFECT)
        return self._with_provider_effects(ToolCallPolicy(
            effects=frozenset(effects),
            mutates_state=mutates,
            tags=frozenset(tags),
        ))

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
                "network_access": {
                    "type": "boolean",
                    "description": "Request approved Docker sandbox network access for this command",
                    "default": False,
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
        allowed, reason = self.command_classifier.is_allowed(args)
        if not allowed:
            if self._has_approved_bypass() and self.command_classifier.is_approval_bypassable(args):
                allowed = True
            else:
                return f"Denied: command is not allowlisted: {reason}"
        timeout = self._coerce_int(kwargs.get("timeout_seconds", 120), minimum=1, maximum=600, default=120)
        max_output_chars = self._coerce_int(kwargs.get("max_output_chars", 20000), minimum=1000, maximum=100000, default=20000)
        return self._run(
            args,
            cwd,
            timeout=timeout,
            max_output_chars=max_output_chars,
            network_access=_coerce_bool(kwargs.get("network_access")),
        )

    def _has_approved_bypass(self) -> bool:
        return self.runtime_state.allow_denied_command_once

    def _is_allowed(self, args: list[str]) -> tuple[bool, str]:
        return self.command_classifier.is_allowed(args)

    def _is_approval_bypassable(self, args: list[str]) -> bool:
        return self.command_classifier.is_approval_bypassable(args)

    def _command_may_mutate(self, command: str) -> bool:
        return self.command_classifier.may_mutate(command)

    def _package_command_allowed(self, args: list[str]) -> tuple[bool, str]:
        return self.command_classifier.package_command_allowed(args)

    def _package_command_is_read_only(self, args: list[str]) -> bool:
        return self.command_classifier.package_command_is_read_only(args)

    def _coerce_int(self, value, *, minimum: int, maximum: int, default: int) -> int:
        try:
            return min(max(int(value), minimum), maximum)
        except (TypeError, ValueError):
            return default


class ShellSessionTool(Tool):
    def __init__(
        self,
        workspace: WorkspaceContext | str,
        service_factory: Callable[[WorkspaceContext, dict], ShellSessionService],
        shared_state: dict | None = None,
    ):
        self.workspace = workspace if isinstance(workspace, WorkspaceContext) else WorkspaceContext.from_root(workspace)
        self.service_factory = service_factory
        self.shared_state = shared_state if shared_state is not None else {}
        self.runtime_state = RuntimeSharedState(self.shared_state)

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return ShellSessionTool(
            runtime_ctx.workspace or self.workspace,
            service_factory=self.service_factory,
            shared_state=runtime_ctx.shared_state,
        )

    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(
            effects=frozenset({"command_write", SHELL_SESSION_EFFECT}),
            mutates_state=True,
            tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}),
        )

    def get_call_policy(self, arguments: dict | None = None) -> ToolCallPolicy:
        command = str((arguments or {}).get("command") or "")
        effects = {"command_write", SHELL_SESSION_EFFECT}
        if (
            _coerce_bool((arguments or {}).get("network_access"))
            or _command_requires_network_access(command)
        ):
            effects.add(NETWORK_EFFECT)
        if self._requires_image_management_approval():
            effects.add(IMAGE_MANAGEMENT_EFFECT)
        return ToolCallPolicy(
            effects=frozenset(effects),
            mutates_state=True,
            tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}),
        )

    @property
    def name(self) -> str:
        return "shell_session"

    @property
    def description(self) -> str:
        return "Run shell code in a named Docker sandbox session."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Named shell session",
                    "default": "default",
                },
                "command": {"type": "string", "description": "Shell command or script to run"},
                "cwd": {
                    "type": "string",
                    "description": "Workspace-relative starting directory for new sessions",
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
                "network_access": {
                    "type": "boolean",
                    "description": "Request approved Docker sandbox network access for this command",
                    "default": False,
                },
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs) -> str:
        command = str(kwargs.get("command") or "")
        if not command.strip():
            return "Error: command is required"
        session_id = str(kwargs.get("session_id") or "default").strip() or "default"
        timeout = RunCommandTool._coerce_int(self, kwargs.get("timeout_seconds", 120), minimum=1, maximum=600, default=120)
        max_output_chars = RunCommandTool._coerce_int(self, kwargs.get("max_output_chars", 20000), minimum=1000, maximum=100000, default=20000)
        service = self.service_factory(self.workspace, self.shared_state)
        execution_grant = self.runtime_state.active_execution_grant
        network_access = _coerce_bool(kwargs.get("network_access"))
        if execution_grant is not None and execution_grant.allows(NETWORK_EFFECT):
            network_access = True
        result = service.execute(
            session_id=session_id,
            command=command,
            cwd=kwargs.get("cwd"),
            timeout=timeout,
            network_access=network_access,
            execution_grant=execution_grant,
        )
        return _WorkspaceCommandMixin._format_output(
            self,
            result.exit_code,
            result.output,
            max_output_chars,
            timed_out=result.timed_out,
        )

    def _requires_image_management_approval(self) -> bool:
        service = self.service_factory(self.workspace, self.shared_state)
        return service.requires_image_management_approval()
