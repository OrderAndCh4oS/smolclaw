import os

from typer.testing import CliRunner

from app.work_loop import (
    CommandResult,
    WorkLoopControl,
    WorkLoopJobSupervisor,
    JiraCandidate,
    TaskExecutionResult,
    VerificationRecord,
    WorkItem,
    WorkLoopConfig,
    WorkLoopLedger,
    WorkLoopRunner,
    branch_name_for_ticket,
    build_backlog_jql,
    eligible_candidates,
    format_work_item_status,
    new_actionable_comments,
    summarize_status_checks,
)
from app.workspace import WorkspaceContext


class FakeCommandRunner:
    def __init__(self):
        self.calls = []

    def run(self, args, *, cwd=None, input_text=None, timeout=600):
        self.calls.append((list(args), cwd, input_text, timeout))
        if args[:3] == ["git", "worktree", "add"]:
            path = args[-2] if "-b" in args else args[-2]
            os.makedirs(path, exist_ok=True)
            return CommandResult(args=list(args), returncode=0, stdout="worktree created\n")
        if args[:2] == ["git", "status"] and "--porcelain" in args:
            if cwd and os.path.exists(os.path.join(cwd, ".has_changes")):
                return CommandResult(args=list(args), returncode=0, stdout="M file.py\n")
            return CommandResult(args=list(args), returncode=0, stdout="")
        if args[:2] == ["git", "fetch"]:
            return CommandResult(args=list(args), returncode=0)
        if args[:2] == ["git", "rev-parse"]:
            return CommandResult(args=list(args), returncode=0, stdout="abc123\n")
        if args[:2] == ["git", "add"]:
            if cwd:
                open(os.path.join(cwd, ".has_changes"), "a").close()
            return CommandResult(args=list(args), returncode=0)
        if args[:2] == ["git", "commit"]:
            return CommandResult(args=list(args), returncode=0, stdout="[branch abc123] commit\n")
        if args[:2] == ["git", "push"]:
            return CommandResult(args=list(args), returncode=0)
        return CommandResult(args=list(args), returncode=0)


class FakeJira:
    def __init__(self, candidates):
        self.candidates = candidates
        self.transitions = []
        self.comments = []

    def auth_ok(self):
        return True

    def search_backlog(self, config, *, limit=50):
        return self.candidates

    def view(self, key):
        return next(candidate for candidate in self.candidates if candidate.key == key)

    def transition(self, key, status):
        self.transitions.append((key, status))

    def comment(self, key, body):
        self.comments.append((key, body))


class FakeGitHub:
    def __init__(self):
        self.comments = []
        self.payloads = {}

    def auth_ok(self):
        return True

    def create_pr(self, item, body, *, base_branch, label=""):
        self.last_body = body
        return 42, "https://github.com/example/repo/pull/42"

    def view_pr(self, pr_number):
        return self.payloads.get(pr_number, {})

    def comment(self, pr_number, body):
        self.comments.append((pr_number, body))


class FakeTaskExecutor:
    def __init__(self, success=True):
        self.calls = []
        self.success = success

    def execute(self, item, candidate, config, *, review_feedback=""):
        self.calls.append((item.jira_key, review_feedback))
        if self.success:
            return TaskExecutionResult(
                success=True,
                summary="Changed behavior and added tests.",
                verification=[VerificationRecord(command="python -m pytest", status="passed")],
                manual_steps="Open the affected screen and verify the new behavior.",
            )
        return TaskExecutionResult(
            success=False,
            summary="Reached attempt cap before verification passed.",
            blocker="tests still fail",
            capped=True,
            attempts=5,
        )


class FailingVerificationRunner(FakeCommandRunner):
    def run(self, args, *, cwd=None, input_text=None, timeout=600):
        if args[:4] == [os.sys.executable, "-m", "cli.main", "run"]:
            self.calls.append((list(args), cwd, input_text, timeout))
            return CommandResult(args=list(args), returncode=0, stdout='{"status":"active"}\n')
        if args == ["python", "-m", "pytest"]:
            self.calls.append((list(args), cwd, input_text, timeout))
            return CommandResult(args=list(args), returncode=1, stderr="tests failed\n")
        return super().run(args, cwd=cwd, input_text=input_text, timeout=timeout)


def test_work_loop_ledger_lists_and_formats_status(temp_dir):
    ledger = WorkLoopLedger(os.path.join(temp_dir, "ledger"))
    item = ledger.save(
        WorkItem(
            jira_key="APP-123",
            title="Fix totals",
            state="open-pr",
            branch_name="APP-123-fix-totals",
            pr_number=7,
            pr_url="https://github.com/example/repo/pull/7",
        )
    )

    assert ledger.load("APP-123").title == "Fix totals"
    assert ledger.list("open-pr")[0].jira_key == "APP-123"
    status = format_work_item_status(item)
    assert "Ticket: APP-123" in status
    assert "PR: https://github.com/example/repo/pull/7" in status


def test_jira_backlog_jql_and_candidate_filtering():
    config = WorkLoopConfig(project="APP", required_label="agent-ready")
    assert 'project = APP' in build_backlog_jql(config)
    assert 'labels = "agent-ready"' in build_backlog_jql(config)

    accepted = JiraCandidate(
        key="APP-1",
        summary="Small fix",
        issue_type="Bug",
        status="Open",
        labels=["agent-ready"],
    )
    blocked = JiraCandidate(
        key="APP-2",
        summary="Blocked",
        issue_type="Bug",
        status="Open",
        labels=["agent-ready", "blocked"],
    )
    assigned = JiraCandidate(
        key="APP-3",
        summary="Assigned",
        issue_type="Task",
        status="Open",
        assignee="Alex",
        labels=["agent-ready"],
    )

    assert eligible_candidates([blocked, assigned, accepted], config) == [accepted]


def test_branch_name_uses_ticket_key_and_slug():
    assert branch_name_for_ticket("APP-12", "Fix checkout total!") == "APP-12-fix-checkout-total"


def test_run_tasks_creates_pr_and_records_ticket(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    config = WorkLoopConfig(project="APP", verification_commands=["python -m pytest"])
    candidate = JiraCandidate(
        key="APP-1",
        summary="Fix checkout total",
        issue_type="Bug",
        status="Open",
        priority="High",
        description="Totals are rounded incorrectly.",
    )
    jira = FakeJira([candidate])
    github = FakeGitHub()
    executor = FakeTaskExecutor()
    runner = WorkLoopRunner(
        workspace=workspace,
        config=config,
        command_runner=FakeCommandRunner(),
        jira=jira,
        github=github,
        task_executor=executor,
    )

    items = runner.run_tasks(limit=1)

    item = items[0]
    assert item.state == "open-pr"
    assert item.pr_number == 42
    assert item.commits == ["abc123"]
    assert jira.transitions == [("APP-1", "In Progress"), ("APP-1", "In Review")]
    assert jira.comments[0][0] == "APP-1"
    assert "Opened PR: https://github.com/example/repo/pull/42" in jira.comments[0][1]
    assert "Status: complete" in jira.comments[0][1]
    assert not os.path.exists(item.workspace_path)


def test_run_tasks_opens_pr_with_incomplete_status_after_attempt_cap(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    config = WorkLoopConfig(project="APP", verification_commands=["python -m pytest"])
    candidate = JiraCandidate(
        key="APP-2",
        summary="Partially fix checkout total",
        issue_type="Bug",
        status="Open",
        description="Totals are rounded incorrectly.",
    )
    jira = FakeJira([candidate])
    github = FakeGitHub()
    runner = WorkLoopRunner(
        workspace=workspace,
        config=config,
        command_runner=FakeCommandRunner(),
        jira=jira,
        github=github,
        task_executor=FakeTaskExecutor(success=False),
    )

    item = runner.run_tasks(limit=1)[0]

    assert item.state == "open-pr"
    assert item.pr_number == 42
    assert item.blocker == "tests still fail"
    assert "## Status\nincomplete - attempt cap reached" in github.last_body
    assert "Known issues" in github.last_body
    assert "tests still fail" in jira.comments[0][1]


def test_cli_agent_executor_caps_inner_loop_at_five_attempts(temp_dir):
    from app.work_loop import CliAgentTaskExecutor

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    runner = FailingVerificationRunner()
    executor = CliAgentTaskExecutor(runner)
    item = WorkItem(jira_key="APP-5", title="Fix retries", workspace_path=workspace.root_dir)
    candidate = JiraCandidate(key="APP-5", summary="Fix retries")
    config = WorkLoopConfig(project="APP", verification_commands=["python -m pytest"], repair_attempts=99)

    result = executor.execute(item, candidate, config)

    agent_runs = [call for call in runner.calls if call[0][:4] == [os.sys.executable, "-m", "cli.main", "run"]]
    assert len(agent_runs) == 5
    assert result.success is False
    assert result.capped is True
    assert result.attempts == 5


def test_run_reviews_processes_only_new_actionable_comments(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    config = WorkLoopConfig(project="APP", verification_commands=["python -m pytest"])
    ledger = WorkLoopLedger.for_workspace(workspace)
    ledger.save(
        WorkItem(
            jira_key="APP-9",
            title="Fix review issue",
            state="open-pr",
            branch_name="APP-9-fix-review-issue",
            pr_number=9,
            workspace_path=os.path.join(temp_dir, ".smolclaw", "work-loop", "runs", "run", "run_1"),
        )
    )
    github = FakeGitHub()
    github.payloads[9] = {
        "comments": [
            {"id": "c1", "body": "Please add a regression test for this case."},
            {"id": "c2", "body": "Maybe we should discuss the naming."},
        ],
        "reviews": [],
    }
    executor = FakeTaskExecutor()
    runner = WorkLoopRunner(
        workspace=workspace,
        config=config,
        command_runner=FakeCommandRunner(),
        jira=FakeJira([]),
        github=github,
        ledger=ledger,
        task_executor=executor,
    )

    items = runner.run_reviews()

    assert items[0].processed_review_comments[0].comment_id == "c1"
    assert executor.calls == [("APP-9", "Review comments:\nPlease add a regression test for this case.")]
    assert github.comments[0][0] == 9


def test_run_reviews_uses_failing_github_checks_without_comments(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    config = WorkLoopConfig(project="APP", verification_commands=["python -m pytest"])
    ledger = WorkLoopLedger.for_workspace(workspace)
    ledger.save(
        WorkItem(
            jira_key="APP-10",
            title="Fix CI issue",
            state="open-pr",
            branch_name="APP-10-fix-ci-issue",
            pr_number=10,
            workspace_path=os.path.join(temp_dir, ".smolclaw", "work-loop", "runs", "ci", "run_1"),
        )
    )
    github = FakeGitHub()
    github.payloads[10] = {
        "comments": [],
        "reviews": [],
        "statusCheckRollup": [
            {
                "name": "test",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "detailsUrl": "https://github.com/example/repo/actions/runs/1",
            }
        ],
    }
    executor = FakeTaskExecutor()
    runner = WorkLoopRunner(
        workspace=workspace,
        config=config,
        command_runner=FakeCommandRunner(),
        jira=FakeJira([]),
        github=github,
        ledger=ledger,
        task_executor=executor,
    )

    items = runner.run_reviews()

    assert items[0].jira_key == "APP-10"
    assert "GitHub checks:" in executor.calls[0][1]
    assert "test: failure" in executor.calls[0][1]
    assert github.comments[0][0] == 10


def test_new_actionable_comments_skips_processed_and_ambiguous():
    item = WorkItem(jira_key="APP-1", title="Fix")
    item.processed_review_comments.append(type("Processed", (), {"comment_id": "old"})())
    payload = {
        "comments": [
            {"id": "old", "body": "Please fix this."},
            {"id": "new", "body": "Please rename this helper."},
            {"id": "ambiguous", "body": "Maybe we should discuss this shape."},
        ],
    }

    assert new_actionable_comments(payload, item) == [{"id": "new", "body": "Please rename this helper."}]


def test_summarize_status_checks_returns_non_passing_checks_only():
    payload = {
        "statusCheckRollup": [
            {"name": "unit", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "lint", "status": "COMPLETED", "conclusion": "FAILURE", "detailsUrl": "https://ci/lint"},
            {"context": "deploy", "state": "PENDING", "targetUrl": "https://ci/deploy"},
        ]
    }

    summary = summarize_status_checks(payload)

    assert "unit" not in summary
    assert "- lint: failure (https://ci/lint)" in summary
    assert "- deploy: pending (https://ci/deploy)" in summary


def test_cli_work_loop_list_uses_ledger(temp_dir):
    from cli.main import app

    ledger = WorkLoopLedger.for_workspace(WorkspaceContext.from_root(temp_dir).ensure_dirs())
    ledger.save(WorkItem(jira_key="APP-4", title="Add empty state", state="blocked"))

    result = CliRunner().invoke(app, ["work-loop", "list", "--workspace", temp_dir, "--state", "blocked"])

    assert result.exit_code == 0
    assert "APP-4 [blocked]" in result.stdout


def test_in_app_work_loop_slash_list_and_status_use_ledger(temp_dir):
    from cli.main import _resolve_work_loop_command

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    ledger = WorkLoopLedger.for_workspace(workspace)
    ledger.save(
        WorkItem(
            jira_key="APP-8",
            title="Fix dashboard copy",
            state="open-pr",
            branch_name="APP-8-fix-dashboard-copy",
            pr_number=18,
        )
    )

    listed = _resolve_work_loop_command(workspace, "list --state open-pr")
    by_ticket = _resolve_work_loop_command(workspace, "status APP-8")
    by_pr = _resolve_work_loop_command(workspace, "status 18")

    assert "APP-8 [open-pr] PR #18" in listed
    assert "Ticket: APP-8" in by_ticket
    assert "Ticket: APP-8" in by_pr


def test_in_app_work_loop_stop_pause_resume_control_files(temp_dir):
    from cli.main import _resolve_work_loop_command

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    control = WorkLoopControl.for_workspace(workspace)

    stopped = _resolve_work_loop_command(workspace, "stop budget reached")
    paused = _resolve_work_loop_command(workspace, "pause waiting")
    state = _resolve_work_loop_command(workspace, "state")
    resumed = _resolve_work_loop_command(workspace, "resume")

    assert "Work-loop stop requested for all: budget reached" == stopped
    assert "Work-loop pause requested for all: waiting" == paused
    assert state == "Work-loop state: stopped"
    assert resumed == "Work-loop resumed for all; stop and pause files cleared."
    assert control.status() == "running"


def test_in_app_work_loop_tasks_starts_background_job(temp_dir, monkeypatch):
    from cli.main import _resolve_work_loop_command

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

    class FakeSupervisor:
        @classmethod
        def for_workspace(cls, workspace):
            return cls()

        def start(self, mode, worker_args):
            assert mode == "tasks"
            assert "--project" in worker_args
            return type(
                "Job",
                (),
                {"job_id": "job-123", "state": "running", "pid": 99},
            )()

    monkeypatch.setattr("cli.main.WorkLoopJobSupervisor", FakeSupervisor)

    result = _resolve_work_loop_command(workspace, "tasks --project APP --limit 1")

    assert result == "Started work-loop job job-123 [running] pid:99 mode:tasks"


def test_work_loop_job_supervisor_start_records_job_metadata(temp_dir, monkeypatch):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

    class FakePopen:
        def __init__(self, command, **kwargs):
            self.command = command
            self.kwargs = kwargs
            self.pid = 12345

        def poll(self):
            return None

    monkeypatch.setattr("app.work_loop.subprocess.Popen", FakePopen)
    monkeypatch.setattr("app.work_loop.os.getpgid", lambda pid: pid)

    supervisor = WorkLoopJobSupervisor.for_workspace(workspace)
    job = supervisor.start("reviews", ["--workspace", temp_dir])
    loaded = supervisor.store.load(job.job_id)

    assert loaded.state == "running"
    assert loaded.pid == 12345
    assert loaded.mode == "reviews"
    assert "work-loop" in loaded.command
    assert "worker" in loaded.command
