"""Harness-level safety gates for coding tools."""

import os
from dataclasses import dataclass, field
from typing import Any

from app.tools.base import Tool, ToolCallPolicy, ToolOutcome, normalize_tool_result
from app.tools.middleware import NextFn
from app.tools.permissions import FILESYSTEM_WRITE, SHELL_WRITE


READ_TOOLS = {"read_file"}
SEARCH_TOOLS = {"find_files", "grep_search", "list_dir", "git_diff"}
STATUS_TOOLS = {"git_status"}
FILESYSTEM_WRITE_TOOLS = {"write_file", "edit_file", "apply_patch"}


@dataclass
class SafetyState:
    """Tracks what the agent has inspected for the active task."""

    workspace: Any = None
    task_key: str | None = None
    did_git_status: bool = False
    did_search: bool = False
    read_paths: set[str] = field(default_factory=set)

    def begin_task(self, task_key: str):
        if self.task_key == task_key:
            return
        self.task_key = task_key
        self.did_git_status = False
        self.did_search = False
        self.read_paths.clear()

    def record_tool_result(self, tool_name: str, arguments: dict[str, Any], result: ToolOutcome):
        normalized = normalize_tool_result(result)
        if not normalized.ok:
            return
        if tool_name in STATUS_TOOLS or self._is_status_command(tool_name, arguments):
            self.did_git_status = True
        if tool_name in SEARCH_TOOLS:
            self.did_search = True
        if tool_name in READ_TOOLS:
            path = self.normalize_path(arguments.get("path"))
            if path:
                self.read_paths.add(path)

    def normalize_path(self, path: str | None) -> str | None:
        if not path:
            return None
        if self.workspace is not None:
            resolved, err = self.workspace.resolve_contained_path(path, label="path")
            if err:
                return None
            return os.path.realpath(resolved)
        return os.path.realpath(os.path.expanduser(path))

    def path_exists(self, path: str | None) -> bool:
        normalized = self.normalize_path(path)
        return bool(normalized and os.path.exists(normalized))

    def has_read_path(self, path: str | None) -> bool:
        normalized = self.normalize_path(path)
        return bool(normalized and normalized in self.read_paths)

    def exploration_errors(self) -> list[str]:
        errors = []
        if not self.did_git_status:
            errors.append("run git_status or run_command git status")
        if not self.did_search:
            errors.append("search the workspace with find_files or grep_search")
        return errors

    def _is_status_command(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        command = str(arguments.get("command") or "").strip()
        return tool_name == "run_command" and command in {"git status", "git status --short", "git status --porcelain"}


class SafetyMiddleware:
    """Blocks coding mutations until the agent has explored the workspace."""

    def __init__(self, state: SafetyState):
        self.state = state

    async def __call__(self, tool: Tool, kwargs: dict[str, Any], next_fn: NextFn):
        policy = tool.get_call_policy(kwargs)
        error = self._mutation_error(tool.name, kwargs, policy)
        if error:
            return error

        result = await next_fn(tool, kwargs)
        self.state.record_tool_result(tool.name, kwargs, result)
        return result

    def _mutation_error(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        policy: ToolCallPolicy,
    ) -> str | None:
        if not self._is_guarded_mutation(tool_name, policy):
            return None

        errors = self.state.exploration_errors()
        unread_paths = self._unread_existing_targets(tool_name, arguments)
        for path in unread_paths:
            errors.append(f"read target file first: {path}")

        if not errors:
            return None
        requirements = "; ".join(errors)
        return (
            "Error: safety gate blocked mutation before codebase exploration. "
            f"Before calling {tool_name}, {requirements}."
        )

    def _is_guarded_mutation(self, tool_name: str, policy: ToolCallPolicy) -> bool:
        return (
            tool_name in FILESYSTEM_WRITE_TOOLS
            or FILESYSTEM_WRITE in policy.tags
            or SHELL_WRITE in policy.tags
        )

    def _unread_existing_targets(self, tool_name: str, arguments: dict[str, Any]) -> list[str]:
        if tool_name == "edit_file":
            path = arguments.get("path")
            return [path] if path and not self.state.has_read_path(path) else []
        if tool_name == "write_file":
            path = arguments.get("path")
            if path and self.state.path_exists(path) and not self.state.has_read_path(path):
                return [path]
            return []
        if tool_name == "apply_patch":
            return [
                path
                for kind, path in self._patch_targets(arguments.get("patch_text") or "")
                if kind in {"update", "delete"} and not self.state.has_read_path(path)
            ]
        return []

    def _patch_targets(self, patch_text: str) -> list[tuple[str, str]]:
        targets = []
        for line in patch_text.splitlines():
            if line.startswith("*** Add File: "):
                targets.append(("add", line.removeprefix("*** Add File: ").strip()))
            elif line.startswith("*** Update File: "):
                targets.append(("update", line.removeprefix("*** Update File: ").strip()))
            elif line.startswith("*** Delete File: "):
                targets.append(("delete", line.removeprefix("*** Delete File: ").strip()))
        return targets
