"""Checkpoint middleware for filesystem mutations."""

import os
from typing import Any

from app.checkpoints import CheckpointStore, FileSnapshot
from app.tools.base import (
    ACTIVE_TOOL_CALL_ID_STATE_KEY,
    ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY,
    TRACE_RECORDER_STATE_KEY,
    Tool,
    ToolOutcome,
    normalize_tool_result,
)
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
        shared_state: dict[str, Any] | None = None,
        goal_store=None,
    ):
        self.store = store
        self.workspace = workspace
        self.session_key = session_key
        self.run_id = run_id
        self.prompt_id = prompt_id
        self.shared_state = shared_state if shared_state is not None else {}
        self.goal_store = goal_store

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
            metadata={
                "result_status": normalized.status,
                "reason": self._mutation_reason(kwargs),
                "tool_call_id": self.shared_state.get(ACTIVE_TOOL_CALL_ID_STATE_KEY),
                "tool_trace_event_id": self.shared_state.get(ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY),
            },
        )
        if record is not None:
            self.store.save(record)
            self._record_checkpoint_evidence(record)
        return result

    def _record_checkpoint_evidence(self, record):
        trace_recorder = self.shared_state.get(TRACE_RECORDER_STATE_KEY)
        trace_event = None
        changed_paths = [self._display_path(path) for path in record.changed_paths]
        reason = str(record.metadata.get("reason") or "")
        tool_call_id = record.metadata.get("tool_call_id")
        tool_trace_event_id = record.metadata.get("tool_trace_event_id")
        if trace_recorder is not None:
            trace_event = trace_recorder.append("checkpoint.created", {
                "checkpoint_id": record.id,
                "tool_name": record.tool_name,
                "changed_paths": changed_paths,
                "reason": reason or None,
                "tool_call_id": tool_call_id,
                "tool_trace_event_id": tool_trace_event_id,
            })
        if self.goal_store is None or self.session_key is None:
            return
        record_evidence = getattr(self.goal_store, "record_evidence_with_result", None)
        if not callable(record_evidence):
            record_evidence = getattr(self.goal_store, "record_evidence", None)
            if not callable(record_evidence):
                return
        for path in changed_paths:
            try:
                recorded = record_evidence(
                    self.session_key,
                    kind="checkpoint",
                    summary=self._checkpoint_summary(record.tool_name, path, reason),
                    path=path,
                    trace_event_id=getattr(trace_event, "event_id", None),
                    tool_call_id=tool_call_id,
                    tool_trace_event_id=tool_trace_event_id,
                    checkpoint_id=record.id,
                )
            except ValueError:
                return
            if trace_recorder is not None:
                trace_recorder.append("ledger.updated", {
                    "kind": "checkpoint",
                    "ledger_path": getattr(recorded, "ledger_path", None),
                    "evidence_id": getattr(recorded, "evidence_id", None),
                    "related_trace_event_id": getattr(recorded, "related_trace_event_id", getattr(trace_event, "event_id", None)),
                    "tool_call_id": tool_call_id,
                    "tool_trace_event_id": tool_trace_event_id,
                    "checkpoint_id": record.id,
                    "path": path,
                    "reason": reason or None,
                })

    def _display_path(self, path: str) -> str:
        real_path = os.path.realpath(path)
        if self.workspace is not None and self.workspace.contains(real_path):
            return os.path.relpath(real_path, self.workspace.root_dir)
        return real_path

    def _mutation_reason(self, arguments: dict[str, Any]) -> str:
        reason = str(arguments.get("reason") or "").strip()
        if len(reason) <= 240:
            return reason
        return reason[:237] + "..."

    def _checkpoint_summary(self, tool_name: str, path: str, reason: str) -> str:
        summary = f"{tool_name} changed {path}"
        if reason:
            summary += f" ({reason})"
        return summary

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
