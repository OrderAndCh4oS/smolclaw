"""Agent-facing work-loop tools."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

import yaml

from app.command_adapters import build_command_adapter_bundle
from app.runtime_config import load_runtime_config
from app.tools.base import Tool, ToolCallPolicy, ToolRuntimeContext
from app.work_loop import TaskCandidate, WorkLoopConfig, WorkLoopRunner, resolve_work_loop_config_path


class _BaseWorkLoopTool(Tool):
    def __init__(
        self,
        *,
        workspace=None,
        runner_factory: Callable[..., Any] = WorkLoopRunner,
    ):
        self.workspace = workspace
        self.runner_factory = runner_factory

    @property
    def exposure(self) -> str:
        return "deferred"

    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(
            effects=frozenset({"network"}),
            requires_approval=True,
            mutates_state=True,
            tags=frozenset({"work_loop", "external_task"}),
        )

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return type(self)(
            workspace=runtime_ctx.workspace or self.workspace,
            runner_factory=self.runner_factory,
        )

    async def execute(self, **kwargs) -> str:
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    def _execute_sync(self, **kwargs) -> str:
        raise NotImplementedError

    def _build_runner(self, *, config_path: str, project: str = ""):
        adapter_config = load_runtime_config(self.workspace)
        config = WorkLoopConfig.load(config_path, project=project)
        explicit_task_source, explicit_code_review = _work_loop_explicit_adapter_types(config_path)
        config = WorkLoopConfig(
            **{
                **config.__dict__,
                "task_source_type": _task_source_type(config, adapter_config, explicit_task_source),
                "code_review_type": config.code_review_type if explicit_code_review else adapter_config.code_review.provider,
            }
        )
        command_adapters = build_command_adapter_bundle(adapter_config.command, workspace=self.workspace)
        return self.runner_factory(
            workspace=self.workspace,
            config=config,
            command_runner=command_adapters.infrastructure_runner,
        )

    def _config_path(self, kwargs: dict[str, Any]) -> str:
        return resolve_work_loop_config_path(kwargs.get("config_path"), workspace=self.workspace)

    def _project(self, kwargs: dict[str, Any]) -> str:
        return str(kwargs.get("project") or "").strip()


class WorkLoopListTasksTool(_BaseWorkLoopTool):
    @property
    def name(self) -> str:
        return "work_loop_list_tasks"

    @property
    def description(self) -> str:
        return (
            "List open or eligible tasks from the single configured work-loop "
            "task-source provider. Use the mounted provider; do not assume Jira."
        )

    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(
            effects=frozenset({"network"}),
            tags=frozenset({"work_loop", "external_task"}),
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": (
                        "Optional task-source project key, identifier, name, or id. "
                        "Omit to use configured work-loop or Kanboard environment defaults."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of tasks to list.",
                    "minimum": 1,
                    "maximum": 200,
                },
            },
        }

    def _execute_sync(self, **kwargs) -> str:
        if self.workspace is None:
            return "Error: work-loop task listing requires a local workspace."
        project = self._project(kwargs)
        limit = int(kwargs.get("limit") or 50)
        if limit < 1:
            return "Error: limit must be at least 1."
        runner = self._build_runner(config_path=self._config_path(kwargs), project=project)
        candidates = runner.task_source.search_backlog(runner.config, limit=limit)
        return _format_task_list(candidates)


class WorkLoopViewTaskTool(_BaseWorkLoopTool):
    @property
    def name(self) -> str:
        return "work_loop_view_task"

    @property
    def description(self) -> str:
        return "View a task from the single configured work-loop task-source provider by provider key."

    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(
            effects=frozenset({"network"}),
            tags=frozenset({"work_loop", "external_task"}),
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Provider task key, such as KB-42 or APP-123.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional task-source project key, identifier, name, or id.",
                },
            },
            "required": ["key"],
        }

    def _execute_sync(self, **kwargs) -> str:
        if self.workspace is None:
            return "Error: work-loop task viewing requires a local workspace."
        key = str(kwargs.get("key") or "").strip()
        if not key:
            return "Error: key is required."
        runner = self._build_runner(config_path=self._config_path(kwargs), project=self._project(kwargs))
        candidate = runner.task_source.view(key)
        return _format_task(candidate)


class WorkLoopCreateTaskTool(_BaseWorkLoopTool):
    @property
    def name(self) -> str:
        return "work_loop_create_task"

    @property
    def description(self) -> str:
        return (
            "Create a task in the single configured work-loop task-source "
            "provider. Use the mounted provider; do not assume Jira."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Task title to create.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional task-source project key, identifier, name, or id. "
                        "Omit to use configured work-loop or Kanboard environment defaults."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Task description/body.",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task labels or tags to apply.",
                },
                "status": {
                    "type": "string",
                    "description": "Initial task status or Kanboard column name.",
                },
            },
            "required": ["title"],
        }

    def _execute_sync(self, **kwargs) -> str:
        if self.workspace is None:
            return "Error: work-loop task creation requires a local workspace."
        title = str(kwargs.get("title") or "").strip()
        project = self._project(kwargs)
        if not title:
            return "Error: title is required."
        labels = kwargs.get("labels") or []
        if not isinstance(labels, list):
            return "Error: labels must be a list."
        runner = self._build_runner(config_path=self._config_path(kwargs), project=project)
        candidate = runner.create_task(
            title=title,
            description=str(kwargs.get("description") or ""),
            labels=[str(label) for label in labels],
            status=str(kwargs.get("status") or ""),
        )
        return _format_created_task(candidate)


class WorkLoopMoveTaskTool(_BaseWorkLoopTool):
    @property
    def name(self) -> str:
        return "work_loop_move_task"

    @property
    def description(self) -> str:
        return "Move or transition a task in the single configured work-loop task-source provider."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Provider task key, such as KB-42 or APP-123.",
                },
                "status": {
                    "type": "string",
                    "description": "Destination status, workflow state, or Kanboard column.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional task-source project key, identifier, name, or id.",
                },
            },
            "required": ["key", "status"],
        }

    def _execute_sync(self, **kwargs) -> str:
        if self.workspace is None:
            return "Error: work-loop task moves require a local workspace."
        key = str(kwargs.get("key") or "").strip()
        status = str(kwargs.get("status") or "").strip()
        if not key:
            return "Error: key is required."
        if not status:
            return "Error: status is required."
        runner = self._build_runner(config_path=self._config_path(kwargs), project=self._project(kwargs))
        runner.task_source.transition(key, status)
        try:
            candidate = runner.task_source.view(key)
        except Exception:
            candidate = None
        if candidate is not None:
            return "Moved task:\n" + _format_task(candidate)
        return f"Moved task {key} to {status}."


class WorkLoopCommentTaskTool(_BaseWorkLoopTool):
    @property
    def name(self) -> str:
        return "work_loop_comment_task"

    @property
    def description(self) -> str:
        return "Add a comment to a task in the single configured work-loop task-source provider."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Provider task key, such as KB-42 or APP-123.",
                },
                "body": {
                    "type": "string",
                    "description": "Comment body to add.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional task-source project key, identifier, name, or id.",
                },
            },
            "required": ["key", "body"],
        }

    def _execute_sync(self, **kwargs) -> str:
        if self.workspace is None:
            return "Error: work-loop task comments require a local workspace."
        key = str(kwargs.get("key") or "").strip()
        body = str(kwargs.get("body") or "").strip()
        if not key:
            return "Error: key is required."
        if not body:
            return "Error: body is required."
        runner = self._build_runner(config_path=self._config_path(kwargs), project=self._project(kwargs))
        runner.task_source.comment(key, body)
        return f"Added comment to task {key}."


class WorkLoopCloseTaskTool(_BaseWorkLoopTool):
    @property
    def name(self) -> str:
        return "work_loop_close_task"

    @property
    def description(self) -> str:
        return "Close or mark a task done in the single configured work-loop task-source provider."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Provider task key, such as KB-42 or APP-123.",
                },
                "project": {
                    "type": "string",
                    "description": "Optional task-source project key, identifier, name, or id.",
                },
            },
            "required": ["key"],
        }

    def _execute_sync(self, **kwargs) -> str:
        if self.workspace is None:
            return "Error: work-loop task closing requires a local workspace."
        key = str(kwargs.get("key") or "").strip()
        if not key:
            return "Error: key is required."
        runner = self._build_runner(config_path=self._config_path(kwargs), project=self._project(kwargs))
        runner.task_source.transition(key, "closed")
        return f"Closed task {key}."


def _work_loop_explicit_adapter_types(config_path: str) -> tuple[bool, bool]:
    if not config_path or not os.path.exists(config_path):
        return False, False
    with open(config_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return False, False
    task_source = data.get("task_source")
    code_review = data.get("code_review")
    return (
        "task_source_type" in data
        or (isinstance(task_source, dict) and ("type" in task_source or "provider" in task_source)),
        "code_review_type" in data
        or (isinstance(code_review, dict) and ("type" in code_review or "provider" in code_review)),
    )


def _task_source_type(config: WorkLoopConfig, adapter_config, explicit_task_source: bool) -> str:
    if explicit_task_source:
        return config.task_source_type
    provider = adapter_config.task_source.provider
    if provider != "jira":
        return provider
    if _has_kanboard_config(config) or _has_kanboard_environment():
        return "kanboard"
    return provider


def _has_kanboard_config(config: WorkLoopConfig) -> bool:
    return any((
        config.kanboard_url,
        config.kanboard_token,
        config.kanboard_token_file,
        config.kanboard_project_id,
        config.kanboard_project_name,
        config.kanboard_project_identifier,
    ))


def _has_kanboard_environment() -> bool:
    return any(os.getenv(name) for name in (
        "KANBOARD_URL",
        "KANBOARD_API_URL",
        "KANBOARD_API_TOKEN",
        "KANBOARD_PASSWORD",
        "KANBOARD_PROJECT",
        "KANBOARD_PROJECT_ID",
        "KANBOARD_PROJECT_IDENTIFIER",
        "KANBOARD_PROJECT_NAME",
    ))


def _format_created_task(candidate: TaskCandidate) -> str:
    lines = [f"Created task {candidate.key}: {candidate.summary}"]
    if candidate.status:
        lines.append(f"Status: {candidate.status}")
    if candidate.labels:
        lines.append(f"Labels: {', '.join(candidate.labels)}")
    if candidate.url:
        lines.append(f"URL: {candidate.url}")
    return "\n".join(lines)


def _format_task(candidate: TaskCandidate) -> str:
    lines = [f"{candidate.key}: {candidate.summary}"]
    if candidate.status:
        lines.append(f"Status: {candidate.status}")
    if candidate.labels:
        lines.append(f"Labels: {', '.join(candidate.labels)}")
    if candidate.url:
        lines.append(f"URL: {candidate.url}")
    if candidate.description:
        lines.append("")
        lines.append(candidate.description)
    return "\n".join(lines)


def _format_task_list(candidates: list[TaskCandidate]) -> str:
    if not candidates:
        return "No tasks found."
    return "\n".join(_format_task_summary(candidate) for candidate in candidates)


def _format_task_summary(candidate: TaskCandidate) -> str:
    parts = [f"{candidate.key}: {candidate.summary}"]
    details = []
    if candidate.status:
        details.append(candidate.status)
    if candidate.labels:
        details.append(", ".join(candidate.labels))
    if details:
        parts.append(f"({'; '.join(details)})")
    if candidate.url:
        parts.append(candidate.url)
    return " ".join(parts)
