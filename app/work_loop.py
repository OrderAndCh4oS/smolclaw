"""Jira/GitHub work-loop orchestration.

The work loop has two independently runnable modes:
- task intake from Jira through PR creation
- review feedback handling for PRs created by the loop

Durable state lives in a workspace-local ledger so the agent can list and
resume work it previously started.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml

from app.storage_paths import atomic_write_json, load_json_with_backup, safe_storage_stem
from app.workspace import WorkspaceContext


WorkItemState = Literal[
    "selected",
    "active",
    "blocked",
    "failed",
    "open-pr",
    "merged",
    "closed",
    "done",
]

DEFAULT_WORK_LOOP_CONFIG = "smolclaw.jira-loop.yaml"
PR_MARKER_PREFIX = "<!-- smolclaw-work-loop:"
MAX_INNER_ATTEMPTS = 5
STOP_FILE = "STOP"
PAUSE_FILE = "PAUSE"
JOBS_DIR = "jobs"
CONTROLS_DIR = "controls"
HEARTBEAT_FILE = "heartbeat.json"

_ACTIVE_PROCESS_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen] = set()


def _register_process(process: subprocess.Popen):
    with _ACTIVE_PROCESS_LOCK:
        _ACTIVE_PROCESSES.add(process)


def _unregister_process(process: subprocess.Popen):
    with _ACTIVE_PROCESS_LOCK:
        _ACTIVE_PROCESSES.discard(process)


def terminate_active_work_loop_processes():
    with _ACTIVE_PROCESS_LOCK:
        processes = list(_ACTIVE_PROCESSES)
    for process in processes:
        if process.poll() is not None:
            _unregister_process(process)
            continue
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.name == "posix":
                os.killpg(process.pid, 15)
            else:
                process.terminate()
    deadline = time.time() + 3
    for process in processes:
        remaining = max(0, deadline - time.time())
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=remaining)
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if os.name == "posix":
                    os.killpg(process.pid, 9)
                else:
                    process.kill()
        _unregister_process(process)


atexit.register(terminate_active_work_loop_processes)


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


class CommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        input_text: str | None = None,
        timeout: int = 600,
    ) -> CommandResult:
        ...


class SubprocessCommandRunner:
    def run(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        input_text: str | None = None,
        timeout: int = 600,
    ) -> CommandResult:
        process: subprocess.Popen | None = None
        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdin=subprocess.PIPE if input_text is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=(os.name == "posix"),
            )
            _register_process(process)
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            return CommandResult(args=args, returncode=process.returncode, stdout=stdout, stderr=stderr)
        except FileNotFoundError as exc:
            return CommandResult(args=args, returncode=127, stderr=str(exc))
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                terminate_active_work_loop_processes()
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return CommandResult(args=args, returncode=124, stdout=stdout, stderr=stderr or "Command timed out.")
        finally:
            if process is not None:
                _unregister_process(process)


@dataclass(frozen=True)
class WorkLoopConfig:
    project: str = ""
    base_branch: str = "main"
    max_concurrency: int = 2
    issue_types: list[str] = field(default_factory=lambda: ["Bug", "Task"])
    eligible_statuses: list[str] = field(default_factory=lambda: ["To Do", "Backlog", "Open"])
    blocked_labels: list[str] = field(default_factory=lambda: ["blocked", "do-not-automate"])
    required_label: str = ""
    selected_status: str = ""
    in_progress_status: str = "In Progress"
    review_status: str = "In Review"
    selector_model: str = "gpt-5.4-mini"
    coder_agent: str = "coder"
    agents_config: str = "agents.yaml"
    inner_max_turns: int = 6
    repair_attempts: int = 4
    verification_commands: list[str] = field(default_factory=list)
    lint_commands: list[str] = field(default_factory=list)
    format_commands: list[str] = field(default_factory=list)
    github_label: str = "agent-owned"

    @classmethod
    def load(cls, path: str | None, *, project: str = "") -> "WorkLoopConfig":
        if not path or not os.path.exists(path):
            return cls(project=project)
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Work-loop config must be a mapping: {path}")
        values = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        if project:
            values["project"] = project
        return cls(**values)


@dataclass
class JiraCandidate:
    key: str
    summary: str
    issue_type: str = ""
    status: str = ""
    assignee: str = ""
    priority: str = ""
    labels: list[str] = field(default_factory=list)
    description: str = ""
    url: str = ""


@dataclass
class VerificationRecord:
    command: str
    status: str
    output: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "status": self.status,
            "output": self.output,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VerificationRecord":
        return cls(
            command=str(data.get("command") or ""),
            status=str(data.get("status") or "unknown"),
            output=str(data.get("output") or ""),
            timestamp=float(data.get("timestamp") or time.time()),
        )


@dataclass
class ProcessedReviewComment:
    comment_id: str
    action: str
    response: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "comment_id": self.comment_id,
            "action": self.action,
            "response": self.response,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProcessedReviewComment":
        return cls(
            comment_id=str(data.get("comment_id") or ""),
            action=str(data.get("action") or ""),
            response=str(data.get("response") or ""),
            timestamp=float(data.get("timestamp") or time.time()),
        )


@dataclass
class WorkItem:
    jira_key: str
    title: str
    state: WorkItemState = "selected"
    run_id: str = field(default_factory=lambda: f"run-{uuid.uuid4().hex[:12]}")
    jira_url: str = ""
    selected_reason: str = ""
    workspace_path: str = ""
    branch_name: str = ""
    base_branch: str = "main"
    base_commit: str = ""
    pr_number: int | None = None
    pr_url: str = ""
    commits: list[str] = field(default_factory=list)
    verification: list[VerificationRecord] = field(default_factory=list)
    processed_review_comments: list[ProcessedReviewComment] = field(default_factory=list)
    blocker: str = ""
    updated_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "jira_key": self.jira_key,
            "title": self.title,
            "state": self.state,
            "run_id": self.run_id,
            "jira_url": self.jira_url,
            "selected_reason": self.selected_reason,
            "workspace_path": self.workspace_path,
            "branch_name": self.branch_name,
            "base_branch": self.base_branch,
            "base_commit": self.base_commit,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "commits": list(self.commits),
            "verification": [item.to_dict() for item in self.verification],
            "processed_review_comments": [item.to_dict() for item in self.processed_review_comments],
            "blocker": self.blocker,
            "updated_at": self.updated_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkItem":
        return cls(
            jira_key=str(data.get("jira_key") or ""),
            title=str(data.get("title") or ""),
            state=str(data.get("state") or "selected"),  # type: ignore[arg-type]
            run_id=str(data.get("run_id") or f"run-{uuid.uuid4().hex[:12]}"),
            jira_url=str(data.get("jira_url") or ""),
            selected_reason=str(data.get("selected_reason") or ""),
            workspace_path=str(data.get("workspace_path") or ""),
            branch_name=str(data.get("branch_name") or ""),
            base_branch=str(data.get("base_branch") or "main"),
            base_commit=str(data.get("base_commit") or ""),
            pr_number=data.get("pr_number"),
            pr_url=str(data.get("pr_url") or ""),
            commits=list(data.get("commits") or []),
            verification=[VerificationRecord.from_dict(item) for item in data.get("verification") or []],
            processed_review_comments=[
                ProcessedReviewComment.from_dict(item)
                for item in data.get("processed_review_comments") or []
            ],
            blocker=str(data.get("blocker") or ""),
            updated_at=float(data.get("updated_at") or time.time()),
            created_at=float(data.get("created_at") or time.time()),
        )


class WorkLoopLedger:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.realpath(root_dir)
        self.items_dir = os.path.join(self.root_dir, "items")
        os.makedirs(self.items_dir, exist_ok=True)

    @classmethod
    def for_workspace(cls, workspace: WorkspaceContext) -> "WorkLoopLedger":
        return cls(os.path.join(workspace.state_root_dir, "work-loop"))

    def _path(self, key: str) -> str:
        return os.path.join(self.items_dir, f"{safe_storage_stem(key)}.json")

    def save(self, item: WorkItem) -> WorkItem:
        item.updated_at = time.time()
        atomic_write_json(self._path(item.jira_key), item.to_dict())
        return item

    def load(self, key: str) -> WorkItem | None:
        data = load_json_with_backup(self._path(key))
        if not isinstance(data, dict):
            return None
        return WorkItem.from_dict(data)

    def list(self, state: str = "all") -> list[WorkItem]:
        items: list[WorkItem] = []
        for path in sorted(Path(self.items_dir).glob("*.json")):
            data = load_json_with_backup(str(path))
            if isinstance(data, dict):
                item = WorkItem.from_dict(data)
                if state == "all" or item.state == state:
                    items.append(item)
        return sorted(items, key=lambda item: item.updated_at, reverse=True)


class WorkLoopStopped(RuntimeError):
    pass


@dataclass
class WorkLoopJob:
    job_id: str
    mode: str
    command: list[str]
    state: str = "starting"
    pid: int | None = None
    pgid: int | None = None
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    heartbeat_at: float | None = None
    exit_code: int | None = None
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "mode": self.mode,
            "command": list(self.command),
            "state": self.state,
            "pid": self.pid,
            "pgid": self.pgid,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "heartbeat_at": self.heartbeat_at,
            "exit_code": self.exit_code,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkLoopJob":
        return cls(
            job_id=str(data.get("job_id") or ""),
            mode=str(data.get("mode") or ""),
            command=[str(item) for item in data.get("command") or []],
            state=str(data.get("state") or "unknown"),
            pid=data.get("pid"),
            pgid=data.get("pgid"),
            started_at=float(data.get("started_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            heartbeat_at=data.get("heartbeat_at"),
            exit_code=data.get("exit_code"),
            message=str(data.get("message") or ""),
        )


class WorkLoopControl:
    def __init__(self, root_dir: str, *, job_id: str | None = None):
        self.root_dir = os.path.realpath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)
        self.job_id = job_id

    @classmethod
    def for_workspace(cls, workspace: WorkspaceContext, *, job_id: str | None = None) -> "WorkLoopControl":
        return cls(os.path.join(workspace.state_root_dir, "work-loop"), job_id=job_id)

    @property
    def control_dir(self) -> str:
        if not self.job_id:
            return self.root_dir
        path = os.path.join(self.root_dir, CONTROLS_DIR, safe_storage_stem(self.job_id))
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def stop_path(self) -> str:
        return os.path.join(self.control_dir, STOP_FILE)

    @property
    def pause_path(self) -> str:
        return os.path.join(self.control_dir, PAUSE_FILE)

    @property
    def global_stop_path(self) -> str:
        return os.path.join(self.root_dir, STOP_FILE)

    @property
    def global_pause_path(self) -> str:
        return os.path.join(self.root_dir, PAUSE_FILE)

    @property
    def heartbeat_path(self) -> str:
        return os.path.join(self.control_dir, HEARTBEAT_FILE)

    def stop(self, reason: str = "User requested stop."):
        Path(self.stop_path).write_text(reason.strip() + "\n", encoding="utf-8")

    def pause(self, reason: str = "User requested pause."):
        Path(self.pause_path).write_text(reason.strip() + "\n", encoding="utf-8")

    def resume(self):
        for path in (self.stop_path, self.pause_path):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)

    def status(self) -> str:
        if os.path.exists(self.stop_path) or os.path.exists(self.global_stop_path):
            return "stopped"
        if os.path.exists(self.pause_path) or os.path.exists(self.global_pause_path):
            return "paused"
        return "running"

    def heartbeat(self, step: str):
        atomic_write_json(
            self.heartbeat_path,
            {"job_id": self.job_id, "step": step, "timestamp": time.time()},
            backup=False,
        )

    def check(self, step: str):
        self.heartbeat(step)
        stop_path = self.stop_path if os.path.exists(self.stop_path) else self.global_stop_path
        pause_path = self.pause_path if os.path.exists(self.pause_path) else self.global_pause_path
        if os.path.exists(stop_path):
            reason = Path(stop_path).read_text(encoding="utf-8").strip()
            raise WorkLoopStopped(f"Stopped before {step}: {reason or 'stop requested'}")
        if os.path.exists(pause_path):
            reason = Path(pause_path).read_text(encoding="utf-8").strip()
            raise WorkLoopStopped(f"Paused before {step}: {reason or 'pause requested'}")


class WorkLoopJobStore:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.realpath(root_dir)
        self.jobs_dir = os.path.join(self.root_dir, JOBS_DIR)
        os.makedirs(self.jobs_dir, exist_ok=True)

    @classmethod
    def for_workspace(cls, workspace: WorkspaceContext) -> "WorkLoopJobStore":
        return cls(os.path.join(workspace.state_root_dir, "work-loop"))

    def _path(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{safe_storage_stem(job_id)}.json")

    def save(self, job: WorkLoopJob) -> WorkLoopJob:
        job.updated_at = time.time()
        atomic_write_json(self._path(job.job_id), job.to_dict())
        return job

    def load(self, job_id: str) -> WorkLoopJob | None:
        data = load_json_with_backup(self._path(job_id))
        return WorkLoopJob.from_dict(data) if isinstance(data, dict) else None

    def list(self) -> list[WorkLoopJob]:
        jobs: list[WorkLoopJob] = []
        for path in sorted(Path(self.jobs_dir).glob("*.json")):
            data = load_json_with_backup(str(path))
            if isinstance(data, dict):
                jobs.append(WorkLoopJob.from_dict(data))
        return sorted(jobs, key=lambda item: item.updated_at, reverse=True)


class WorkLoopJobSupervisor:
    def __init__(self, workspace: WorkspaceContext, *, runner: CommandRunner | None = None):
        self.workspace = workspace.ensure_dirs()
        self.root_dir = os.path.join(self.workspace.state_root_dir, "work-loop")
        self.store = WorkLoopJobStore(self.root_dir)
        self.runner = runner

    @classmethod
    def for_workspace(cls, workspace: WorkspaceContext) -> "WorkLoopJobSupervisor":
        return cls(workspace)

    def start(self, mode: str, worker_args: list[str]) -> WorkLoopJob:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        command = [sys.executable, "-m", "cli.main", "work-loop", "worker", "--job-id", job_id, "--mode", mode, *worker_args]
        job = self.store.save(WorkLoopJob(job_id=job_id, mode=mode, command=command))
        try:
            process = subprocess.Popen(
                command,
                cwd=self.workspace.root_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            job.state = "failed"
            job.message = str(exc)
            return self.store.save(job)
        job.pid = process.pid
        if os.name == "posix":
            with contextlib.suppress(OSError):
                job.pgid = os.getpgid(process.pid)
        job.state = "running"
        job.message = "Job started."
        return self.store.save(job)

    def stop(self, target: str = "all", *, reason: str = "User requested stop.", grace_seconds: float = 3.0) -> list[WorkLoopJob]:
        jobs = self._target_jobs(target)
        for job in jobs:
            WorkLoopControl(self.root_dir, job_id=job.job_id).stop(reason)
        deadline = time.time() + grace_seconds
        while time.time() < deadline and any(self._is_alive(job) for job in jobs):
            time.sleep(0.05)
        for job in jobs:
            if self._is_alive(job):
                self._terminate_job(job, kill=False)
        deadline = time.time() + 1.0
        while time.time() < deadline and any(self._is_alive(job) for job in jobs):
            time.sleep(0.05)
        for job in jobs:
            if self._is_alive(job):
                self._terminate_job(job, kill=True)
            job.state = "stopped"
            job.message = reason
            self.store.save(job)
        return jobs

    def pause(self, target: str = "all", *, reason: str = "User requested pause.") -> list[WorkLoopJob]:
        jobs = self._target_jobs(target)
        for job in jobs:
            WorkLoopControl(self.root_dir, job_id=job.job_id).pause(reason)
            job.state = "paused"
            job.message = reason
            self.store.save(job)
        return jobs

    def resume(self, target: str = "all") -> list[WorkLoopJob]:
        jobs = self._target_jobs(target)
        for job in jobs:
            WorkLoopControl(self.root_dir, job_id=job.job_id).resume()
            if job.state == "paused":
                job.state = "running"
            job.message = "Resume requested."
            self.store.save(job)
        return jobs

    def _target_jobs(self, target: str) -> list[WorkLoopJob]:
        jobs = self.store.list()
        if target == "all":
            return [job for job in jobs if job.state in {"starting", "running", "paused", "stopping"}]
        return [job for job in jobs if job.job_id == target]

    def _is_alive(self, job: WorkLoopJob) -> bool:
        if not job.pid:
            return False
        with contextlib.suppress(ProcessLookupError):
            os.kill(job.pid, 0)
            return True
        return False

    def _terminate_job(self, job: WorkLoopJob, *, kill: bool):
        if not job.pid:
            return
        sig = 9 if kill else 15
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.name == "posix":
                os.killpg(job.pgid or job.pid, sig)
            elif kill:
                subprocess.run(["taskkill", "/PID", str(job.pid), "/T", "/F"], check=False)
            else:
                os.kill(job.pid, sig)


class JiraAdapter:
    def __init__(self, runner: CommandRunner):
        self.runner = runner

    def auth_ok(self) -> bool:
        return self.runner.run(["acli", "auth", "status"], timeout=30).ok

    def search_backlog(self, config: WorkLoopConfig, *, limit: int = 50) -> list[JiraCandidate]:
        jql = build_backlog_jql(config)
        result = self.runner.run(
            [
                "acli",
                "jira",
                "workitem",
                "search",
                "--jql",
                jql,
                "--fields",
                "issuetype,key,assignee,priority,status,summary,labels",
                "--limit",
                str(limit),
                "--json",
            ],
            timeout=60,
        )
        if not result.ok:
            raise RuntimeError(f"Jira search failed: {result.output.strip()}")
        return parse_jira_candidates(result.stdout)

    def view(self, key: str) -> JiraCandidate:
        result = self.runner.run(
            [
                "acli",
                "jira",
                "workitem",
                "view",
                key,
                "--fields",
                "key,issuetype,summary,status,assignee,description,labels",
                "--json",
            ],
            timeout=60,
        )
        if not result.ok:
            raise RuntimeError(f"Jira view failed for {key}: {result.output.strip()}")
        candidates = parse_jira_candidates(result.stdout)
        if not candidates:
            raise RuntimeError(f"Jira view returned no work item for {key}")
        return candidates[0]

    def transition(self, key: str, status: str):
        if not status:
            return
        result = self.runner.run(
            [
                "acli",
                "jira",
                "workitem",
                "transition",
                "--key",
                key,
                "--status",
                status,
                "--yes",
                "--json",
            ],
            timeout=60,
        )
        if not result.ok:
            raise RuntimeError(f"Jira transition failed for {key}: {result.output.strip()}")

    def comment(self, key: str, body: str):
        result = self.runner.run(
            ["acli", "jira", "workitem", "comment", "create", "--key", key, "--body", body],
            timeout=60,
        )
        if not result.ok:
            raise RuntimeError(f"Jira comment failed for {key}: {result.output.strip()}")


class GitHubAdapter:
    def __init__(self, runner: CommandRunner):
        self.runner = runner

    def auth_ok(self) -> bool:
        return self.runner.run(["gh", "auth", "status"], timeout=30).ok

    def create_pr(self, item: WorkItem, body: str, *, base_branch: str, label: str = "") -> tuple[int | None, str]:
        args = [
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            item.branch_name,
            "--title",
            f"{item.jira_key}: {item.title}",
            "--body",
            body,
        ]
        if label:
            args.extend(["--label", label])
        result = self.runner.run(args, cwd=item.workspace_path, timeout=60)
        if not result.ok:
            raise RuntimeError(f"PR creation failed for {item.jira_key}: {result.output.strip()}")
        url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        return parse_pr_number(url), url

    def view_pr(self, pr_number: int) -> dict:
        result = self.runner.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--comments",
                "--json",
                "number,url,state,headRefName,comments,reviews,reviewDecision,statusCheckRollup",
            ],
            timeout=60,
        )
        if not result.ok:
            raise RuntimeError(f"PR view failed for {pr_number}: {result.output.strip()}")
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"PR view returned invalid JSON for {pr_number}") from exc
        return payload if isinstance(payload, dict) else {}

    def comment(self, pr_number: int, body: str):
        result = self.runner.run(["gh", "pr", "comment", str(pr_number), "--body", body], timeout=60)
        if not result.ok:
            raise RuntimeError(f"PR comment failed for {pr_number}: {result.output.strip()}")


@dataclass(frozen=True)
class TaskExecutionResult:
    success: bool
    summary: str
    verification: list[VerificationRecord] = field(default_factory=list)
    manual_steps: str = ""
    blocker: str = ""
    attempts: int = 0
    capped: bool = False


class CliAgentTaskExecutor:
    def __init__(self, runner: CommandRunner, control: WorkLoopControl | None = None):
        self.runner = runner
        self.control = control

    def execute(
        self,
        item: WorkItem,
        candidate: JiraCandidate,
        config: WorkLoopConfig,
        *,
        review_feedback: str = "",
    ) -> TaskExecutionResult:
        commands = discover_done_gate_commands(item.workspace_path, config)
        prompt = build_task_prompt(candidate, commands, review_feedback=review_feedback)
        blocker = ""
        verification: list[VerificationRecord] = []
        max_attempts = max(1, min(config.repair_attempts + 1, MAX_INNER_ATTEMPTS))
        for attempt in range(max_attempts):
            if self.control is not None:
                self.control.check(f"agent attempt {attempt + 1} for {item.jira_key}")
            run_result = self.runner.run(
                [
                    sys.executable,
                    "-m",
                    "cli.main",
                    "run",
                    prompt,
                    "--workspace",
                    item.workspace_path,
                    "--agent",
                    config.coder_agent,
                    "--agents-config",
                    config.agents_config,
                    "--goal",
                    "--max-turns",
                    str(config.inner_max_turns),
                ],
                cwd=item.workspace_path,
                timeout=3600,
            )
            if not run_result.ok:
                blocker = f"Agent run failed: {run_result.output.strip()}"
                continue
            if self.control is not None:
                self.control.check(f"verification for {item.jira_key}")
            verification = run_verification_commands(self.runner, item.workspace_path, commands)
            failed = [record for record in verification if record.status != "passed"]
            if not failed:
                return TaskExecutionResult(
                    success=True,
                    summary="Implementation completed and verification passed.",
                    verification=verification,
                    manual_steps=manual_testing_steps(candidate),
                    attempts=attempt + 1,
                )
            failure_summary = "\n\n".join(
                f"{record.command}\n{record.output[-4000:]}" for record in failed
            )
            prompt = build_repair_prompt(candidate, failure_summary, attempt=attempt + 1)
            blocker = f"Verification failed after attempt {attempt + 1}."
        return TaskExecutionResult(
            success=False,
            summary=f"Task reached the {max_attempts}-attempt work-loop cap before verification passed.",
            verification=verification,
            manual_steps=manual_testing_steps(candidate),
            blocker=blocker or "Task did not complete.",
            attempts=max_attempts,
            capped=True,
        )


class WorkLoopRunner:
    def __init__(
        self,
        *,
        workspace: WorkspaceContext,
        config: WorkLoopConfig,
        command_runner: CommandRunner | None = None,
        jira: JiraAdapter | None = None,
        github: GitHubAdapter | None = None,
        ledger: WorkLoopLedger | None = None,
        task_executor: CliAgentTaskExecutor | None = None,
        job_id: str | None = None,
    ):
        self.workspace = workspace.ensure_dirs()
        self.config = config
        self.command_runner = command_runner or SubprocessCommandRunner()
        self.jira = jira or JiraAdapter(self.command_runner)
        self.github = github or GitHubAdapter(self.command_runner)
        self.ledger = ledger or WorkLoopLedger.for_workspace(self.workspace)
        self.control = WorkLoopControl.for_workspace(self.workspace, job_id=job_id)
        self.task_executor = task_executor or CliAgentTaskExecutor(self.command_runner, control=self.control)

    def preflight(self, *, require_jira: bool = True, require_github: bool = True) -> list[str]:
        errors: list[str] = []
        try:
            self.control.check("preflight")
        except WorkLoopStopped as exc:
            return [str(exc)]
        if require_jira and not self.jira.auth_ok():
            errors.append("Jira auth failed: run `acli auth login`.")
        if require_github and not self.github.auth_ok():
            errors.append("GitHub auth failed: run `gh auth login`.")
        status = self.command_runner.run(["git", "status", "--porcelain"], cwd=self.workspace.root_dir, timeout=30)
        if not status.ok:
            errors.append(f"Could not inspect git status: {status.output.strip()}")
        elif status.stdout.strip():
            errors.append("Base repository has uncommitted changes; start from a clean base before work-loop runs.")
        fetch = self.command_runner.run(
            ["git", "fetch", "origin", self.config.base_branch],
            cwd=self.workspace.root_dir,
            timeout=120,
        )
        if not fetch.ok:
            errors.append(f"Could not fetch origin/{self.config.base_branch}: {fetch.output.strip()}")
        if not discover_done_gate_commands(self.workspace.root_dir, self.config):
            errors.append("No verification commands discovered; configure verification_commands.")
        return errors

    def run_tasks(self, *, limit: int | None = None, dry_run: bool = False) -> list[WorkItem]:
        self.control.check("task loop")
        errors = self.preflight(require_jira=True, require_github=True)
        if errors:
            raise RuntimeError("\n".join(errors))
        candidates = eligible_candidates(self.jira.search_backlog(self.config), self.config)
        selected = select_candidates(candidates, limit=limit or self.config.max_concurrency)
        items: list[WorkItem] = []
        for index, candidate in enumerate(selected, start=1):
            self.control.check(f"selecting Jira task {candidate.key}")
            detailed = self.jira.view(candidate.key)
            item = self.ledger.load(detailed.key) or WorkItem(
                jira_key=detailed.key,
                title=detailed.summary,
                jira_url=detailed.url,
                selected_reason="Selected as low-risk unassigned Jira task.",
                base_branch=self.config.base_branch,
            )
            item.branch_name = branch_name_for_ticket(detailed.key, detailed.summary)
            item.workspace_path = self._workspace_for_item(item, index)
            self.ledger.save(item)
            if not dry_run:
                self._execute_item(item, detailed)
            items.append(self.ledger.load(item.jira_key) or item)
        return items

    def run_reviews(self, *, dry_run: bool = False) -> list[WorkItem]:
        self.control.check("review loop")
        errors = self.preflight(require_jira=False, require_github=True)
        if errors:
            raise RuntimeError("\n".join(errors))
        updated: list[WorkItem] = []
        for item in self.ledger.list("open-pr"):
            self.control.check(f"reviewing PR for {item.jira_key}")
            if item.pr_number is None:
                continue
            pr = self.github.view_pr(item.pr_number)
            comments = new_actionable_comments(pr, item)
            check_summary = summarize_status_checks(pr)
            if not comments and not check_summary:
                continue
            if dry_run:
                updated.append(item)
                continue
            feedback_parts = []
            if comments:
                feedback_parts.append("Review comments:\n" + "\n\n".join(comment["body"] for comment in comments))
            if check_summary:
                feedback_parts.append("GitHub checks:\n" + check_summary)
            feedback = "\n\n".join(feedback_parts)
            candidate = JiraCandidate(key=item.jira_key, summary=item.title, description=feedback)
            self._ensure_branch_workspace(item)
            self.control.check(f"executing review fixes for {item.jira_key}")
            result = self.task_executor.execute(item, candidate, self.config, review_feedback=feedback)
            item.verification.extend(result.verification)
            self.control.check(f"committing review fixes for {item.jira_key}")
            commit_sha = self._commit_and_push(item, result)
            if commit_sha:
                item.commits.append(commit_sha)
            response = render_review_response(result)
            self.control.check(f"commenting on PR for {item.jira_key}")
            self.github.comment(item.pr_number, response)
            for comment in comments:
                item.processed_review_comments.append(
                    ProcessedReviewComment(
                        comment_id=str(comment["id"]),
                        action="fixed" if result.success else "pushed-incomplete",
                        response=response,
                    )
                )
            if not result.success:
                item.blocker = result.blocker
            self.ledger.save(item)
            updated.append(item)
        return updated

    def _execute_item(self, item: WorkItem, candidate: JiraCandidate):
        self.control.check(f"creating workspace for {item.jira_key}")
        self._create_branch_workspace(item)
        item.state = "active"
        self.ledger.save(item)
        if self.config.selected_status:
            self.control.check(f"transitioning {item.jira_key} to selected")
            self.jira.transition(item.jira_key, self.config.selected_status)
        self.control.check(f"transitioning {item.jira_key} to in progress")
        self.jira.transition(item.jira_key, self.config.in_progress_status)
        self.control.check(f"executing {item.jira_key}")
        result = self.task_executor.execute(item, candidate, self.config)
        item.verification.extend(result.verification)
        if not result.success:
            item.blocker = result.blocker
        self.control.check(f"committing {item.jira_key}")
        commit_sha = self._commit_and_push(item, result)
        if commit_sha:
            item.commits.append(commit_sha)
        self.control.check(f"creating PR for {item.jira_key}")
        body = render_pr_body(item, candidate, result)
        pr_number, pr_url = self.github.create_pr(
            item,
            body,
            base_branch=self.config.base_branch,
            label=self.config.github_label,
        )
        item.pr_number = pr_number
        item.pr_url = pr_url
        item.state = "open-pr"
        self.control.check(f"transitioning {item.jira_key} to review")
        self.jira.transition(item.jira_key, self.config.review_status)
        self.control.check(f"commenting on Jira for {item.jira_key}")
        self.jira.comment(item.jira_key, render_jira_pr_comment(pr_url, result))
        self.ledger.save(item)
        shutil.rmtree(item.workspace_path, ignore_errors=True)

    def _workspace_for_item(self, item: WorkItem, index: int) -> str:
        batch_dir = os.path.join(self.workspace.state_root_dir, "work-loop", "runs", item.run_id)
        return os.path.join(batch_dir, f"run_{index}")

    def _create_branch_workspace(self, item: WorkItem):
        os.makedirs(os.path.dirname(item.workspace_path), exist_ok=True)
        add = self.command_runner.run(
            [
                "git",
                "worktree",
                "add",
                "-b",
                item.branch_name,
                item.workspace_path,
                f"origin/{self.config.base_branch}",
            ],
            cwd=self.workspace.root_dir,
            timeout=120,
        )
        if not add.ok:
            raise RuntimeError(f"Could not create worktree for {item.jira_key}: {add.output.strip()}")
        rev = self.command_runner.run(["git", "rev-parse", "HEAD"], cwd=item.workspace_path, timeout=30)
        item.base_commit = rev.stdout.strip() if rev.ok else ""
        self.ledger.save(item)

    def _ensure_branch_workspace(self, item: WorkItem):
        if item.workspace_path and os.path.exists(item.workspace_path):
            return
        if not item.workspace_path:
            item.workspace_path = self._workspace_for_item(item, 1)
        os.makedirs(os.path.dirname(item.workspace_path), exist_ok=True)
        result = self.command_runner.run(
            ["git", "worktree", "add", item.workspace_path, item.branch_name],
            cwd=self.workspace.root_dir,
            timeout=120,
        )
        if not result.ok:
            raise RuntimeError(f"Could not recreate worktree for {item.jira_key}: {result.output.strip()}")
        self.ledger.save(item)

    def _commit_and_push(self, item: WorkItem, result: TaskExecutionResult) -> str:
        add = self.command_runner.run(["git", "add", "."], cwd=item.workspace_path, timeout=120)
        if not add.ok:
            raise RuntimeError(f"git add failed for {item.jira_key}: {add.output.strip()}")
        status = self.command_runner.run(["git", "status", "--porcelain"], cwd=item.workspace_path, timeout=30)
        if not status.ok:
            raise RuntimeError(f"git status failed for {item.jira_key}: {status.output.strip()}")
        if not status.stdout.strip() and result.success:
            raise RuntimeError(f"No commit-worthy changes for {item.jira_key}.")
        commit_args = ["git", "commit", "-m", render_commit_message(item, result)]
        if not status.stdout.strip():
            commit_args.insert(2, "--allow-empty")
        commit = self.command_runner.run(
            commit_args,
            cwd=item.workspace_path,
            timeout=120,
        )
        if not commit.ok:
            raise RuntimeError(f"git commit failed for {item.jira_key}: {commit.output.strip()}")
        sha = self.command_runner.run(["git", "rev-parse", "HEAD"], cwd=item.workspace_path, timeout=30)
        push = self.command_runner.run(
            ["git", "push", "-u", "origin", item.branch_name],
            cwd=item.workspace_path,
            timeout=180,
        )
        if not push.ok:
            raise RuntimeError(f"git push failed for {item.jira_key}: {push.output.strip()}")
        return sha.stdout.strip() if sha.ok else ""


def build_backlog_jql(config: WorkLoopConfig) -> str:
    if not config.project:
        raise ValueError("A Jira project key is required.")
    parts = [f"project = {config.project}"]
    if config.issue_types:
        issue_types = ", ".join(f'"{item}"' for item in config.issue_types)
        parts.append(f"issuetype in ({issue_types})")
    if config.eligible_statuses:
        statuses = ", ".join(f'"{item}"' for item in config.eligible_statuses)
        parts.append(f"status in ({statuses})")
    parts.append("assignee is EMPTY")
    if config.required_label:
        parts.append(f'labels = "{config.required_label}"')
    for label in config.blocked_labels:
        parts.append(f'labels != "{label}"')
    return " AND ".join(parts) + " ORDER BY updated DESC"


def parse_jira_candidates(raw: str) -> list[JiraCandidate]:
    if not raw.strip():
        return []
    payload = json.loads(raw)
    if isinstance(payload, dict):
        values = payload.get("issues") or payload.get("workItems") or payload.get("values") or [payload]
    else:
        values = payload
    candidates: list[JiraCandidate] = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else item
        candidates.append(
            JiraCandidate(
                key=str(item.get("key") or fields.get("key") or ""),
                summary=_field_text(fields.get("summary")),
                issue_type=_field_name(fields.get("issuetype")),
                status=_field_name(fields.get("status")),
                assignee=_field_name(fields.get("assignee")),
                priority=_field_name(fields.get("priority")),
                labels=[str(label) for label in fields.get("labels") or []],
                description=_field_text(fields.get("description")),
                url=str(item.get("self") or fields.get("url") or ""),
            )
        )
    return [candidate for candidate in candidates if candidate.key]


def _field_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("displayName") or value.get("value") or "")
    return str(value or "")


def _field_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True)


def eligible_candidates(candidates: list[JiraCandidate], config: WorkLoopConfig) -> list[JiraCandidate]:
    blocked = {label.lower() for label in config.blocked_labels}
    eligible_types = {item.lower() for item in config.issue_types}
    eligible_statuses = {item.lower() for item in config.eligible_statuses}
    result: list[JiraCandidate] = []
    for candidate in candidates:
        if candidate.assignee.strip():
            continue
        if eligible_types and candidate.issue_type.lower() not in eligible_types:
            continue
        if eligible_statuses and candidate.status.lower() not in eligible_statuses:
            continue
        labels = {label.lower() for label in candidate.labels}
        if blocked.intersection(labels):
            continue
        if config.required_label and config.required_label.lower() not in labels:
            continue
        if len(candidate.description or candidate.summary) > 12000:
            continue
        result.append(candidate)
    return result


def select_candidates(candidates: list[JiraCandidate], *, limit: int) -> list[JiraCandidate]:
    return sorted(candidates, key=lambda item: (priority_rank(item.priority), len(item.description or item.summary)))[:limit]


def priority_rank(priority: str) -> int:
    order = {"highest": 0, "high": 1, "medium": 2, "low": 3, "lowest": 4}
    return order.get(priority.lower(), 2)


def branch_name_for_ticket(key: str, summary: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", summary.lower()).strip("-")
    slug = slug[:48].strip("-") or "task"
    return f"{key}-{slug}"


def discover_done_gate_commands(root: str, config: WorkLoopConfig) -> list[str]:
    configured = [*config.format_commands, *config.lint_commands, *config.verification_commands]
    if configured:
        return configured
    commands: list[str] = []
    package_json = os.path.join(root, "package.json")
    if os.path.exists(package_json):
        try:
            with open(package_json, encoding="utf-8") as handle:
                package = json.load(handle)
            scripts = package.get("scripts") if isinstance(package, dict) else {}
            if isinstance(scripts, dict):
                if "format:check" in scripts:
                    commands.append("npm run format:check")
                elif "format" in scripts:
                    commands.append("npm run format -- --check")
                if "lint" in scripts:
                    commands.append("npm run lint")
                if "typecheck" in scripts:
                    commands.append("npm run typecheck")
                if "test" in scripts:
                    commands.append("npm test")
        except (OSError, json.JSONDecodeError):
            pass
    if os.path.exists(os.path.join(root, "pyproject.toml")) or os.path.exists(os.path.join(root, "pytest.ini")):
        commands.append("python -m pytest")
    if os.path.exists(os.path.join(root, "Cargo.toml")):
        commands.append("cargo test")
    if os.path.exists(os.path.join(root, "go.mod")):
        commands.append("go test ./...")
    return list(dict.fromkeys(commands))


def run_verification_commands(
    runner: CommandRunner,
    cwd: str,
    commands: list[str],
) -> list[VerificationRecord]:
    records: list[VerificationRecord] = []
    for command in commands:
        result = runner.run(shlex.split(command), cwd=cwd, timeout=1800)
        records.append(
            VerificationRecord(
                command=command,
                status="passed" if result.ok else "failed",
                output=result.output[-8000:],
            )
        )
    return records


def build_task_prompt(candidate: JiraCandidate, commands: list[str], *, review_feedback: str = "") -> str:
    feedback = f"\n\nReview feedback to address:\n{review_feedback}" if review_feedback else ""
    command_block = "\n".join(f"- {command}" for command in commands) or "- <none discovered>"
    return (
        f"Complete Jira ticket {candidate.key}: {candidate.summary}\n\n"
        f"Ticket description:\n{candidate.description or candidate.summary}\n\n"
        "Respect the repository AGENTS.md/CLAUDE.md instructions for API design, type definitions, "
        "validation, testing, and established UX/UI patterns. Read relevant files before editing. "
        "Write or update appropriate tests. Continue until the ticket requirements are complete.\n\n"
        f"Verification commands expected by the outer loop:\n{command_block}"
        f"{feedback}"
    )


def build_repair_prompt(candidate: JiraCandidate, failure_summary: str, *, attempt: int) -> str:
    return (
        f"Repair Jira ticket {candidate.key}: {candidate.summary}\n\n"
        f"Verification failed on repair attempt {attempt}. Fix the implementation or tests while "
        "continuing to respect the ticket requirements and repository guidance.\n\n"
        f"Failure output:\n{failure_summary}"
    )


def manual_testing_steps(candidate: JiraCandidate) -> str:
    return (
        f"Manually exercise the workflow affected by {candidate.key} and confirm the behavior "
        "matches the Jira acceptance requirements."
    )


def work_status(result: TaskExecutionResult) -> str:
    if result.success:
        return "complete"
    if result.capped:
        return "incomplete - attempt cap reached"
    return "incomplete"


def render_commit_message(item: WorkItem, result: TaskExecutionResult) -> str:
    verification = "\n".join(f"- {record.command}: {record.status}" for record in result.verification)
    return (
        f"{item.jira_key}: {item.title}\n\n"
        f"Status: {work_status(result)}\n\n"
        f"Work completed:\n{result.summary}\n\n"
        f"Tests and verification:\n{verification or '- No verification recorded'}\n\n"
        f"Known issues:\n{result.blocker or '- None recorded'}\n\n"
        f"Manual testing:\n{result.manual_steps or 'Review the changed workflow manually.'}"
    )


def render_pr_body(item: WorkItem, candidate: JiraCandidate, result: TaskExecutionResult) -> str:
    verification = "\n".join(f"- `{record.command}`: {record.status}" for record in result.verification)
    return (
        f"{PR_MARKER_PREFIX}{item.jira_key} -->\n"
        f"## Jira\n{candidate.key}: {candidate.summary}\n\n"
        f"## Status\n{work_status(result)}\n\n"
        f"## Work completed\n{result.summary}\n\n"
        f"## Verification\n{verification or '- No verification recorded'}\n\n"
        f"## Known issues\n{result.blocker or '- None recorded'}\n\n"
        f"## Manual testing\n{result.manual_steps or manual_testing_steps(candidate)}\n"
    )


def render_review_response(result: TaskExecutionResult) -> str:
    verification = "\n".join(f"- `{record.command}`: {record.status}" for record in result.verification)
    lead = (
        "Addressed the actionable review feedback and pushed a follow-up commit."
        if result.success
        else "Pushed the latest review-feedback work after reaching the attempt cap."
    )
    return "\n\n".join(
        [
            lead,
            f"Status: {work_status(result)}",
            f"Verification:\n{verification or '- No verification recorded'}",
            f"Known issues:\n{result.blocker or '- None recorded'}",
        ]
    )


def render_jira_pr_comment(pr_url: str, result: TaskExecutionResult) -> str:
    verification = "\n".join(f"- {record.command}: {record.status}" for record in result.verification)
    return "\n\n".join(
        [
            f"Opened PR: {pr_url}",
            f"Status: {work_status(result)}",
            f"Verification:\n{verification or '- No verification recorded'}",
            f"Known issues:\n{result.blocker or '- None recorded'}",
        ]
    )


def parse_pr_number(url: str) -> int | None:
    match = re.search(r"/pull/(\d+)", url)
    return int(match.group(1)) if match else None


def new_actionable_comments(pr_payload: dict, item: WorkItem) -> list[dict]:
    processed = {comment.comment_id for comment in item.processed_review_comments}
    comments: list[dict] = []
    for comment in pr_payload.get("comments") or []:
        comment_id = str(comment.get("id") or comment.get("databaseId") or comment.get("url") or "")
        body = str(comment.get("body") or "").strip()
        if not comment_id or comment_id in processed or not body:
            continue
        if is_actionable_review_comment(body):
            comments.append({"id": comment_id, "body": body})
    for review in pr_payload.get("reviews") or []:
        review_id = str(review.get("id") or review.get("databaseId") or "")
        body = str(review.get("body") or "").strip()
        state = str(review.get("state") or "").upper()
        if not review_id or review_id in processed or not body:
            continue
        if state in {"CHANGES_REQUESTED", "COMMENTED"} and is_actionable_review_comment(body):
            comments.append({"id": review_id, "body": body})
    return comments


def summarize_status_checks(pr_payload: dict) -> str:
    checks = pr_payload.get("statusCheckRollup") or []
    if not isinstance(checks, list):
        return ""
    lines: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        name = str(
            check.get("name")
            or check.get("context")
            or check.get("workflowName")
            or check.get("title")
            or "unnamed check"
        )
        status = str(check.get("status") or check.get("state") or "").lower()
        conclusion = str(check.get("conclusion") or "").lower()
        details = str(check.get("detailsUrl") or check.get("targetUrl") or check.get("url") or "")
        if conclusion in {"success", "skipped", "neutral"}:
            continue
        if not conclusion and status in {"success", "completed"}:
            continue
        state = conclusion or status or "unknown"
        if state in {"", "expected"}:
            continue
        suffix = f" ({details})" if details else ""
        lines.append(f"- {name}: {state}{suffix}")
    return "\n".join(lines[:10])


def is_actionable_review_comment(body: str) -> bool:
    lowered = body.lower()
    ambiguous = ("what do you think", "maybe", "consider whether", "could we discuss")
    if any(phrase in lowered for phrase in ambiguous):
        return False
    actionable = ("please", "fix", "change", "rename", "add", "remove", "update", "failing", "bug")
    return any(word in lowered for word in actionable)


def format_work_items(items: list[WorkItem]) -> str:
    if not items:
        return "No work-loop items found."
    lines = []
    for item in items:
        pr = f" PR #{item.pr_number}" if item.pr_number is not None else ""
        lines.append(f"{item.jira_key} [{item.state}]{pr} {item.branch_name} - {item.title}")
    return "\n".join(lines)


def format_work_loop_jobs(jobs: list[WorkLoopJob]) -> str:
    if not jobs:
        return "No work-loop jobs found."
    lines = []
    for job in jobs:
        pid = f" pid:{job.pid}" if job.pid else ""
        lines.append(f"{job.job_id} [{job.state}]{pid} {job.mode} - {job.message or 'no message'}")
    return "\n".join(lines)


def format_work_item_status(item: WorkItem | None) -> str:
    if item is None:
        return "No work-loop item found."
    verification = "\n".join(f"- {record.command}: {record.status}" for record in item.verification)
    comments = "\n".join(f"- {comment.comment_id}: {comment.action}" for comment in item.processed_review_comments)
    return "\n".join(
        [
            f"Ticket: {item.jira_key}",
            f"Title: {item.title}",
            f"State: {item.state}",
            f"Branch: {item.branch_name or '<none>'}",
            f"Workspace: {item.workspace_path or '<none>'}",
            f"PR: {item.pr_url or '<none>'}",
            f"Blocker: {item.blocker or '<none>'}",
            "Verification:",
            verification or "- <none>",
            "Processed review comments:",
            comments or "- <none>",
        ]
    )
