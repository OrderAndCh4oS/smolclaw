"""Harness-level safety gates for coding tools."""

import hashlib
import json
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


@dataclass(frozen=True)
class ExplorationEvidence:
    kind: str
    path: str | None = None
    query: str | None = None
    tool_call_id: str | None = None
    timestamp: float | None = None


@dataclass
class SafetyState:
    """Tracks what the agent has inspected for the active task."""

    workspace: Any = None
    task_key: str | None = None
    did_git_status: bool = False
    did_search: bool = False
    read_paths: set[str] = field(default_factory=set)
    evidence: list[ExplorationEvidence] = field(default_factory=list)
    max_identical_tool_calls: int = 3
    _last_tool_call_key: str | None = None
    _last_tool_call_count: int = 0

    def begin_task(self, task_key: str):
        if self.task_key == task_key:
            return
        self.task_key = task_key
        self.did_git_status = False
        self.did_search = False
        self.read_paths.clear()
        self.evidence.clear()
        self._last_tool_call_key = None
        self._last_tool_call_count = 0

    def record_tool_attempt(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        key = self._tool_call_key(tool_name, arguments)
        if key == self._last_tool_call_key:
            self._last_tool_call_count += 1
        else:
            self._last_tool_call_key = key
            self._last_tool_call_count = 1
        if self._last_tool_call_count > self.max_identical_tool_calls:
            return (
                f"Error: repeated identical tool call blocked after "
                f"{self.max_identical_tool_calls} attempts: {tool_name}."
            )
        return None

    def record_tool_result(self, tool_name: str, arguments: dict[str, Any], result: ToolOutcome):
        normalized = normalize_tool_result(result)
        if not normalized.ok:
            return
        if tool_name in STATUS_TOOLS or self._is_status_command(tool_name, arguments):
            self.did_git_status = True
            self.evidence.append(ExplorationEvidence(kind="status", path=self._evidence_path(tool_name, arguments)))
        if tool_name in SEARCH_TOOLS:
            self.did_search = True
            self.evidence.append(ExplorationEvidence(
                kind="diff" if tool_name == "git_diff" else "search",
                path=self._evidence_path(tool_name, arguments),
                query=str(arguments.get("query") or arguments.get("pattern") or ""),
            ))
        if tool_name in READ_TOOLS:
            path = self.normalize_path(arguments.get("path"))
            if path:
                self.read_paths.add(path)
                self.evidence.append(ExplorationEvidence(kind="read", path=path))

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

    def has_relevant_exploration(self, path: str | None) -> bool:
        target = self.normalize_path(path)
        if not target:
            return False
        parent = target if os.path.isdir(target) else os.path.dirname(target)
        for item in self.evidence:
            if not item.path:
                continue
            evidence_path = os.path.realpath(item.path)
            if item.kind == "read" and evidence_path == target:
                return True
            if item.kind in {"search", "diff"}:
                if self._path_contains(evidence_path, target) or self._path_contains(evidence_path, parent):
                    return True
        return False

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

    def _evidence_path(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        if tool_name in {"find_files", "grep_search", "list_dir"}:
            return self.normalize_path(arguments.get("path") or ".")
        if tool_name == "git_diff":
            return self.normalize_path(arguments.get("path") or arguments.get("cwd") or ".")
        if tool_name == "git_status" or self._is_status_command(tool_name, arguments):
            return self.normalize_path(arguments.get("cwd") or ".")
        return None

    def _path_contains(self, root: str, candidate: str) -> bool:
        root = os.path.realpath(root)
        candidate = os.path.realpath(candidate)
        return candidate == root or candidate.startswith(root + os.sep)

    def _tool_call_key(self, tool_name: str, arguments: dict[str, Any]) -> str:
        payload = json.dumps(
            {"tool": tool_name, "arguments": arguments},
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SafetyMiddleware:
    """Blocks coding mutations until the agent has explored the workspace."""

    def __init__(self, state: SafetyState):
        self.state = state

    async def __call__(self, tool: Tool, kwargs: dict[str, Any], next_fn: NextFn):
        repeat_error = self.state.record_tool_attempt(tool.name, kwargs)
        if repeat_error:
            return repeat_error

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
        targets = self._target_paths(tool_name, arguments)
        for path in targets:
            if not self.state.has_relevant_exploration(path):
                errors.append(f"inspect target path or parent directory first: {path}")
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

    def _target_paths(self, tool_name: str, arguments: dict[str, Any]) -> list[str]:
        if tool_name in {"write_file", "edit_file"}:
            path = arguments.get("path")
            return [path] if path else []
        if tool_name == "apply_patch":
            return [path for _, path in self._patch_targets(arguments.get("patch_text") or "")]
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
