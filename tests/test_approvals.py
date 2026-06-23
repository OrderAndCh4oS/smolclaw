import os

import pytest

from app.approvals import (
    ApprovalRequestStore,
    approval_arguments_hash,
    approval_request_id,
    format_approval_detail,
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
    assert len(store.list("session-a")) == 1


def test_approval_request_store_approves_and_consumes_exact_call(temp_dir):
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
    assert second is None
    assert store.get("session-a", request.id).status == "used"


def test_approval_request_store_rejects_unknown_approval_id(temp_dir):
    store = ApprovalRequestStore(os.path.join(temp_dir, "approvals"))

    with pytest.raises(KeyError):
        store.approve("session-a", "apr-missing")


def test_approval_hash_and_id_are_stable():
    first_hash = approval_arguments_hash("read_file", {"path": "README.md"})
    second_hash = approval_arguments_hash("read_file", {"path": "README.md"})

    assert first_hash == second_hash
    assert approval_request_id("session", "read_file", first_hash).startswith("apr-")


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
    )

    status = format_approval_status(store, "session-a")
    detail = format_approval_detail(store, "session-a", request.id)

    assert request.id in status
    assert "command:npm install*" in status
    assert "Use /approval detail" in status
    assert f"Approval: {request.id}" in detail
    assert "Tool: run_command" in detail
    assert "Scope: once" in detail
    assert "Requested action: ask" in detail
    assert "Matched rule: command:npm install*" in detail
    assert "Run: run-123" in detail
    assert "Expiry: none" in detail
    assert "Arguments hash:" in detail
    assert "\"command\": \"npm install left-pad\"" in detail
