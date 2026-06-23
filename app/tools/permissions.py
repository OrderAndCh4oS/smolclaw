"""Permission modes for restricting tool access per agent."""

import os
from dataclasses import dataclass
from typing import Any, Dict, Final, Mapping, Set

from app.tools.base import Tool
from app.tools.middleware import NextFn

MUTATES_STATE: Final[str] = "mutates_state"
DELEGATES: Final[str] = "delegates"
COMMAND_EXECUTION: Final[str] = "command_execution"
FILESYSTEM_READ: Final[str] = "filesystem_read"
FILESYSTEM_WRITE: Final[str] = "filesystem_write"
SHELL_READ: Final[str] = "shell_read"
SHELL_WRITE: Final[str] = "shell_write"
EXTERNAL_PATH: Final[str] = "external_path"
DELETE: Final[str] = "delete"
SECRET_PATH: Final[str] = "secret_path"

SECRET_FILENAMES: Final[frozenset[str]] = frozenset({".env"})
SECRET_PREFIXES: Final[tuple[str, ...]] = (".env.",)
SECRET_FILENAME_EXCEPTIONS: Final[frozenset[str]] = frozenset({
    ".env.example",
    ".env.sample",
    ".env.template",
})

DIRECT_MUTATION_TOOLS: Final[Set[str]] = {
    "write_file",
    "edit_file",
    "apply_patch",
    "exec",
    "memory_store",
    "research_source_store",
    "memory_relate",
}

DELEGATION_TOOLS: Final[Set[str]] = {
    "sequential_pipeline",
    "fanout_pipeline",
    "route",
    "spawn_agent",
}

@dataclass(frozen=True)
class PermissionModeConfig:
    blocked_tools: frozenset[str]
    blocked_capabilities: frozenset[str]
    capability_exempt_tools: frozenset[str] = frozenset()


PERMISSION_MODES: Final[Dict[str, PermissionModeConfig]] = {
    "full": PermissionModeConfig(
        blocked_tools=frozenset(),
        blocked_capabilities=frozenset(),
    ),
    "plan": PermissionModeConfig(
        blocked_tools=frozenset(DIRECT_MUTATION_TOOLS | DELEGATION_TOOLS),
        blocked_capabilities=frozenset({MUTATES_STATE, DELEGATES, COMMAND_EXECUTION}),
        capability_exempt_tools=frozenset({"contradiction_review"}),
    ),
    "execute": PermissionModeConfig(
        blocked_tools=frozenset(DELEGATION_TOOLS),
        blocked_capabilities=frozenset({DELEGATES}),
    ),
    "research": PermissionModeConfig(
        blocked_tools=frozenset({
            "apply_patch",
            "write_file",
            "edit_file",
            "exec",
            "memory_relate",
            "sequential_pipeline",
            "fanout_pipeline",
            "route",
            "spawn_agent",
        }),
        blocked_capabilities=frozenset({MUTATES_STATE, DELEGATES, COMMAND_EXECUTION}),
        capability_exempt_tools=frozenset({"memory_store", "research_source_store", "contradiction_review"}),
    ),
    "delegate_only": PermissionModeConfig(
        blocked_tools=frozenset(DIRECT_MUTATION_TOOLS),
        blocked_capabilities=frozenset({MUTATES_STATE}),
    ),
}

PERMISSION_BLOCKED: Dict[str, Set[str]] = {
    name: set(config.blocked_tools) for name, config in PERMISSION_MODES.items()
}

PERMISSION_BLOCKED_CAPABILITIES: Dict[str, Set[str]] = {
    name: set(config.blocked_capabilities) for name, config in PERMISSION_MODES.items()
}
VALID_PERMISSION_MODES: Final[frozenset[str]] = frozenset(PERMISSION_MODES)


@dataclass(frozen=True)
class PermissionDecision:
    blocked_capabilities: frozenset[str]

    def denies(self, capability: str) -> bool:
        return capability in self.blocked_capabilities


def _policy_capabilities(tool: Tool, kwargs: Mapping[str, Any]) -> set[str]:
    policy = tool.get_call_policy(dict(kwargs))
    capabilities = set(policy.tags)
    if policy.mutates_state:
        capabilities.add(MUTATES_STATE)
    if policy.delegates:
        capabilities.add(DELEGATES)
    return capabilities


class PermissionMiddleware:
    """Middleware that blocks tool calls not permitted by the agent's permission mode."""

    def __init__(self, mode: str, *, workspace=None):
        if mode not in VALID_PERMISSION_MODES:
            supported = ", ".join(sorted(VALID_PERMISSION_MODES))
            raise ValueError(
                f"Unknown permission mode '{mode}'. Expected one of: {supported}."
            )
        self.mode = mode
        self.workspace = workspace
        self.config = PERMISSION_MODES[mode]
        self.decision = PermissionDecision(
            blocked_capabilities=self.config.blocked_capabilities,
        )
        self.blocked_tools = set(self.config.blocked_tools)

    async def __call__(self, tool: Tool, kwargs: Dict[str, Any], next_fn: NextFn):
        path_error = self._path_policy_error(tool.name, kwargs)
        if path_error:
            return path_error
        if tool.name in self.blocked_tools:
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode."
        capabilities = _policy_capabilities(tool, kwargs)
        if tool.name in self.config.capability_exempt_tools:
            capabilities -= self.decision.blocked_capabilities
        blocked = sorted(cap for cap in capabilities if self.decision.denies(cap))
        if blocked:
            caps = ", ".join(blocked)
            return f"Error: tool '{tool.name}' is not permitted in '{self.mode}' mode ({caps})."
        return await next_fn(tool, kwargs)

    def _path_policy_error(self, tool_name: str, kwargs: Mapping[str, Any]) -> str | None:
        for label, path in self._path_arguments(tool_name, kwargs):
            if not path:
                continue
            if self._is_secret_path(path):
                return f"Error: tool '{tool_name}' is not permitted to access secret path '{path}'."
            if self.workspace is not None:
                _, err = self.workspace.resolve_contained_path(path, label=label)
                if err:
                    return f"Error: tool '{tool_name}' is not permitted to access external path '{path}'."
        return None

    def _path_arguments(self, tool_name: str, kwargs: Mapping[str, Any]) -> list[tuple[str, str]]:
        if tool_name in {"read_file", "write_file", "edit_file", "list_dir"}:
            return [("path", str(kwargs.get("path") or ""))]
        if tool_name in {"find_files", "grep_search"}:
            return [("path", str(kwargs.get("path") or "."))]
        if tool_name == "git_status":
            return [("cwd", str(kwargs.get("cwd") or "."))]
        if tool_name in {"git_branch", "git_checkout", "git_pull", "git_push", "git_commit"}:
            return [("cwd", str(kwargs.get("cwd") or "."))]
        if tool_name == "git_add":
            paths = [("cwd", str(kwargs.get("cwd") or "."))]
            paths.extend(("path", str(path)) for path in (kwargs.get("paths") or []))
            return paths
        if tool_name == "git_diff":
            paths = [("cwd", str(kwargs.get("cwd") or "."))]
            if kwargs.get("path"):
                paths.append(("path", str(kwargs.get("path"))))
            return paths
        if tool_name == "run_command":
            return [("cwd", str(kwargs.get("cwd") or "."))]
        if tool_name == "apply_patch":
            return [("path", path) for path in self._patch_targets(str(kwargs.get("patch_text") or ""))]
        return []

    def _patch_targets(self, patch_text: str) -> list[str]:
        targets = []
        for line in patch_text.splitlines():
            if line.startswith("*** Add File: "):
                targets.append(line.removeprefix("*** Add File: ").strip())
            elif line.startswith("*** Update File: "):
                targets.append(line.removeprefix("*** Update File: ").strip())
            elif line.startswith("*** Delete File: "):
                targets.append(line.removeprefix("*** Delete File: ").strip())
        return targets

    def _is_secret_path(self, path: str) -> bool:
        parts = os.path.normpath(path).split(os.sep)
        for part in parts:
            if part in SECRET_FILENAME_EXCEPTIONS:
                continue
            if part in SECRET_FILENAMES or part.startswith(SECRET_PREFIXES):
                return True
        return False
