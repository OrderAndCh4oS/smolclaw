"""Checkpoint middleware for filesystem mutations."""

import os
from typing import Any

from app.checkpoints import CheckpointStore, FileSnapshot
from app.tools.base import Tool, ToolOutcome, normalize_tool_result
from app.tools.middleware import NextFn


FILESYSTEM_MUTATION_TOOLS = {"write_file", "edit_file", "apply_patch"}


class CheckpointMiddleware:
    def __init__(
        self,
        store: CheckpointStore,
        *,
        workspace=None,
        session_key: str | None = None,
        run_id: str | None = None,
        prompt_id: str | None = None,
    ):
        self.store = store
        self.workspace = workspace
        self.session_key = session_key
        self.run_id = run_id
        self.prompt_id = prompt_id

    async def __call__(self, tool: Tool, kwargs: dict[str, Any], next_fn: NextFn) -> ToolOutcome:
        paths = self._target_paths(tool.name, kwargs)
        if not paths:
            return await next_fn(tool, kwargs)

        before = {path: FileSnapshot.capture(path) for path in paths}
        result = await next_fn(tool, kwargs)
        normalized = normalize_tool_result(result)
        if not normalized.ok:
            return result

        after = {path: FileSnapshot.capture(path) for path in paths}
        record = self.store.create_record(
            session_key=self.session_key,
            tool_name=tool.name,
            arguments=kwargs,
            before=before,
            after=after,
            run_id=self.run_id,
            prompt_id=self.prompt_id,
            metadata={"result_status": normalized.status},
        )
        if record is not None:
            self.store.save(record)
        return result

    def _target_paths(self, tool_name: str, arguments: dict[str, Any]) -> list[str]:
        if tool_name not in FILESYSTEM_MUTATION_TOOLS:
            return []
        if tool_name in {"write_file", "edit_file"}:
            path = self._resolve_path(arguments.get("path"))
            return [path] if path else []
        if tool_name == "apply_patch":
            paths = []
            for path in self._patch_targets(arguments.get("patch_text") or ""):
                resolved = self._resolve_path(path)
                if resolved:
                    paths.append(resolved)
            return sorted(set(paths))
        return []

    def _resolve_path(self, path: str | None) -> str | None:
        if not path:
            return None
        if self.workspace is not None:
            resolved, err = self.workspace.resolve_contained_path(path, label="path")
            if err:
                return None
            return os.path.realpath(resolved)
        return os.path.realpath(os.path.expanduser(path))

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
