"""Deterministic memory-on versus memory-off coding evals."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

import yaml


REQUIRED_FIELDS = {"id", "prompt", "verification", "memory", "patches"}


@dataclass(frozen=True)
class MemoryCodingEvalTask:
    id: str
    prompt: str
    verification: list[str]
    memory_source_id: str
    memory_content: str
    required_memory_terms: list[str] = field(default_factory=list)
    memory_on_patches: dict[str, str] = field(default_factory=dict)
    memory_off_patches: dict[str, str] = field(default_factory=dict)
    root_dir: str | None = None
    repo_dir: str | None = None


@dataclass
class MemoryCodingEvalAttempt:
    memory_enabled: bool
    status: str
    workspace: str
    command_outputs: dict[str, str]
    retrieved_memory: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_enabled": self.memory_enabled,
            "status": self.status,
            "workspace": self.workspace,
            "command_outputs": self.command_outputs,
            "retrieved_memory": self.retrieved_memory,
        }


@dataclass
class MemoryCodingEvalReport:
    task_id: str
    status: str
    score: float
    checks: dict[str, bool]
    memory_on: MemoryCodingEvalAttempt
    memory_off: MemoryCodingEvalAttempt
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "score": self.score,
            "checks": self.checks,
            "memory_on": self.memory_on.to_dict(),
            "memory_off": self.memory_off.to_dict(),
            "created_at": self.created_at,
        }


def load_memory_coding_eval_task(task_dir: str) -> MemoryCodingEvalTask:
    task_dir = os.path.abspath(task_dir)
    task_path = os.path.join(task_dir, "task.yaml")
    if not os.path.exists(task_path):
        raise ValueError(f"Missing eval task file: {task_path}")
    with open(task_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Memory coding eval YAML must contain an object.")
    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        raise ValueError(f"Memory coding eval is missing required field(s): {', '.join(missing)}")

    memory = data["memory"]
    patches = data["patches"]
    if not isinstance(memory, dict):
        raise ValueError("Memory coding eval field 'memory' must be an object.")
    if not isinstance(patches, dict):
        raise ValueError("Memory coding eval field 'patches' must be an object.")

    task_id = str(data.get("id") or "").strip()
    prompt = str(data.get("prompt") or "").strip()
    if not task_id:
        raise ValueError("Memory coding eval id cannot be empty.")
    if not prompt:
        raise ValueError("Memory coding eval prompt cannot be empty.")

    return MemoryCodingEvalTask(
        id=task_id,
        prompt=prompt,
        verification=_coerce_string_list(data.get("verification"), "verification"),
        memory_source_id=str(memory.get("source_id") or "").strip(),
        memory_content=str(memory.get("content") or "").strip(),
        required_memory_terms=_coerce_string_list(memory.get("required_terms"), "memory.required_terms"),
        memory_on_patches=_coerce_patch_map(patches.get("memory_on"), "patches.memory_on"),
        memory_off_patches=_coerce_patch_map(patches.get("memory_off"), "patches.memory_off"),
        root_dir=task_dir,
        repo_dir=os.path.join(task_dir, "repo"),
    )


class MemoryCodingEvalRunner:
    def __init__(self, *, keep_workspaces: bool = False, command_runner=None):
        self.keep_workspaces = keep_workspaces
        self.command_runner = command_runner or subprocess.run

    def run(self, task_dir: str) -> MemoryCodingEvalReport:
        task = load_memory_coding_eval_task(task_dir)
        memory_off = self._run_attempt(task, memory_enabled=False)
        memory_on = self._run_attempt(task, memory_enabled=True)
        retrieved = memory_on.retrieved_memory.lower()
        checks = {
            "memory_on_passes": memory_on.status == "passed",
            "memory_off_fails": memory_off.status == "failed",
            "memory_terms_present": all(term.lower() in retrieved for term in task.required_memory_terms),
            "contrast_observed": memory_on.status != memory_off.status,
        }
        passed = sum(1 for ok in checks.values() if ok)
        return MemoryCodingEvalReport(
            task_id=task.id,
            status="passed" if all(checks.values()) else "failed",
            score=passed / len(checks),
            checks=checks,
            memory_on=memory_on,
            memory_off=memory_off,
        )

    def _run_attempt(self, task: MemoryCodingEvalTask, *, memory_enabled: bool) -> MemoryCodingEvalAttempt:
        workspace = self._copy_repo(task)
        retrieved_memory = task.memory_content if memory_enabled else ""
        patches = task.memory_on_patches if memory_enabled else task.memory_off_patches
        try:
            for relative_path, content in patches.items():
                path = os.path.abspath(os.path.join(workspace, relative_path))
                if not path.startswith(os.path.abspath(workspace) + os.sep):
                    raise ValueError(f"Patch path escapes workspace: {relative_path}")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                    if content and not content.endswith("\n"):
                        handle.write("\n")

            command_outputs = {}
            statuses = []
            for command in task.verification:
                status, output = self._run_command(command, workspace)
                command_outputs[command] = output
                statuses.append(status)
            return MemoryCodingEvalAttempt(
                memory_enabled=memory_enabled,
                status="passed" if statuses and all(statuses) else "failed",
                workspace=workspace,
                command_outputs=command_outputs,
                retrieved_memory=retrieved_memory,
            )
        finally:
            if not self.keep_workspaces:
                shutil.rmtree(workspace, ignore_errors=True)

    def _copy_repo(self, task: MemoryCodingEvalTask) -> str:
        workspace = tempfile.mkdtemp(prefix=f"smolclaw-memory-coding-{task.id}-")
        if task.repo_dir and os.path.isdir(task.repo_dir):
            shutil.copytree(task.repo_dir, workspace, dirs_exist_ok=True)
        return workspace

    def _run_command(self, command: str, workspace: str) -> tuple[bool, str]:
        parts = shlex.split(command)
        if parts and parts[0] == "python":
            parts[0] = sys.executable
        result = self.command_runner(
            parts,
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        output = (
            f"exit code {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        return result.returncode == 0, output


def _coerce_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Memory coding eval field '{field_name}' must be a list.")
    return [str(item) for item in value]


def _coerce_patch_map(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"Memory coding eval field '{field_name}' must be an object.")
    return {str(path): str(content) for path, content in value.items()}
