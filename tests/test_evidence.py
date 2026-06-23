import os

import pytest

from app.goal_ledger import GoalLedgerStore
from app.run_trace import RunTraceStore
from app.tools.base import ACTIVE_TOOL_CALL_ID_STATE_KEY, ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY, Tool
from app.tools.evidence import EvidenceMiddleware
from app.tools.middleware import MiddlewareChain


class StubRunCommandTool(Tool):
    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return "Stub command"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"command": {"type": "string"}}}

    async def execute(self, **kwargs) -> str:
        return "exit code 0\nok"


class StubTool(Tool):
    def __init__(self, name: str, result: str = "ok"):
        self._name = name
        self.result = result

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Stub {self._name}"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return self.result


@pytest.mark.asyncio
async def test_evidence_middleware_records_verification_trace_and_goal(temp_dir):
    trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = trace_store.start_run("session-a")
    tool_started_event = recorder.append("tool.started", {
        "name": "run_command",
        "summary": "run_command command=pytest",
    })
    shared_state = {
        "trace_recorder": recorder,
        ACTIVE_TOOL_CALL_ID_STATE_KEY: "call-test-1",
        ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY: tool_started_event.event_id,
    }
    goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
    goal_store.start("session-a", "Run verification")
    chain = MiddlewareChain([
        EvidenceMiddleware(
            shared_state=shared_state,
            goal_store=goal_store,
            session_key="session-a",
        ),
    ])

    result = await chain.run(StubRunCommandTool(), {"command": "pytest"})
    recorder.finish("complete", stop_reason="test")

    assert result.startswith("exit code 0")
    events = trace_store.load_events("session-a", recorder.run_id)
    event_names = [event.event for event in events]
    assert "verification.recorded" in event_names
    assert "ledger.updated" in event_names
    verification_event = next(event for event in events if event.event == "verification.recorded")
    ledger_event = next(event for event in events if event.event == "ledger.updated")
    assert verification_event.data["tool_call_id"] == "call-test-1"
    assert verification_event.data["tool_trace_event_id"] == tool_started_event.event_id
    assert ledger_event.data["evidence_id"].startswith("cmd-")
    assert ledger_event.data["ledger_path"].endswith("session-a.ledger.json")
    assert ledger_event.data["related_trace_event_id"] == verification_event.event_id
    assert ledger_event.data["tool_call_id"] == "call-test-1"
    assert ledger_event.data["tool_trace_event_id"] == tool_started_event.event_id
    summary = trace_store.load_summary("session-a", recorder.run_id)
    assert summary.verification[0]["command"] == "pytest"
    ledger = goal_store.load("session-a")
    assert ledger.commands[0].command == "pytest"
    assert ledger.verification[0].id == ledger_event.data["evidence_id"]
    assert ledger.verification[0].trace_event_id == verification_event.event_id
    assert ledger.verification[0].tool_call_id == "call-test-1"
    assert ledger.verification[0].tool_trace_event_id == tool_started_event.event_id
    assert ledger.verification[0].status == "passed"


@pytest.mark.asyncio
async def test_evidence_middleware_records_non_verification_command_only_in_ledger(temp_dir):
    trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = trace_store.start_run("session-a")
    tool_started_event = recorder.append("tool.started", {
        "name": "run_command",
        "summary": "run_command command=git status",
    })
    shared_state = {
        "trace_recorder": recorder,
        ACTIVE_TOOL_CALL_ID_STATE_KEY: "call-command-1",
        ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY: tool_started_event.event_id,
    }
    goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
    goal_store.start("session-a", "Inspect command")
    chain = MiddlewareChain([
        EvidenceMiddleware(
            shared_state=shared_state,
            goal_store=goal_store,
            session_key="session-a",
        ),
    ])

    await chain.run(StubRunCommandTool(), {"command": "git status"})
    recorder.finish("complete", stop_reason="test")

    event_names = [event.event for event in trace_store.load_events("session-a", recorder.run_id)]
    assert "verification.recorded" not in event_names
    assert "ledger.updated" in event_names
    ledger_event = next(
        event
        for event in trace_store.load_events("session-a", recorder.run_id)
        if event.event == "ledger.updated"
    )
    assert ledger_event.data["evidence_id"].startswith("cmd-")
    assert ledger_event.data["related_trace_event_id"] is None
    assert ledger_event.data["tool_call_id"] == "call-command-1"
    assert ledger_event.data["tool_trace_event_id"] == tool_started_event.event_id
    ledger = goal_store.load("session-a")
    assert ledger.commands[0].command == "git status"
    assert ledger.commands[0].id == ledger_event.data["evidence_id"]
    assert ledger.commands[0].tool_call_id == "call-command-1"
    assert ledger.commands[0].tool_trace_event_id == tool_started_event.event_id
    assert ledger.verification == []


@pytest.mark.asyncio
async def test_evidence_middleware_records_read_and_search_origin_events(temp_dir):
    trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = trace_store.start_run("session-a")
    read_event = recorder.append("tool.started", {
        "name": "read_file",
        "summary": "read_file path=app.py",
    })
    shared_state = {
        "trace_recorder": recorder,
        ACTIVE_TOOL_CALL_ID_STATE_KEY: "call-read-1",
        ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY: read_event.event_id,
    }
    goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
    goal_store.start("session-a", "Inspect files")
    chain = MiddlewareChain([
        EvidenceMiddleware(
            shared_state=shared_state,
            goal_store=goal_store,
            session_key="session-a",
        ),
    ])

    await chain.run(StubTool("read_file", "print('hello')\n"), {"path": "app.py"})
    search_event = recorder.append("tool.started", {
        "name": "grep_search",
        "summary": "grep_search path=. query=hello",
    })
    shared_state[ACTIVE_TOOL_CALL_ID_STATE_KEY] = "call-search-1"
    shared_state[ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY] = search_event.event_id
    await chain.run(StubTool("grep_search", "app.py:1:1: hello"), {
        "path": ".",
        "query": "hello",
    })
    recorder.finish("complete", stop_reason="test")

    events = trace_store.load_events("session-a", recorder.run_id)
    ledger_events = [event for event in events if event.event == "ledger.updated"]
    assert [event.data["kind"] for event in ledger_events] == ["read", "search"]
    assert ledger_events[0].data["tool_call_id"] == "call-read-1"
    assert ledger_events[0].data["related_trace_event_id"] == read_event.event_id
    assert ledger_events[1].data["tool_call_id"] == "call-search-1"
    assert ledger_events[1].data["related_trace_event_id"] == search_event.event_id

    ledger = goal_store.load("session-a")
    assert [item.kind for item in ledger.inspected_files] == ["read", "search"]
    assert ledger.inspected_files[0].path == "app.py"
    assert ledger.inspected_files[0].tool_call_id == "call-read-1"
    assert ledger.inspected_files[0].trace_event_id == read_event.event_id
    assert ledger.inspected_files[1].path == "."
    assert ledger.inspected_files[1].tool_call_id == "call-search-1"
    assert ledger.inspected_files[1].trace_event_id == search_event.event_id


@pytest.mark.asyncio
async def test_evidence_middleware_skips_failed_read_evidence(temp_dir):
    trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = trace_store.start_run("session-a")
    shared_state = {"trace_recorder": recorder}
    goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
    goal_store.start("session-a", "Inspect files")
    chain = MiddlewareChain([
        EvidenceMiddleware(
            shared_state=shared_state,
            goal_store=goal_store,
            session_key="session-a",
        ),
    ])

    await chain.run(StubTool("read_file", "Error: file not found"), {"path": "missing.py"})
    recorder.finish("complete", stop_reason="test")

    events = trace_store.load_events("session-a", recorder.run_id)
    assert "ledger.updated" not in [event.event for event in events]
    ledger = goal_store.load("session-a")
    assert ledger.inspected_files == []
