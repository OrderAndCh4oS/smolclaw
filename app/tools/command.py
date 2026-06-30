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
_GIT_SHA_RE = re.compile(r"^[A-Fa-f0-9]{7,64}$")


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


def _validate_git_source_ref(value: str, *, label: str = "source_ref") -> str | None:
    if not value:
        return f"Error: {label} is required"
    if value == "HEAD" or _GIT_SHA_RE.match(value):
        return None
    return _validate_git_ref(value, label=label)


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

    def _resolve_paths(self, cwd: str, paths: list[str], *, label: str = "path") -> tuple[list[str], str | None]:
        if not paths:
            return [], "Error: provide at least one path"
        resolved_paths: list[str] = []
        for path in paths:
            resolved, err = self.workspace.resolve_contained_path(path, label=label)
            if err:
                return [], err
            resolved_paths.append(os.path.relpath(resolved, cwd))
        return resolved_paths, None

    @staticmethod
    def _coerce_output_limit(value, *, default: int = 30000) -> int:
        try:
            return min(max(int(value), 1000), 100000)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_max_count(value, *, default: int = 20, minimum: int = 1, maximum: int = 200) -> int:
        try:
            return min(max(int(value), minimum), maximum)
        except (TypeError, ValueError):
            return default

    def _run_raw(
        self,
        args: list[str],
        cwd: str,
        timeout: int = 30,
        *,
        network_access: bool = False,
    ):
        execution_grant = self.runtime_state.active_execution_grant
        grant_allows_network = bool(
            execution_grant is not None
            and execution_grant.allows(NETWORK_EFFECT)
        )
        return self.command_executor.run(AgentCommandRequest(
            args=list(args),
            cwd=cwd,
            timeout=timeout,
            network_access=bool(network_access or grant_allows_network),
            execution_grant=execution_grant,
        ))

    def _git_output(self, args: list[str], cwd: str, *, timeout: int = 30) -> str:
        result = self._run_raw(args, cwd, timeout=timeout)
        return ((result.stdout or "") + (result.stderr or "")).strip()

    def _git_success(self, args: list[str], cwd: str, *, timeout: int = 30) -> bool:
        return self._run_raw(args, cwd, timeout=timeout).returncode == 0

    def _git_path_exists(self, cwd: str, git_path: str) -> bool:
        result = self._run_raw(["git", "rev-parse", "--git-path", git_path], cwd, timeout=10)
        if result.returncode != 0:
            return False
        path = (result.stdout or "").strip()
        if not path:
            return False
        if not os.path.isabs(path):
            path = os.path.join(cwd, path)
        return os.path.exists(path)

    def _has_unmerged_paths(self, cwd: str) -> bool:
        result = self._run_raw(["git", "diff", "--name-only", "--diff-filter=U"], cwd, timeout=10)
        return bool((result.stdout or "").strip())

    def _run(
        self,
        args: list[str],
        cwd: str,
        timeout: int = 30,
        max_output_chars: int = 20000,
        network_access: bool = False,
    ) -> str:
        try:
            result = self._run_raw(args, cwd, timeout=timeout, network_access=network_access)
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


class GitStatusRichTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({SHELL_READ}))

    @property
    def name(self) -> str:
        return "git_status_rich"

    @property
    def description(self) -> str:
        return "Show detailed git state including detached HEAD and merge/cherry-pick state."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        branch = self._git_output(["git", "branch", "--show-current"], cwd, timeout=10)
        head = self._git_output(["git", "rev-parse", "--short", "HEAD"], cwd, timeout=10)
        upstream_result = self._run_raw(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd,
            timeout=10,
        )
        upstream = (upstream_result.stdout or "").strip() if upstream_result.returncode == 0 else "<none>"
        ahead_behind = ""
        if upstream != "<none>":
            ahead_behind = self._git_output(["git", "rev-list", "--left-right", "--count", f"{upstream}...HEAD"], cwd, timeout=10)
        status = self._git_output(["git", "status", "--short", "--branch"], cwd, timeout=10)
        unmerged = self._git_output(["git", "diff", "--name-only", "--diff-filter=U"], cwd, timeout=10)
        operations = []
        if self._git_path_exists(cwd, "MERGE_HEAD"):
            operations.append("merge")
        if self._git_path_exists(cwd, "CHERRY_PICK_HEAD"):
            operations.append("cherry-pick")
        if self._git_path_exists(cwd, "REBASE_HEAD") or self._git_path_exists(cwd, "rebase-merge") or self._git_path_exists(cwd, "rebase-apply"):
            operations.append("rebase")
        lines = [
            "exit code 0",
            f"branch: {branch or '<detached>'}",
            f"head: {head or '<unknown>'}",
            f"upstream: {upstream}",
        ]
        if ahead_behind:
            parts = ahead_behind.split()
            if len(parts) == 2:
                lines.append(f"ahead_behind: behind {parts[0]}, ahead {parts[1]}")
            else:
                lines.append(f"ahead_behind: {ahead_behind}")
        lines.append(f"operation: {', '.join(operations) if operations else 'none'}")
        lines.append("unmerged_files:")
        lines.append(unmerged or "<none>")
        lines.append("status:")
        lines.append(status or "<clean>")
        return "\n".join(lines)


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


class GitFetchTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, effects=frozenset({NETWORK_EFFECT}), tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_fetch"

    @property
    def description(self) -> str:
        return "Fetch refs from a Git remote."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                "ref": {"type": "string", "description": "Optional ref to fetch", "default": ""},
                "prune": {"type": "boolean", "description": "Prune deleted remote refs", "default": False},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        remote = str(kwargs.get("remote") or "origin").strip()
        ref = str(kwargs.get("ref") or "").strip()
        for label, value in (("remote", remote), ("ref", ref)):
            if value:
                ref_err = _validate_git_ref(value, label=label)
                if ref_err:
                    return ref_err
        args = ["git", "fetch"]
        if _coerce_bool(kwargs.get("prune")):
            args.append("--prune")
        args.append(remote)
        if ref:
            args.append(ref)
        return self._run(args, cwd, timeout=120, max_output_chars=40000, network_access=True)


class GitLogTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({SHELL_READ}))

    @property
    def name(self) -> str:
        return "git_log"

    @property
    def description(self) -> str:
        return "Show recent Git commits."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "ref": {"type": "string", "description": "Optional branch, commit, or ref", "default": ""},
                "max_count": {"type": "integer", "description": "Maximum commits", "default": 20, "minimum": 1, "maximum": 200},
                "path": {"type": "string", "description": "Optional workspace-relative path"},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        ref = str(kwargs.get("ref") or "").strip()
        if ref:
            ref_err = _validate_git_source_ref(ref, label="ref")
            if ref_err:
                return ref_err
        args = ["git", "log", "--oneline", "--decorate", f"--max-count={self._coerce_max_count(kwargs.get('max_count'))}"]
        if ref:
            args.append(ref)
        path = kwargs.get("path")
        if path:
            resolved, err = self.workspace.resolve_contained_path(path, label="path")
            if err:
                return err
            args.extend(["--", os.path.relpath(resolved, cwd)])
        return self._run(args, cwd, timeout=30, max_output_chars=40000)


class GitShowTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({SHELL_READ}))

    @property
    def name(self) -> str:
        return "git_show"

    @property
    def description(self) -> str:
        return "Show a Git commit or file at a ref."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "ref": {"type": "string", "description": "Commit, branch, tag, or ref"},
                "path": {"type": "string", "description": "Optional workspace-relative path"},
                "max_output_chars": {"type": "integer", "description": "Maximum output characters", "default": 40000, "minimum": 1000, "maximum": 100000},
            },
            "required": ["ref"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        ref = str(kwargs.get("ref") or "").strip()
        ref_err = _validate_git_source_ref(ref, label="ref")
        if ref_err:
            return ref_err
        args = ["git", "show", "--stat", "--patch", ref]
        path = kwargs.get("path")
        if path:
            resolved, err = self.workspace.resolve_contained_path(path, label="path")
            if err:
                return err
            args.extend(["--", os.path.relpath(resolved, cwd)])
        return self._run(args, cwd, timeout=30, max_output_chars=self._coerce_output_limit(kwargs.get("max_output_chars"), default=40000))


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


class GitPushRefspecTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_push_refspec"

    @property
    def description(self) -> str:
        return "Push a source ref such as HEAD to a named remote branch."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                "source_ref": {"type": "string", "description": "Source ref to push", "default": "HEAD"},
                "target_branch": {"type": "string", "description": "Remote branch name to update"},
                "force_with_lease": {"type": "boolean", "description": "Use --force-with-lease", "default": False},
            },
            "required": ["target_branch"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        remote = str(kwargs.get("remote") or "origin").strip()
        source_ref = str(kwargs.get("source_ref") or "HEAD").strip()
        target_branch = str(kwargs.get("target_branch") or "").strip()
        for label, value, validator in (
            ("remote", remote, _validate_git_ref),
            ("source_ref", source_ref, _validate_git_source_ref),
            ("target_branch", target_branch, _validate_git_ref),
        ):
            ref_err = validator(value, label=label)
            if ref_err:
                return ref_err
        args = ["git", "push"]
        if _coerce_bool(kwargs.get("force_with_lease")):
            args.append("--force-with-lease")
        args.extend([remote, f"{source_ref}:refs/heads/{target_branch}"])
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


class GitAttachHeadToBranchTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_attach_head_to_branch"

    @property
    def description(self) -> str:
        return "Move or create a local branch at HEAD and optionally check it out."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "branch": {"type": "string", "description": "Branch to point at HEAD"},
                "create": {"type": "boolean", "description": "Allow creating the branch", "default": True},
                "checkout": {"type": "boolean", "description": "Check out the branch after updating it", "default": True},
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
        if not _coerce_bool(kwargs.get("create", True)) and not self._git_success(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd, timeout=10):
            return f"Error: branch does not exist: {branch}"
        result = self._run_raw(["git", "branch", "-f", branch, "HEAD"], cwd, timeout=30)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            return self._format_output(result.returncode, output, 40000)
        if _coerce_bool(kwargs.get("checkout", True)):
            checkout = self._run_raw(["git", "checkout", branch], cwd, timeout=60)
            output += (checkout.stdout or "") + (checkout.stderr or "")
            return self._format_output(checkout.returncode, output, 40000)
        return self._format_output(0, output, 40000)


class GitBranchCreateTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_branch_create"

    @property
    def description(self) -> str:
        return "Create a local branch from an explicit start point."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "branch": {"type": "string", "description": "Branch name to create"},
                "start_point": {"type": "string", "description": "Start point ref", "default": "HEAD"},
                "checkout": {"type": "boolean", "description": "Check out the new branch", "default": False},
            },
            "required": ["branch"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        branch = str(kwargs.get("branch") or "").strip()
        start_point = str(kwargs.get("start_point") or "HEAD").strip()
        for label, value, validator in (
            ("branch", branch, _validate_git_ref),
            ("start_point", start_point, _validate_git_source_ref),
        ):
            ref_err = validator(value, label=label)
            if ref_err:
                return ref_err
        create = self._run_raw(["git", "branch", branch, start_point], cwd, timeout=30)
        output = (create.stdout or "") + (create.stderr or "")
        if create.returncode != 0 or not _coerce_bool(kwargs.get("checkout")):
            return self._format_output(create.returncode, output, 40000)
        checkout = self._run_raw(["git", "checkout", branch], cwd, timeout=60)
        output += (checkout.stdout or "") + (checkout.stderr or "")
        return self._format_output(checkout.returncode, output, 40000)


class GitBranchDeleteTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_branch_delete"

    @property
    def description(self) -> str:
        return "Delete a non-current local branch."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "branch": {"type": "string", "description": "Local branch to delete"},
                "force": {"type": "boolean", "description": "Use git branch -D", "default": False},
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
        current = self._git_output(["git", "branch", "--show-current"], cwd, timeout=10)
        if current == branch:
            return f"Error: refusing to delete current branch: {branch}"
        return self._run(["git", "branch", "-D" if _coerce_bool(kwargs.get("force")) else "-d", branch], cwd, timeout=30, max_output_chars=40000)


class GitUpstreamTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({SHELL_READ}))

    def get_call_policy(self, arguments: dict | None = None) -> ToolCallPolicy:
        if arguments and _coerce_bool(arguments.get("set")):
            return self._with_provider_effects(ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE})))
        return super().get_call_policy(arguments)

    @property
    def name(self) -> str:
        return "git_upstream"

    @property
    def description(self) -> str:
        return "Inspect or set upstream tracking for a branch."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "branch": {"type": "string", "description": "Optional local branch", "default": ""},
                "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                "remote_branch": {"type": "string", "description": "Remote branch for set=true", "default": ""},
                "set": {"type": "boolean", "description": "Set upstream instead of inspecting", "default": False},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        branch = str(kwargs.get("branch") or "").strip()
        if branch:
            ref_err = _validate_git_ref(branch, label="branch")
            if ref_err:
                return ref_err
        if not _coerce_bool(kwargs.get("set")):
            args = ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name"]
            args.append(f"{branch}@{{u}}" if branch else "@{u}")
            return self._run(args, cwd, timeout=10)
        remote = str(kwargs.get("remote") or "origin").strip()
        remote_branch = str(kwargs.get("remote_branch") or "").strip()
        for label, value in (("remote", remote), ("remote_branch", remote_branch)):
            ref_err = _validate_git_ref(value, label=label)
            if ref_err:
                return ref_err
        args = ["git", "branch", f"--set-upstream-to={remote}/{remote_branch}"]
        if branch:
            args.append(branch)
        return self._run(args, cwd, timeout=30, max_output_chars=40000)


class GitMergeTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_merge"

    @property
    def description(self) -> str:
        return "Merge a ref into the current branch."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "ref": {"type": "string", "description": "Ref to merge"},
                "no_ff": {"type": "boolean", "description": "Use --no-ff", "default": False},
            },
            "required": ["ref"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        ref = str(kwargs.get("ref") or "").strip()
        ref_err = _validate_git_source_ref(ref, label="ref")
        if ref_err:
            return ref_err
        args = ["git", "merge"]
        if _coerce_bool(kwargs.get("no_ff")):
            args.append("--no-ff")
        args.append(ref)
        return self._run(args, cwd, timeout=120, max_output_chars=40000)


class GitMergeContinueTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_merge_continue"

    @property
    def description(self) -> str:
        return "Commit a resolved in-progress merge."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "message": {"type": "string", "description": "Optional merge commit message", "default": ""},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        if not self._git_path_exists(cwd, "MERGE_HEAD"):
            return "Error: no merge is in progress"
        if self._has_unmerged_paths(cwd):
            return "Error: merge has unresolved files"
        message = str(kwargs.get("message") or "").strip()
        args = ["git", "commit", "-m", message] if message else ["git", "commit", "--no-edit"]
        return self._run(args, cwd, timeout=60, max_output_chars=40000)


class GitMergeAbortTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_merge_abort"

    @property
    def description(self) -> str:
        return "Abort an in-progress merge."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        if not self._git_path_exists(cwd, "MERGE_HEAD"):
            return "Error: no merge is in progress"
        return self._run(["git", "merge", "--abort"], cwd, timeout=60, max_output_chars=40000)


class GitCherryPickTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_cherry_pick"

    @property
    def description(self) -> str:
        return "Cherry-pick a commit onto the current branch."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "ref": {"type": "string", "description": "Commit to cherry-pick"},
            },
            "required": ["ref"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        ref = str(kwargs.get("ref") or "").strip()
        ref_err = _validate_git_source_ref(ref, label="ref")
        if ref_err:
            return ref_err
        return self._run(["git", "cherry-pick", ref], cwd, timeout=120, max_output_chars=40000)


class GitCherryPickContinueTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_cherry_pick_continue"

    @property
    def description(self) -> str:
        return "Continue a resolved in-progress cherry-pick."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        if not self._git_path_exists(cwd, "CHERRY_PICK_HEAD"):
            return "Error: no cherry-pick is in progress"
        if self._has_unmerged_paths(cwd):
            return "Error: cherry-pick has unresolved files"
        return self._run(["git", "cherry-pick", "--continue"], cwd, timeout=60, max_output_chars=40000)


class GitCherryPickAbortTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_cherry_pick_abort"

    @property
    def description(self) -> str:
        return "Abort an in-progress cherry-pick."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        if not self._git_path_exists(cwd, "CHERRY_PICK_HEAD"):
            return "Error: no cherry-pick is in progress"
        return self._run(["git", "cherry-pick", "--abort"], cwd, timeout=60, max_output_chars=40000)


class GitRestoreStagedTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_restore_staged"

    @property
    def description(self) -> str:
        return "Unstage selected paths."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Workspace-relative paths to unstage"},
            },
            "required": ["paths"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        paths, err = self._resolve_paths(cwd, list(kwargs.get("paths") or []))
        if err:
            return err
        return self._run(["git", "restore", "--staged", "--", *paths], cwd, timeout=30, max_output_chars=40000)


class GitRestorePathsTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_restore_paths"

    @property
    def description(self) -> str:
        return "Restore selected paths from a source ref."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Workspace-relative paths to restore"},
                "source": {"type": "string", "description": "Source ref", "default": "HEAD"},
            },
            "required": ["paths"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        source = str(kwargs.get("source") or "HEAD").strip()
        ref_err = _validate_git_source_ref(source, label="source")
        if ref_err:
            return ref_err
        paths, err = self._resolve_paths(cwd, list(kwargs.get("paths") or []))
        if err:
            return err
        return self._run(["git", "restore", f"--source={source}", "--", *paths], cwd, timeout=30, max_output_chars=40000)


class GitStashPushTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_stash_push"

    @property
    def description(self) -> str:
        return "Create a Git stash with a message."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "message": {"type": "string", "description": "Stash message"},
                "include_untracked": {"type": "boolean", "description": "Include untracked files", "default": False},
            },
            "required": ["message"],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        message = str(kwargs.get("message") or "").strip()
        if not message:
            return "Error: stash message is required"
        args = ["git", "stash", "push"]
        if _coerce_bool(kwargs.get("include_untracked")):
            args.append("-u")
        args.extend(["-m", message])
        return self._run(args, cwd, timeout=60, max_output_chars=40000)


class GitStashListTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(tags=frozenset({SHELL_READ}))

    @property
    def name(self) -> str:
        return "git_stash_list"

    @property
    def description(self) -> str:
        return "List Git stashes."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "max_count": {"type": "integer", "description": "Maximum stashes", "default": 20, "minimum": 1, "maximum": 200},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        return self._run(["git", "stash", "list", f"--max-count={self._coerce_max_count(kwargs.get('max_count'))}"], cwd, timeout=10)


class GitStashApplyTool(_WorkspaceCommandMixin, Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(mutates_state=True, tags=frozenset({COMMAND_EXECUTION, SHELL_WRITE}))

    @property
    def name(self) -> str:
        return "git_stash_apply"

    @property
    def description(self) -> str:
        return "Apply or pop a Git stash."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Workspace-relative directory", "default": "."},
                "stash_ref": {"type": "string", "description": "Stash ref", "default": "stash@{0}"},
                "pop": {"type": "boolean", "description": "Pop instead of apply", "default": False},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> str:
        cwd, err = self._resolve_cwd(kwargs.get("cwd"))
        if err:
            return err
        stash_ref = str(kwargs.get("stash_ref") or "stash@{0}").strip()
        if not re.match(r"^stash@\{[0-9]+\}$", stash_ref):
            return f"Error: invalid stash_ref: {stash_ref}"
        return self._run(["git", "stash", "pop" if _coerce_bool(kwargs.get("pop")) else "apply", stash_ref], cwd, timeout=60, max_output_chars=40000)


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
