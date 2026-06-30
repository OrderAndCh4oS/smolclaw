import os
import subprocess

import pytest
from typer.testing import CliRunner

from app.work_loop import (
    CodingLifecycleRunner,
    CommandResult,
    GitOperations,
    GitHubAdapter,
    InternalReviewRecord,
    KanboardAdapter,
    ProcessedReviewComment,
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
    build_task_source_adapter,
    eligible_candidates,
    format_work_item_status,
    new_actionable_comments,
    resolve_work_loop_config_path,
    summarize_status_checks,
)
from app.coding_lifecycle import LifecycleSourceRef, ReviewFeedbackRef
from app.agent_config import AgentConfigLoader
from app.runtime_config import RuntimeAdapterConfig
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

    def run(self, args, *, cwd=None, input_text=None, timeout=600, network_access=False):
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
        if args[:4] == ["git", "show-ref", "--verify", "--quiet"]:
            return CommandResult(args=list(args), returncode=1)
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


class FakeKanboardClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        value = self.responses.get(method)
        if callable(value):
            return value(params)
        return value


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

    def review(self, item, candidate, config, result, profile=None):
        self.calls.append((item.jira_key, candidate.key, result.summary, profile.name if profile else ""))
        return self.record


class FailingVerificationRunner(FakeCommandRunner):
    def run(self, args, *, cwd=None, input_text=None, timeout=600, network_access=False):
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


def test_work_loop_ledger_uses_workspace_lifecycle_path(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

    ledger = WorkLoopLedger.for_workspace(workspace)

    assert ledger.root_dir == os.path.realpath(workspace.paths.work_loop_dir)
    assert workspace.paths.work_loop_dir.endswith(os.path.join(".smolclaw", "work-loop"))


def test_work_item_exports_lifecycle_work():
    item = WorkItem(
        jira_key="APP-123",
        title="Fix totals",
        state="open-pr",
        task_source_type="jira",
        jira_url="https://jira.example.invalid/browse/APP-123",
        branch_name="APP-123-fix-totals",
        pr_number=42,
        pr_url="https://github.com/example/repo/pull/42",
        commits=["abc123"],
    )

    lifecycle = item.to_lifecycle_work()

    assert lifecycle.source_ref.provider == "jira"
    assert lifecycle.source_ref.key == "APP-123"
    assert lifecycle.phase == "open-pr"
    assert lifecycle.branch_name == "APP-123-fix-totals"
    assert {ref.kind for ref in lifecycle.publication_refs} == {"commit", "pull_request"}


def test_work_item_migrates_source_fields_with_legacy_compatibility():
    item = WorkItem.from_dict({
        "schema_version": 1,
        "source_key": "TASK-9",
        "source_provider": "linear",
        "source_url": "https://linear.example/TASK-9",
        "title": "Provider neutral item",
    })

    payload = item.to_dict()

    assert item.source_key == "TASK-9"
    assert item.jira_key == "TASK-9"
    assert item.source_provider == "linear"
    assert payload["source_key"] == "TASK-9"
    assert payload["jira_key"] == "TASK-9"
    assert payload["source_provider"] == "linear"
    assert payload["task_source_type"] == "linear"


def test_jira_adapter_exposes_discovery_contract():
    candidate = JiraCandidate(key="APP-1", summary="Fix totals", description="Round correctly.")
    adapter = FakeJira([candidate])

    # FakeJira deliberately implements the old protocol only; this documents
    # that the real adapter owns lifecycle discovery conversion.
    lifecycle = candidate.to_lifecycle_work()

    assert lifecycle.source_ref == LifecycleSourceRef(
        kind="discovery",
        provider="jira",
        key="APP-1",
        url="",
        metadata={},
    )
    assert lifecycle.title == "Fix totals"


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


def test_run_tasks_resets_stale_ledger_state_for_backlog_retry(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    config = WorkLoopConfig(project="APP", verification_commands=["python -m pytest"])
    old_workspace = os.path.join(temp_dir, ".smolclaw", "work-loop", "runs", "old", "run_1")
    ledger = WorkLoopLedger.for_workspace(workspace)
    ledger.save(
        WorkItem(
            jira_key="APP-4",
            title="Old title",
            state="blocked",
            run_id="run-old",
            task_source_type="jira",
            jira_url="https://jira.example.invalid/browse/APP-4",
            workspace_path=old_workspace,
            branch_name="APP-4-old-title",
            base_commit="old-base",
            pr_number=99,
            pr_url="https://github.com/example/repo/pull/99",
            commits=["old-sha"],
            verification=[VerificationRecord(command="old", status="failed")],
            processed_review_comments=[ProcessedReviewComment(comment_id="c1", action="fixed")],
            internal_review=InternalReviewRecord(status="error"),
            blocker="old blocker",
        )
    )
    candidate = JiraCandidate(
        key="APP-4",
        summary="Retry from backlog",
        issue_type="Bug",
        status="Open",
        description="Retry without stale metadata.",
    )
    runner = WorkLoopRunner(
        workspace=workspace,
        config=config,
        command_runner=FakeCommandRunner(),
        jira=FakeJira([candidate]),
        github=FakeGitHub(),
        ledger=ledger,
        task_executor=FakeTaskExecutor(),
    )

    item = runner.run_tasks(limit=1)[0]

    assert item.state == "open-pr"
    assert item.run_id != "run-old"
    assert item.title == "Retry from backlog"
    assert item.branch_name == "APP-4-retry-from-backlog"
    assert item.workspace_path != old_workspace
    assert item.base_commit == "abc123"
    assert item.pr_number == 42
    assert item.pr_url == "https://github.com/example/repo/pull/42"
    assert item.commits == ["abc123"]
    assert [(record.command, record.status) for record in item.verification] == [("python -m pytest", "passed")]
    assert item.processed_review_comments == []
    assert item.internal_review.status == "passed"
    assert item.blocker == ""


def test_git_create_worktree_uses_retry_branch_when_branch_exists(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    calls = []

    class BranchRunner:
        def run(self, args, *, cwd=None, timeout=600, **kwargs):
            calls.append((list(args), cwd))
            if args[:4] == ["git", "show-ref", "--verify", "--quiet"]:
                branch_ref = args[4]
                exists = branch_ref == "refs/heads/APP-4-retry-from-backlog"
                return CommandResult(args=list(args), returncode=0 if exists else 1)
            if args[:3] == ["git", "worktree", "add"]:
                os.makedirs(args[-2], exist_ok=True)
                return CommandResult(args=list(args), returncode=0, stdout="worktree created\n")
            if args[:2] == ["git", "rev-parse"]:
                return CommandResult(args=list(args), returncode=0, stdout="new-base\n")
            return CommandResult(args=list(args), returncode=0)

    item = WorkItem(
        jira_key="APP-4",
        title="Retry from backlog",
        branch_name="APP-4-retry-from-backlog",
        workspace_path=os.path.join(temp_dir, "run_1"),
    )

    GitOperations(BranchRunner(), workspace).create_worktree(item, WorkLoopConfig(project="APP"))

    worktree_call = next(args for args, _cwd in calls if args[:3] == ["git", "worktree", "add"])
    assert item.branch_name.startswith("APP-4-retry-from-backlog-")
    assert item.branch_name != "APP-4-retry-from-backlog"
    assert worktree_call[3:5] == ["-b", item.branch_name]
    assert item.base_commit == "new-base"


def test_coding_lifecycle_runner_aliases_work_loop_runner():
    assert CodingLifecycleRunner is WorkLoopRunner


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


def test_cli_work_loop_config_uses_runtime_adapter_defaults(temp_dir):
    from cli.main import _load_work_loop_config

    config = _load_work_loop_config(
        "",
        adapter_config=RuntimeAdapterConfig.from_dict({
            "adapters": {
                "task_source": {"default": {"provider": "jira"}},
                "code_review": {"default": {"provider": "github"}},
            },
        }),
    )

    assert config.task_source_type == "jira"
    assert config.code_review_type == "github"


def test_cli_work_loop_config_file_overrides_runtime_adapter_defaults(temp_dir):
    from cli.main import _load_work_loop_config

    config_path = os.path.join(temp_dir, "smolclaw-loop.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join([
                "task_source:",
                "  type: jira",
                "code_review:",
                "  type: github",
            ])
        )

    config = _load_work_loop_config(
        config_path,
        adapter_config=RuntimeAdapterConfig.from_dict({
            "adapters": {
                "task_source": {"default": {"provider": "unsupported-task"}},
                "code_review": {"default": {"provider": "unsupported-review"}},
            },
        }),
    )

    assert config.task_source_type == "jira"
    assert config.code_review_type == "github"


def test_cli_work_loop_config_provider_overrides_runtime_adapter_defaults(temp_dir):
    from cli.main import _load_work_loop_config

    config_path = os.path.join(temp_dir, ".work-loop.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join([
                "task_source:",
                "  provider: local",
                "  project: text-editor",
            ])
        )

    config = _load_work_loop_config(
        config_path,
        adapter_config=RuntimeAdapterConfig.from_dict({
            "adapters": {
                "task_source": {"default": {"provider": "jira"}},
            },
        }),
    )

    assert config.task_source_type == "local"
    assert config.project == "text-editor"


def test_work_loop_config_loads_kanboard_task_source(temp_dir):
    config_path = os.path.join(temp_dir, ".work-loop.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join([
                "task_source:",
                "  type: kanboard",
                "  url: http://localhost:8080",
                "  username: jsonrpc",
                "  token_env: KANBOARD_API_TOKEN",
                "  token_file: .smolclaw/kanboard/api-token",
                "  user_id: 1",
                "  project: SMOL",
                "  project_identifier: SMOL",
                "  eligible_statuses: [Backlog]",
                "  in_progress_status: Work in progress",
                "  review_status: Review",
                "  required_label: agent-ready",
                "code_review:",
                "  type: github",
            ])
        )

    config = WorkLoopConfig.load(config_path)

    assert config.task_source_type == "kanboard"
    assert config.kanboard_url == "http://localhost:8080"
    assert config.kanboard_username == "jsonrpc"
    assert config.kanboard_token_env == "KANBOARD_API_TOKEN"
    assert config.kanboard_token_file == os.path.join(temp_dir, ".smolclaw", "kanboard", "api-token")
    assert config.kanboard_user_id == 1
    assert config.project == "SMOL"
    assert config.kanboard_project_identifier == "SMOL"
    assert config.eligible_statuses == ["Backlog"]
    assert config.in_progress_status == "Work in progress"
    assert config.review_status == "Review"
    assert config.required_label == "agent-ready"


def test_work_loop_config_accepts_local_provider_alias(temp_dir):
    config_path = os.path.join(temp_dir, ".work-loop.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join([
                "task_source:",
                "  provider: local",
                "  project: text-editor",
            ])
        )

    config = WorkLoopConfig.load(config_path)

    assert config.task_source_type == "local"
    assert config.project == "text-editor"


def test_resolve_work_loop_config_prefers_workspace_mount_config(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    mounted_config = os.path.join(temp_dir, ".work-loop.yaml")
    legacy_config = os.path.join(temp_dir, "smolclaw.jira-loop.yaml")
    with open(mounted_config, "w", encoding="utf-8") as handle:
        handle.write("task_source:\n  provider: local\n")
    with open(legacy_config, "w", encoding="utf-8") as handle:
        handle.write("task_source:\n  type: jira\n")

    assert resolve_work_loop_config_path("", workspace=workspace) == os.path.realpath(mounted_config)
    assert resolve_work_loop_config_path("smolclaw.jira-loop.yaml", workspace=workspace) == os.path.realpath(mounted_config)
    assert resolve_work_loop_config_path(".work-loop.yaml", workspace=workspace) == os.path.realpath(mounted_config)


def test_build_task_source_adapter_supports_kanboard():
    config = WorkLoopConfig(
        task_source_type="kanboard",
        project="1",
        kanboard_url="http://localhost:8080",
        kanboard_token="secret",
    )

    adapter = build_task_source_adapter(config, FakeCommandRunner())

    assert isinstance(adapter, KanboardAdapter)


def test_build_task_source_adapter_supports_local_provider_alias():
    config = WorkLoopConfig(
        task_source_type="local",
        project="text-editor",
        kanboard_url="http://localhost:8080",
        kanboard_token="secret",
    )

    adapter = build_task_source_adapter(config, FakeCommandRunner())

    assert isinstance(adapter, KanboardAdapter)


def test_kanboard_adapter_search_view_transition_and_comment():
    columns = [
        {"id": "1", "title": "Backlog"},
        {"id": "2", "title": "Work in progress"},
        {"id": "3", "title": "Review"},
    ]
    task = {
        "id": "42",
        "title": "Fix totals",
        "description": "Round correctly.",
        "project_id": "7",
        "column_id": "1",
        "owner_id": "0",
        "priority": "2",
        "swimlane_id": "1",
        "position": "4",
        "url": "http://localhost:8080/?controller=task&action=show&task_id=42&project_id=7",
    }
    client = FakeKanboardClient({
        "getAllProjects": [],
        "getProjectByIdentifier": {"id": "7"},
        "getColumns": columns,
        "getAllTasks": [task],
        "getTask": task,
        "getTaskTags": {"1": "agent-ready"},
        "moveTaskPosition": True,
        "createComment": 11,
    })
    config = WorkLoopConfig(
        task_source_type="kanboard",
        project="SMOL",
        eligible_statuses=["Backlog"],
        required_label="agent-ready",
        in_progress_status="Work in progress",
        review_status="Review",
        kanboard_url="http://localhost:8080",
        kanboard_token="secret",
    )
    adapter = KanboardAdapter(config, client=client)

    assert adapter.auth_ok() is True
    candidates = adapter.search_backlog(config)
    eligible = eligible_candidates(candidates, config)
    viewed = adapter.view("KB-42")
    adapter.transition("KB-42", "Work in progress")
    adapter.comment("KB-42", "Opened PR: https://github.com/example/repo/pull/42")

    assert [candidate.key for candidate in candidates] == ["KB-42"]
    assert eligible == candidates
    assert candidates[0].source_type == "kanboard"
    assert candidates[0].status == "Backlog"
    assert candidates[0].labels == ["agent-ready"]
    assert viewed.description == "Round correctly."
    assert ("getAllTasks", {"project_id": 7, "status_id": 1}) in client.calls
    assert ("getTaskTags", {"task_id": 42}) in client.calls
    assert (
        "moveTaskPosition",
        {
            "project_id": 7,
            "task_id": 42,
            "column_id": 2,
            "position": 1,
            "swimlane_id": 1,
        },
    ) in client.calls
    assert (
        "createComment",
        {
            "task_id": 42,
            "user_id": 1,
            "content": "Opened PR: https://github.com/example/repo/pull/42",
        },
    ) in client.calls


def test_kanboard_adapter_create_task_with_tags_and_column():
    columns = [
        {"id": "1", "title": "Backlog"},
        {"id": "2", "title": "Work in progress"},
    ]
    created_task = {
        "id": "43",
        "title": "Add Kanboard seed task",
        "description": "Create the task from SmolClaw.",
        "project_id": "7",
        "column_id": "1",
        "owner_id": "0",
        "tags": ["agent-ready", "cli"],
    }
    client = FakeKanboardClient({
        "getProjectByIdentifier": {"id": "7"},
        "getColumns": columns,
        "createTask": 43,
        "getTask": created_task,
        "getTaskTags": {"1": "agent-ready", "2": "cli"},
    })
    config = WorkLoopConfig(
        task_source_type="kanboard",
        project="SMOL",
        eligible_statuses=["Backlog"],
        required_label="agent-ready",
        kanboard_url="http://localhost:8080",
        kanboard_token="secret",
    )
    adapter = KanboardAdapter(config, client=client)

    candidate = adapter.create_task(
        config,
        title="Add Kanboard seed task",
        description="Create the task from SmolClaw.",
        labels=["cli", "agent-ready"],
    )

    assert candidate.key == "KB-43"
    assert candidate.labels == ["agent-ready", "cli"]
    assert (
        "createTask",
        {
            "project_id": 7,
            "title": "Add Kanboard seed task",
            "description": "Create the task from SmolClaw.",
            "tags": ["cli", "agent-ready"],
            "column_id": 1,
        },
    ) in client.calls


def test_kanboard_adapter_uses_environment_project():
    client = FakeKanboardClient({
        "getProjectByIdentifier": {"id": "7"},
        "getColumns": [],
        "getAllTasks": [],
    })
    config = WorkLoopConfig(
        task_source_type="kanboard",
        kanboard_url="http://localhost:8080",
        kanboard_token="secret",
    )
    adapter = KanboardAdapter(
        config,
        client=client,
        environ={"KANBOARD_PROJECT": "SMOL"},
    )

    assert adapter.search_backlog(config) == []
    assert ("getProjectByIdentifier", {"identifier": "SMOL"}) in client.calls


def test_kanboard_adapter_reads_token_file(temp_dir):
    token_path = os.path.join(temp_dir, "api-token")
    with open(token_path, "w", encoding="utf-8") as handle:
        handle.write("secret-token\n")

    config = WorkLoopConfig(
        task_source_type="kanboard",
        kanboard_url="http://localhost:8080",
        kanboard_token_file=token_path,
    )
    adapter = KanboardAdapter(config, http_client_factory=object)

    assert adapter.client.token == "secret-token"


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
    assert {"work_loop_list_tasks", "work_loop_view_task"}.issubset(config.tools)
    assert not {
        "work_loop_create_task",
        "work_loop_move_task",
        "work_loop_comment_task",
        "work_loop_close_task",
    }.intersection(config.tools)


def test_default_chat_agent_knows_work_loop_task_tools():
    config = AgentConfigLoader.load("agents.yaml")["default"]

    assert {
        "work_loop_list_tasks",
        "work_loop_view_task",
        "work_loop_create_task",
        "work_loop_move_task",
        "work_loop_comment_task",
        "work_loop_close_task",
    }.issubset(config.tools)


def test_researcher_agent_can_read_work_loop_tasks():
    config = AgentConfigLoader.load("agents.yaml")["researcher"]

    assert {"work_loop_list_tasks", "work_loop_view_task"}.issubset(config.tools)
    assert "work_loop_create_task" not in config.tools


def test_ticket_writer_agent_can_create_requirement_tickets():
    config = AgentConfigLoader.load("agents.yaml")["ticket_writer"]

    assert config.permission_mode == "plan"
    assert config.bootstrap_path == "agents/ticket_writer.md"
    assert {"filesystem", "command", "memory"} == set(config.capabilities)
    assert {
        "read_file",
        "grep_search",
        "work_loop_list_tasks",
        "work_loop_view_task",
        "work_loop_create_task",
        "work_loop_comment_task",
    }.issubset(config.tools)
    assert not {
        "write_file",
        "edit_file",
        "apply_patch",
        "run_command",
        "git_add",
        "git_commit",
        "git_push",
        "work_loop_move_task",
        "work_loop_close_task",
    }.intersection(config.tools)


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


def test_internal_reviewer_passes_profile_review_model(temp_dir):
    from app.work_loop import InternalReviewRunner

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    runner = FakeCommandRunner()
    reviewer = InternalReviewRunner(runner)
    item = WorkItem(jira_key="APP-14", title="Review model", workspace_path=workspace.root_dir)
    candidate = JiraCandidate(key="APP-14", summary="Review model")
    config = WorkLoopConfig(project="APP")
    profile = TaskExecutionProfile(
        name="claude-review",
        models=WorkLoopModels(review_model="claude-sonnet-4-20250514"),
    )

    record = reviewer.review(
        item,
        candidate,
        config,
        TaskExecutionResult(success=True, summary="Done."),
        profile=profile,
    )

    agent_run = next(call for call in runner.calls if call[0][:4] == [os.sys.executable, "-m", "cli.main", "run"])
    assert "--agent" in agent_run[0]
    assert agent_run[0][agent_run[0].index("--agent") + 1] == "reviewer"
    assert "--model" in agent_run[0]
    assert agent_run[0][agent_run[0].index("--model") + 1] == "claude-sonnet-4-20250514"
    assert record.status == "passed"


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


def test_github_adapter_exposes_followup_contract(temp_dir):
    runner = FakeCommandRunner()
    adapter = FakeGitHub()
    adapter.payloads[9] = {
        "comments": [
            {"id": "c1", "body": "Please add a regression test for this case."},
        ],
        "reviews": [],
    }
    item = WorkItem(
        jira_key="APP-9",
        title="Fix review issue",
        state="open-pr",
        pr_number=9,
        processed_review_comments=[],
    )
    from app.work_loop import GitHubAdapter

    github = GitHubAdapter(runner)
    github.view_pr = adapter.view_pr
    github.comment = adapter.comment

    followups = github.discover_followups(WorkLoopConfig(project="APP"), open_items=[item])
    response = github.respond(
        ReviewFeedbackRef(provider="github", pr_number=9, comment_id="c1", body="Please add a regression test."),
        "Addressed in latest push.",
    )

    assert followups[0].phase == "responding-to-review"
    assert followups[0].review_feedback[0].comment_id == "c1"
    assert response.ok is True
    assert adapter.comments == [(9, "Addressed in latest push.")]


def test_github_adapter_creates_missing_pr_label_before_pr(temp_dir):
    calls = []

    class LabelRunner:
        def run(self, args, *, cwd=None, timeout=600, **kwargs):
            calls.append((list(args), cwd))
            if args[:3] == ["gh", "label", "list"]:
                return CommandResult(args=list(args), returncode=0, stdout="[]")
            if args[:3] == ["gh", "label", "create"]:
                return CommandResult(args=list(args), returncode=0, stdout="")
            if args[:3] == ["gh", "pr", "create"]:
                return CommandResult(args=list(args), returncode=0, stdout="https://github.com/example/repo/pull/42\n")
            return CommandResult(args=list(args), returncode=0)

    item = WorkItem(
        jira_key="KB-14",
        title="Future language support",
        branch_name="KB-14-future-language-support",
        workspace_path=temp_dir,
    )
    adapter = GitHubAdapter(LabelRunner())

    pr_number, pr_url = adapter.create_pr(item, "body", base_branch="main", label="agent-owned")

    assert pr_number == 42
    assert pr_url == "https://github.com/example/repo/pull/42"
    assert calls[0][0] == ["gh", "label", "list", "--search", "agent-owned", "--json", "name"]
    assert calls[1][0][:4] == ["gh", "label", "create", "agent-owned"]
    assert "--label" in calls[2][0]
    assert "agent-owned" in calls[2][0]


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


def test_in_app_work_loop_tasks_starts_background_job(temp_dir):
    from cli.main import CliDependencies, _resolve_work_loop_command

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

    deps = CliDependencies(work_loop_supervisor_factory=FakeSupervisor.for_workspace)
    result = _resolve_work_loop_command(workspace, "tasks --project APP --limit 1", deps=deps)

    assert result == "Started work-loop job job-123 [running] pid:99 mode:tasks"


def test_in_app_work_loop_start_uses_configured_project(temp_dir):
    from cli.main import CliDependencies, _resolve_work_loop_command

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

    class FakeSupervisor:
        @classmethod
        def for_workspace(cls, workspace):
            return cls()

        def start(self, mode, worker_args):
            assert mode == "run"
            assert "--project" not in worker_args
            assert "--limit" in worker_args
            return type(
                "Job",
                (),
                {"job_id": "job-456", "state": "running", "pid": 101},
            )()

    deps = CliDependencies(work_loop_supervisor_factory=FakeSupervisor.for_workspace)
    result = _resolve_work_loop_command(workspace, "start --limit 3", deps=deps)

    assert result == "Started work-loop job job-456 [running] pid:101 mode:run"


def test_in_app_work_loop_create_task_uses_runner(temp_dir):
    from cli.main import CliDependencies, _resolve_work_loop_command

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    calls = []

    class FakeRunner:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create_task(self, **kwargs):
            calls.append(kwargs)
            return JiraCandidate(
                key="KB-99",
                summary=kwargs["title"],
                status="Backlog",
                labels=kwargs["labels"],
                source_type="kanboard",
                url="http://localhost:8080/?controller=task&action=show&task_id=99&project_id=7",
            )

    deps = CliDependencies(work_loop_runner_factory=lambda **kwargs: FakeRunner(**kwargs))
    result = _resolve_work_loop_command(
        workspace,
        'create-task "Seed Kanboard task" --project SMOL --description "Try the loop" --label cli --status Backlog',
        deps=deps,
    )

    assert "Created task KB-99: Seed Kanboard task" in result
    assert "Status: Backlog" in result
    assert "Labels: cli" in result
    assert calls == [
        {
            "title": "Seed Kanboard task",
            "description": "Try the loop",
            "labels": ["cli"],
            "status": "Backlog",
        }
    ]


def test_cli_work_loop_create_task_command_uses_runner(temp_dir):
    from cli.main import app, override_cli_dependencies

    class FakeRunner:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create_task(self, **kwargs):
            return JiraCandidate(
                key="KB-100",
                summary=kwargs["title"],
                status="Backlog",
                labels=kwargs["labels"],
                source_type="kanboard",
            )

    with override_cli_dependencies(work_loop_runner_factory=lambda **kwargs: FakeRunner(**kwargs)):
        result = CliRunner().invoke(
            app,
            [
                "work-loop",
                "create-task",
                "Seed from CLI",
                "--workspace",
                temp_dir,
                "--project",
                "SMOL",
                "--label",
                "agent-ready",
            ],
        )

    assert result.exit_code == 0
    assert "Created task KB-100: Seed from CLI" in result.stdout
    assert "Labels: agent-ready" in result.stdout


@pytest.mark.asyncio
async def test_agent_work_loop_create_task_tool_uses_runner(temp_dir):
    from app.tools.base import ToolRuntimeContext
    from app.tools.work_loop import WorkLoopCreateTaskTool

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    calls = []

    class FakeRunner:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create_task(self, **kwargs):
            calls.append(kwargs)
            return JiraCandidate(
                key="KB-101",
                summary=kwargs["title"],
                status="Backlog",
                labels=kwargs["labels"],
                source_type="kanboard",
            )

    tool = WorkLoopCreateTaskTool(runner_factory=lambda **kwargs: FakeRunner(**kwargs)).bind(
        ToolRuntimeContext(workspace=workspace)
    )

    result = await tool.execute(
        title="Seed via agent",
        project="SMOL",
        description="Created from terminal chat.",
        labels=["agent-ready"],
        status="Backlog",
    )

    assert "Created task KB-101: Seed via agent" in result
    assert "Labels: agent-ready" in result
    assert calls == [
        {
            "title": "Seed via agent",
            "description": "Created from terminal chat.",
            "labels": ["agent-ready"],
            "status": "Backlog",
        }
    ]
    policy = tool.get_call_policy({})
    assert policy.requires_approval is True
    assert "network" in policy.effects


@pytest.mark.asyncio
async def test_agent_work_loop_create_task_uses_configured_project(temp_dir):
    from app.tools.base import ToolRuntimeContext
    from app.tools.work_loop import WorkLoopCreateTaskTool

    config_path = os.path.join(temp_dir, ".work-loop.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join([
                "task_source:",
                "  provider: local",
                "  project: SMOL",
            ])
        )
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    created_configs = []

    class FakeRunner:
        def __init__(self, **kwargs):
            self.config = kwargs["config"]
            created_configs.append(self.config)

        def create_task(self, **kwargs):
            return JiraCandidate(
                key="KB-102",
                summary=kwargs["title"],
                status="Backlog",
                labels=kwargs["labels"],
                source_type="kanboard",
            )

    tool = WorkLoopCreateTaskTool(runner_factory=lambda **kwargs: FakeRunner(**kwargs)).bind(
        ToolRuntimeContext(workspace=workspace)
    )

    result = await tool.execute(
        title="Seed via configured defaults",
        labels=["agent-ready"],
    )

    assert "Created task KB-102: Seed via configured defaults" in result
    assert created_configs[0].task_source_type == "local"
    assert created_configs[0].project == "SMOL"
    assert "project" not in tool.parameters["required"]
    assert "config_path" not in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_agent_work_loop_list_tasks_infers_kanboard_from_environment(temp_dir, monkeypatch):
    from app.tools.base import ToolRuntimeContext
    from app.tools.work_loop import WorkLoopListTasksTool

    monkeypatch.setenv("KANBOARD_URL", "http://localhost:8080")
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    created_configs = []

    class FakeTaskSource:
        def search_backlog(self, config, *, limit=50):
            created_configs.append(config)
            return [
                JiraCandidate(
                    key="KB-203",
                    summary="Environment-backed task",
                    status="Backlog",
                    source_type="kanboard",
                )
            ]

    class FakeRunner:
        def __init__(self, **kwargs):
            self.config = kwargs["config"]
            self.task_source = FakeTaskSource()

    tool = WorkLoopListTasksTool(runner_factory=lambda **kwargs: FakeRunner(**kwargs)).bind(
        ToolRuntimeContext(workspace=workspace)
    )

    result = await tool.execute(limit=1)

    assert "KB-203: Environment-backed task" in result
    assert created_configs[0].task_source_type == "kanboard"
    assert "required" not in tool.parameters
    assert "config_path" not in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_agent_work_loop_task_tools_use_configured_provider(temp_dir):
    from app.tools.base import ToolRuntimeContext
    from app.tools.work_loop import (
        WorkLoopCloseTaskTool,
        WorkLoopCommentTaskTool,
        WorkLoopListTasksTool,
        WorkLoopMoveTaskTool,
        WorkLoopViewTaskTool,
    )

    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

    class FakeTaskSource:
        def __init__(self):
            self.transitions = []
            self.comments = []
            self.candidate = JiraCandidate(
                key="KB-201",
                summary="Provider-backed task",
                description="Task body",
                status="Backlog",
                labels=["agent-ready"],
                source_type="kanboard",
                url="http://kanboard.local/task/201",
            )

        def search_backlog(self, config, *, limit=50):
            assert config.project == "SMOL"
            assert limit == 3
            return [self.candidate]

        def view(self, key):
            assert key == "KB-201"
            return self.candidate

        def transition(self, key, status):
            self.transitions.append((key, status))

        def comment(self, key, body):
            self.comments.append((key, body))

    task_source = FakeTaskSource()

    class FakeRunner:
        def __init__(self, **kwargs):
            self.config = kwargs["config"]
            self.task_source = task_source

    runtime = ToolRuntimeContext(workspace=workspace)
    factory = lambda **kwargs: FakeRunner(**kwargs)
    list_tool = WorkLoopListTasksTool(runner_factory=factory).bind(runtime)
    view_tool = WorkLoopViewTaskTool(runner_factory=factory).bind(runtime)
    move_tool = WorkLoopMoveTaskTool(runner_factory=factory).bind(runtime)
    comment_tool = WorkLoopCommentTaskTool(runner_factory=factory).bind(runtime)
    close_tool = WorkLoopCloseTaskTool(runner_factory=factory).bind(runtime)

    listed = await list_tool.execute(project="SMOL", limit=3)
    viewed = await view_tool.execute(key="KB-201")
    moved = await move_tool.execute(key="KB-201", status="Review")
    commented = await comment_tool.execute(key="KB-201", body="Taking this.")
    closed = await close_tool.execute(key="KB-201")

    assert "KB-201: Provider-backed task" in listed
    assert "Status: Backlog" in viewed
    assert "Task body" in viewed
    assert "Moved task:" in moved
    assert commented == "Added comment to task KB-201."
    assert closed == "Closed task KB-201."
    assert task_source.transitions == [("KB-201", "Review"), ("KB-201", "closed")]
    assert task_source.comments == [("KB-201", "Taking this.")]
    assert list_tool.get_call_policy({}).requires_approval is False
    assert view_tool.get_call_policy({}).requires_approval is False
    for tool in (move_tool, comment_tool, close_tool):
        assert tool.get_call_policy({}).requires_approval is True


def test_work_loop_job_supervisor_start_records_job_metadata(temp_dir):
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

    supervisor = WorkLoopJobSupervisor(workspace, process_factory=FakePopen)
    job = supervisor.start("reviews", ["--workspace", temp_dir])
    loaded = supervisor.store.load(job.job_id)

    assert loaded.state == "running"
    assert loaded.pid == 12345
    assert loaded.mode == "reviews"
    assert "work-loop" in loaded.command
    assert "worker" in loaded.command
    assert captured[0].kwargs["env"]["SMOLCLAW_WORK_LOOP_JOB_ID"] == job.job_id


def test_subprocess_runner_keeps_worker_children_in_job_process_group():
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

    from app.command_runner import SubprocessCommandRunner

    result = SubprocessCommandRunner(
        process_factory=FakePopen,
        environ={"SMOLCLAW_WORK_LOOP_JOB_ID": "job-test"},
    ).run(["python", "--version"])

    assert result.ok
    assert captured[0].kwargs["start_new_session"] is False
    assert captured[0]._smolclaw_own_process_group is False
