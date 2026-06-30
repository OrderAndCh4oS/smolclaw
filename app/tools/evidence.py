"""Middleware that records tool evidence into traces and goal ledgers."""

from __future__ import annotations

import shlex
from typing import Any

from app.runtime_state import RuntimeSharedState
from app.tools.base import Tool, ToolOutcome, normalize_tool_result, tool_policy_effects
from app.tools.middleware import NextFn


class EvidenceMiddleware:
    def __init__(
        self,
        *,
        shared_state: dict[str, Any] | None = None,
        goal_store=None,
        session_key: str | None = None,
    ):
        self.shared_state = shared_state if shared_state is not None else {}
        self.runtime_state = RuntimeSharedState(self.shared_state)
        self.goal_store = goal_store
        self.session_key = session_key

    async def __call__(self, tool: Tool, kwargs: dict[str, Any], next_fn: NextFn) -> ToolOutcome:
        result = await next_fn(tool, kwargs)
        normalized = normalize_tool_result(result)
        if tool.name == "run_command":
            self._record_command(kwargs, normalized)
        elif not normalized.ok:
            return result
        elif "memory_write" in tool_policy_effects(tool.get_call_policy(kwargs)):
            tool_call_id, tool_trace_event_id = self._active_tool_ids()
            self._record_ledger_evidence(
                kind="memory",
                summary=f"Memory state changed: {tool.name}",
                trace_event_id=tool_trace_event_id,
                tool_call_id=tool_call_id,
            )
        elif tool.name == "read_file":
            tool_call_id, tool_trace_event_id = self._active_tool_ids()
            self._record_ledger_evidence(
                kind="read",
                summary=f"Read file: {kwargs.get('path') or ''}",
                path=kwargs.get("path"),
                trace_event_id=tool_trace_event_id,
                tool_call_id=tool_call_id,
            )
        elif tool.name in {"find_files", "grep_search", "list_dir"}:
            tool_call_id, tool_trace_event_id = self._active_tool_ids()
            self._record_ledger_evidence(
                kind="search",
                summary=self._search_summary(tool.name, kwargs),
                path=kwargs.get("path") or ".",
                trace_event_id=tool_trace_event_id,
                tool_call_id=tool_call_id,
            )
        elif tool.name in {"git_status", "git_status_rich"}:
            tool_call_id, tool_trace_event_id = self._active_tool_ids()
            self._record_ledger_evidence(
                kind="status",
                summary="Checked git status",
                path=kwargs.get("cwd") or ".",
                trace_event_id=tool_trace_event_id,
                tool_call_id=tool_call_id,
            )
        elif tool.name == "git_diff":
            tool_call_id, tool_trace_event_id = self._active_tool_ids()
            self._record_ledger_evidence(
                kind="diff",
                summary="Inspected git diff",
                path=kwargs.get("path") or kwargs.get("cwd") or ".",
                trace_event_id=tool_trace_event_id,
                tool_call_id=tool_call_id,
            )
        return result

    def _record_command(self, kwargs: dict[str, Any], result):
        command = str(kwargs.get("command") or "").strip()
        if not command:
            return
        status = self._command_status(result)
        summary = self._command_summary(command, status)
        trace_recorder = self.runtime_state.trace_recorder
        trace_event = None
        tool_call_id, tool_trace_event_id = self._active_tool_ids()
        if self._is_verification_command(command):
            if trace_recorder is not None:
                trace_event = trace_recorder.append("verification.recorded", {
                    "command": command,
                    "status": status,
                    "summary": summary,
                    "tool_call_id": tool_call_id,
                    "tool_trace_event_id": tool_trace_event_id,
                })
            self._record_ledger_evidence(
                kind="test",
                summary=summary,
                command=command,
                status=status,
                trace_event_id=getattr(trace_event, "event_id", None),
                tool_call_id=tool_call_id,
                tool_trace_event_id=tool_trace_event_id,
            )
        else:
            self._record_ledger_evidence(
                kind="command",
                summary=summary,
                command=command,
                status=status,
                tool_call_id=tool_call_id,
                tool_trace_event_id=tool_trace_event_id,
            )

    def _record_ledger_evidence(
        self,
        *,
        kind: str,
        summary: str,
        path: str | None = None,
        command: str | None = None,
        status: str | None = None,
        trace_event_id: str | None = None,
        tool_call_id: str | None = None,
        tool_trace_event_id: str | None = None,
    ):
        if self.goal_store is None or self.session_key is None:
            return
        record_evidence = getattr(self.goal_store, "record_evidence_with_result", None)
        if not callable(record_evidence):
            record_evidence = getattr(self.goal_store, "record_evidence", None)
            if not callable(record_evidence):
                return
        try:
            recorded = record_evidence(
                self.session_key,
                kind=kind,
                summary=summary,
                path=path,
                command=command,
                status=status,
                tool_call_id=tool_call_id,
                trace_event_id=trace_event_id,
                tool_trace_event_id=tool_trace_event_id,
            )
        except ValueError:
            return
        trace_recorder = self.runtime_state.trace_recorder
        if trace_recorder is not None:
            evidence_id = getattr(recorded, "evidence_id", None)
            ledger_path = getattr(recorded, "ledger_path", None)
            related_trace_event_id = getattr(recorded, "related_trace_event_id", trace_event_id)
            trace_recorder.append("ledger.updated", {
                "kind": kind,
                "ledger_path": ledger_path,
                "evidence_id": evidence_id,
                "related_trace_event_id": related_trace_event_id,
                "summary": summary,
                "path": path,
                "command": command,
                "status": status,
                "tool_call_id": tool_call_id,
                "tool_trace_event_id": tool_trace_event_id,
            })

    def _command_status(self, result) -> str:
        if result.status == "denied":
            return "denied"
        if result.status == "error":
            return "error"
        if result.content.startswith("exit code 0"):
            return "passed"
        if result.content.startswith("exit code "):
            return "failed"
        if result.content.startswith("timed out"):
            return "timed_out"
        return result.status

    def _is_verification_command(self, command: str) -> bool:
        try:
            args = shlex.split(command)
        except ValueError:
            return False
        if not args:
            return False
        if args[0] == "pytest":
            return True
        if args[:3] == ["python", "-m", "pytest"]:
            return True
        if args[0] == "cargo" and len(args) > 1 and args[1] in {"test", "check"}:
            return True
        if args[:2] == ["go", "test"]:
            return True
        if len(args) >= 2 and args[0] in {"npm", "pnpm", "yarn", "bun"} and args[1] == "test":
            return True
        return (
            len(args) >= 3
            and args[0] in {"npm", "pnpm", "yarn", "bun"}
            and args[1] == "run"
            and args[2] in {"test", "check", "lint"}
        )

    def _command_summary(self, command: str, status: str) -> str:
        if self._is_verification_command(command):
            return f"Verification command {status}: {command}"
        return f"Command {status}: {command}"

    def _active_tool_ids(self) -> tuple[str | None, str | None]:
        return self.runtime_state.active_tool_ids

    def _search_summary(self, tool_name: str, kwargs: dict[str, Any]) -> str:
        path = kwargs.get("path") or "."
        if tool_name == "find_files":
            pattern = kwargs.get("pattern") or "**/*"
            return f"Found files in {path} matching {pattern}"
        if tool_name == "grep_search":
            query = kwargs.get("query") or ""
            return f"Searched {path} for {query}"
        return f"Listed directory: {path}"
