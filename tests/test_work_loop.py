import os
import subprocess

from typer.testing import CliRunner

from app.work_loop import (
    CommandResult,
    InternalReviewRecord,
    RunWorkspaceManager,
    WorkLoopControl,
    WorkLoopJobSupervisor,
    JiraCandidate,
    TaskProfile,
    TaskProfileMatch,
    TaskExecutionProfile,
    WorkLoopModels,
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
from app.agent_config import AgentConfigLoader
from app.workspace import WorkspaceContext


def _run_git(args, cwd):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def _git_repo(temp_dir):
    repo = os.path.join(temp_dir, "repo")
    os.makedirs(repo, exist_ok=True)
    _run_git(["init"], repo)
    _run_git(["config", "user.email", "test@example.invalid"], repo)
    _run_git(["config", "user.name", "Test User"], repo)
    with open(os.path.join(repo, "app.py"), "w", encoding="utf-8") as handle:
        handle.write("print('base')\n")
    _run_git(["add", "app.py"], repo)
    _run_git(["commit", "-m", "initial"], repo)
    return repo


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

    def execute(self, item, candidate, config, *, review_feedback="", profile=None):
        self.calls.append((item.jira_key, review_feedback, profile.name if profile else ""))
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


class SequencedTaskExecutor:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, item, candidate, config, *, review_feedback="", profile=None):
        self.calls.append((item.jira_key, review_feedback, profile.name if profile else ""))
        return self.results.pop(0)


class FakeInternalReviewer:
    def __init__(self, record):
        self.record = record
        self.calls = []

    def review(self, item, candidate, config, result):
        self.calls.append((item.jira_key, candidate.key, result.summary))
        return self.record


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


def test_run_workspace_cleanup_removes_git_worktree_metadata(temp_dir):
    repo = _git_repo(temp_dir)
    workspace = WorkspaceContext.from_root(repo).ensure_dirs()
    item = WorkItem(
        jira_key="APP-7",
        title="Clean worktree",
        workspace_path=os.path.join(temp_dir, "work-loop-run"),
    )
    _run_git(["worktree", "add", "--detach", item.workspace_path, "HEAD"], repo)

    RunWorkspaceManager(workspace).cleanup(item)

    assert not os.path.exists(item.workspace_path)
    listed = _run_git(["worktree", "list", "--porcelain"], repo).stdout
    assert item.workspace_path not in listed


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
    assert "Internal review:\npassed" in jira.comments[0][1]
    assert "## Internal review\npassed" in github.last_body
    assert item.internal_review.status == "passed"
    assert not os.path.exists(item.workspace_path)


def test_run_tasks_persists_matching_execution_profile(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    config = WorkLoopConfig(
        project="APP",
        verification_commands=["python -m pytest"],
        task_profiles=[
            TaskProfile(
                name="small_bug",
                match=TaskProfileMatch(issue_types=["Bug"], labels=["small"]),
                execution=TaskExecutionProfile(
                    name="small_bug",
                    models=WorkLoopModels(
                        analysis_model="gpt-5.4-mini",
                        coding_model="gpt-5.4",
                        review_model="gpt-5.4-mini",
                        status_model="gpt-5.4-mini",
                    ),
                    inner_max_turns=7,
                    repair_attempts=2,
                ),
            )
        ],
    )
    candidate = JiraCandidate(
        key="APP-11",
        summary="Fix small bug",
        issue_type="Bug",
        status="Open",
        labels=["small"],
    )
    executor = FakeTaskExecutor()
    runner = WorkLoopRunner(
        workspace=workspace,
        config=config,
        command_runner=FakeCommandRunner(),
        jira=FakeJira([candidate]),
        github=FakeGitHub(),
        task_executor=executor,
    )

    item = runner.run_tasks(limit=1)[0]

    assert item.execution_profile["name"] == "small_bug"
    assert item.execution_profile["models"]["coding_model"] == "gpt-5.4"
    assert executor.calls[0] == ("APP-11", "", "small_bug")


def test_work_loop_config_loads_adapter_and_profile_rules(temp_dir):
    config_path = os.path.join(temp_dir, "smolclaw-loop.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    "task_source:",
                    "  type: jira",
                    "  project: APP",
                    "code_review:",
                    "  type: github",
                    "  label: agent-owned",
                    "defaults:",
                    "  models:",
                    "    analysis_model: gpt-5.4-mini",
                    "    coding_model: subagent",
                    "  inner_max_turns: 6",
                    "  repair_attempts: 4",
                    "internal_review:",
                    "  enabled: true",
                    "  reviewer_agent: reviewer",
                    "  repair_cycles: 1",
                    "task_profiles:",
                    "  - name: api_change",
                    "    match:",
                    "      labels: [api]",
                    "    models:",
                    "      coding_model: gpt-5.5",
                    "    inner_max_turns: 9",
                ]
            )
        )

    config = WorkLoopConfig.load(config_path)

    assert config.task_source_type == "jira"
    assert config.code_review_type == "github"
    assert config.project == "APP"
    assert config.github_label == "agent-owned"
    assert config.internal_review_enabled is True
    assert config.reviewer_agent == "reviewer"
    assert config.internal_review_repair_cycles == 1
    assert config.task_profiles[0].name == "api_change"
    assert config.task_profiles[0].execution.models.coding_model == "gpt-5.5"
    assert config.task_profiles[0].execution.inner_max_turns == 9


def test_reviewer_agent_is_read_only():
    config = AgentConfigLoader.load("agents.yaml")["reviewer"]

    blocked_tools = {
        "write_file",
        "edit_file",
        "apply_patch",
        "run_command",
        "git_add",
        "git_commit",
        "git_push",
        "git_checkout",
        "git_pull",
    }
    assert config.permission_mode == "plan"
    assert not blocked_tools.intersection(config.tools)
    assert {"read_file", "grep_search", "git_status", "git_diff"}.issubset(config.tools)


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


def test_internal_review_findings_trigger_one_repair_before_pr(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    config = WorkLoopConfig(project="APP", verification_commands=["python -m pytest"])
    candidate = JiraCandidate(
        key="APP-3",
        summary="Fix stale total",
        issue_type="Bug",
        status="Open",
        description="The total does not refresh after item removal.",
    )
    initial = TaskExecutionResult(
        success=True,
        summary="Updated total refresh logic.",
        verification=[VerificationRecord(command="python -m pytest", status="passed")],
        manual_steps="Remove an item and inspect the total.",
    )
    repaired = TaskExecutionResult(
        success=True,
        summary="Added missing removal regression test.",
        verification=[VerificationRecord(command="python -m pytest", status="passed")],
        manual_steps="Remove an item and inspect the total.",
    )
    executor = SequencedTaskExecutor([initial, repaired])
    reviewer = FakeInternalReviewer(InternalReviewRecord(
        status="findings",
        findings="Add a regression test for removing the final cart item.",
    ))
    jira = FakeJira([candidate])
    github = FakeGitHub()
    runner = WorkLoopRunner(
        workspace=workspace,
        config=config,
        command_runner=FakeCommandRunner(),
        jira=jira,
        github=github,
        task_executor=executor,
        internal_reviewer=reviewer,
    )

    item = runner.run_tasks(limit=1)[0]

    assert len(executor.calls) == 2
    assert executor.calls[0] == ("APP-3", "", "default")
    assert "Internal pre-PR review found actionable" in executor.calls[1][1]
    assert "final cart item" in executor.calls[1][1]
    assert item.internal_review.status == "findings"
    assert item.internal_review.repair_attempted is True
    assert len(item.verification) == 2
    assert "repair attempted" in github.last_body
    assert "final cart item" in github.last_body
    assert "Internal review:\nfindings - repair attempted" in jira.comments[0][1]


def test_internal_review_findings_do_not_block_pr_after_repair_cap(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    config = WorkLoopConfig(
        project="APP",
        verification_commands=["python -m pytest"],
        internal_review_repair_cycles=0,
    )
    candidate = JiraCandidate(key="APP-12", summary="Fix validation", issue_type="Bug", status="Open")
    executor = SequencedTaskExecutor([
        TaskExecutionResult(
            success=True,
            summary="Updated validation.",
            verification=[VerificationRecord(command="python -m pytest", status="passed")],
        )
    ])
    reviewer = FakeInternalReviewer(InternalReviewRecord(
        status="findings",
        findings="Add a boundary-case validation test.",
    ))
    github = FakeGitHub()
    runner = WorkLoopRunner(
        workspace=workspace,
        config=config,
        command_runner=FakeCommandRunner(),
        jira=FakeJira([candidate]),
        github=github,
        task_executor=executor,
        internal_reviewer=reviewer,
    )

    item = runner.run_tasks(limit=1)[0]

    assert item.state == "open-pr"
    assert len(executor.calls) == 1
    assert item.internal_review.repair_attempted is False
    assert "Add a boundary-case validation test." in github.last_body


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


def test_cli_agent_executor_passes_explicit_profile_coding_model(temp_dir):
    from app.work_loop import CliAgentTaskExecutor

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    runner = FakeCommandRunner()
    executor = CliAgentTaskExecutor(runner)
    item = WorkItem(jira_key="APP-6", title="Fix model", workspace_path=workspace.root_dir)
    candidate = JiraCandidate(key="APP-6", summary="Fix model")
    config = WorkLoopConfig(project="APP", verification_commands=[])
    profile = TaskExecutionProfile(
        name="explicit",
        models=WorkLoopModels(coding_model="gpt-5.4"),
        inner_max_turns=3,
        repair_attempts=0,
    )

    result = executor.execute(item, candidate, config, profile=profile)

    agent_run = next(call for call in runner.calls if call[0][:4] == [os.sys.executable, "-m", "cli.main", "run"])
    assert "--model" in agent_run[0]
    assert agent_run[0][agent_run[0].index("--model") + 1] == "gpt-5.4"
    assert agent_run[0][agent_run[0].index("--max-turns") + 1] == "3"
    assert result.success is True


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
    assert executor.calls == [("APP-9", "Review comments:\nPlease add a regression test for this case.", "default")]
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
    captured = []

    class FakePopen:
        def __init__(self, command, **kwargs):
            self.command = command
            self.kwargs = kwargs
            self.pid = 12345
            captured.append(self)

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
    assert captured[0].kwargs["env"]["SMOLCLAW_WORK_LOOP_JOB_ID"] == job.job_id


def test_subprocess_runner_keeps_worker_children_in_job_process_group(monkeypatch):
    captured = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.pid = 456
            self.returncode = 0
            captured.append(self)

        def communicate(self, input=None, timeout=None):
            return "ok\n", ""

    monkeypatch.setattr("app.work_loop.subprocess.Popen", FakePopen)
    monkeypatch.setenv("SMOLCLAW_WORK_LOOP_JOB_ID", "job-test")

    from app.work_loop import SubprocessCommandRunner

    result = SubprocessCommandRunner().run(["python", "--version"])

    assert result.ok
    assert captured[0].kwargs["start_new_session"] is False
    assert captured[0]._smolclaw_own_process_group is False
