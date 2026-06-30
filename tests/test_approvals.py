import os

import pytest

from app.approvals import (
    ApprovalRequestStore,
    approval_arguments_hash,
    approval_request_id,
    format_approval_detail,
    format_approval_review,
    format_approval_review_option,
    format_approval_status,
)


def test_approval_request_store_creates_stable_pending_request(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))

    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        reason="dependency changes need approval",
        run_id="run-123",
        matched_subject="command",
        matched_pattern="npm install*",
        granted_effects=("command_write", "image_management"),
    )
    repeated = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        reason="dependency changes need approval",
    )

    assert request.id == repeated.id
    assert request.status == "pending"
    assert request.scope == "once"
    assert request.run_id == "run-123"
    assert request.matched_subject == "command"
    assert request.matched_pattern == "npm install*"
    assert request.granted_effects == ("command_write", "image_management")
    assert len(store.list("session-a")) == 1


def test_approval_request_store_approves_and_consumes_exact_call_after_mark(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
    )

    store.approve("session-a", request.id)
    consumed = store.consume_approved(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
    )
    second = store.consume_approved(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
    )

    assert consumed is not None
    assert consumed.id == request.id
    assert second is not None
    assert second.id == request.id
    assert store.get("session-a", request.id).status == "approved"

    store.mark_used("session-a", request.id)

    third = store.consume_approved(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
    )

    assert third is None
    assert store.get("session-a", request.id).status == "used"


def test_approval_request_store_reopens_when_required_effects_expand(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "python -m pytest", "network_access": True},
        granted_effects=("command_read",),
    )

    store.approve("session-a", request.id)
    consumed = store.consume_approved(
        "session-a",
        tool_name="run_command",
        arguments={"command": "python -m pytest", "network_access": True},
        required_effects=("command_read", "network"),
    )
    assert consumed is None
    reopened = store.get("session-a", request.id)
    assert reopened is not None
    assert reopened.status == "pending"
    assert reopened.granted_effects == ("command_read", "network")

    expanded = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "python -m pytest", "network_access": True},
        granted_effects=("command_read", "network"),
    )
    assert expanded.id == request.id
    assert expanded.status == "pending"
    assert expanded.granted_effects == ("command_read", "network")


def test_approval_request_store_consumes_across_continuation_runs(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        run_id="run-original",
        granted_effects=("command_write",),
    )

    store.approve("session-a", request.id)
    consumed = store.consume_approved(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        required_effects=("command_write",),
    )

    assert consumed is not None
    assert consumed.id == request.id
    assert consumed.run_id == "run-original"


def test_approval_request_store_lists_all_pending_requests(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    first = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
    )
    second = store.request(
        "session-b",
        tool_name="run_command",
        arguments={"command": "npm install is-even"},
    )
    store.deny("session-b", second.id)

    pending = store.list_all(status="pending")

    assert [request.id for request in pending] == [first.id]


def test_run_command_approval_request_expands_required_effects(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    command_request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        granted_effects=("command_write",),
    )
    network_request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        granted_effects=("command_write", "network"),
    )

    assert network_request.id == command_request.id
    assert network_request.granted_effects == ("command_write", "network")
    assert len(store.list("session-a")) == 1


def test_approval_request_store_rejects_unknown_approval_id(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))

    with pytest.raises(KeyError):
        store.approve("session-a", "apr-missing")


def test_approval_hash_and_id_are_stable():
    first_hash = approval_arguments_hash("read_file", {"path": "README.md"})
    second_hash = approval_arguments_hash("read_file", {"path": "README.md"})

    assert first_hash == second_hash
    assert approval_request_id("session", "read_file", first_hash).startswith("apr-")


def test_run_command_approval_hash_ignores_operational_display_arguments():
    first_hash = approval_arguments_hash(
        "run_command",
        {
            "command": "npm install left-pad",
            "cwd": ".",
            "max_output_chars": 20000,
            "network_access": True,
            "timeout_seconds": 120,
        },
    )
    second_hash = approval_arguments_hash(
        "run_command",
        {
            "command": "npm install left-pad",
            "cwd": ".",
            "max_output_chars": 60000,
            "network_access": False,
            "timeout_seconds": 600,
        },
    )
    default_cwd_hash = approval_arguments_hash(
        "run_command",
        {"command": "npm install left-pad"},
    )
    changed_command_hash = approval_arguments_hash(
        "run_command",
        {
            "command": "npm install is-odd",
            "cwd": ".",
            "max_output_chars": 20000,
            "network_access": True,
            "timeout_seconds": 120,
        },
    )

    assert first_hash == second_hash
    assert first_hash == default_cwd_hash
    assert changed_command_hash != first_hash


def test_run_command_approval_consumes_with_changed_output_limits(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={
            "command": "npm install left-pad",
            "cwd": ".",
            "max_output_chars": 20000,
            "network_access": True,
            "timeout_seconds": 120,
        },
        granted_effects=("command_write", "network"),
    )

    store.approve("session-a", request.id)
    consumed = store.consume_approved(
        "session-a",
        tool_name="run_command",
        arguments={
            "command": "npm install left-pad",
            "cwd": ".",
            "max_output_chars": 60000,
            "network_access": True,
            "timeout_seconds": 600,
        },
        required_effects=("command_write", "network"),
    )

    assert consumed is not None
    assert consumed.id == request.id


def test_run_command_approval_consumes_with_default_cwd_variation(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        granted_effects=("command_write",),
    )

    store.approve("session-a", request.id)
    consumed = store.consume_approved(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad", "cwd": "."},
        required_effects=("command_write",),
    )

    assert consumed is not None
    assert consumed.id == request.id


def test_run_command_repeated_request_does_not_downgrade_granted_effects(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={
            "command": "npm install left-pad",
            "cwd": ".",
            "network_access": True,
        },
        granted_effects=("command_write", "network"),
    )
    repeated = store.request(
        "session-a",
        tool_name="run_command",
        arguments={
            "command": "npm install left-pad",
            "cwd": ".",
            "network_access": False,
        },
        granted_effects=("command_write",),
    )

    assert repeated.id == request.id
    assert repeated.granted_effects == ("command_write", "network")
    assert len(store.list("session-a")) == 1


def test_approval_formatters_show_status_and_detail(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        reason="dependency changes need approval",
        run_id="run-123",
        matched_subject="command",
        matched_pattern="npm install*",
        granted_effects=("command_write",),
    )

    status = format_approval_status(store, "session-a")
    detail = format_approval_detail(store, "session-a", request.id)

    assert request.id in status
    assert "command:npm install*" in status
    assert "Use /approval review" in status
    assert f"Approval: {request.id}" in detail
    assert "Tool: run_command" in detail
    assert "Scope: once" in detail
    assert "Requested action: ask" in detail
    assert "Matched rule: command:npm install*" in detail
    assert "Run: run-123" in detail
    assert "Granted effects: command_write" in detail
    assert "Expiry: none" in detail
    assert "Arguments hash:" in detail
    assert "\"command\": \"npm install left-pad\"" in detail


def test_approval_review_formatter_shows_numbered_exact_call_options(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))
    request = store.request(
        "session-a",
        tool_name="run_command",
        arguments={"command": "npm install left-pad"},
        reason="dependency changes need approval",
        run_id="run-123",
        granted_effects=("network", "command_write"),
    )

    review = format_approval_review(store, "session-a")
    option = format_approval_review_option(request)

    assert "Approval review:" in review
    assert f"1. {request.id}: run_command" in review
    assert "Actions: approve, deny, detail, skip, quit." in review
    assert "run:run-123" in option
    assert "effects:command_write,network" in option
    assert "args:npm install left-pad" in option
