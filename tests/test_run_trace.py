import json
import os

import pytest

from app.run_trace import RunTraceEvent, RunTraceStore


def test_run_trace_store_writes_events_and_summary(temp_dir):
    store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = store.start_run("session-a", goal_id="goal-1", metadata={"model": "gpt-test"})

    recorder.append("llm.ended", {"model": "gpt-test"})
    recorder.append("tool.started", {"name": "run_command", "command": "pytest"})
    recorder.append("tool.denied", {"name": "write_file"})
    summary = recorder.finish("stopped", stop_reason="done")

    events = store.load_events("session-a", recorder.run_id)
    assert [event.event for event in events] == [
        "run.started",
        "llm.ended",
        "tool.started",
        "tool.denied",
        "run.ended",
    ]
    assert os.path.exists(summary.trace_path)

    loaded = store.load_summary("session-a", recorder.run_id)
    assert loaded is not None
    assert loaded.run_id == recorder.run_id
    assert loaded.goal_id == "goal-1"
    assert loaded.status == "stopped"
    assert loaded.stop_reason == "done"
    assert loaded.model == "gpt-test"
    assert loaded.tool_calls == 1
    assert loaded.denied_tool_calls == 1
    assert loaded.commands_run == ["pytest"]
    assert summary.to_dict() == loaded.to_dict()


def test_run_trace_event_redacts_secret_fields(temp_dir):
    store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = store.start_run("session-a")
    recorder.append("tool.started", {
        "name": "webfetch",
        "api_key": "sk-secretsecretsecret",
        "nested": {"authorization": "Bearer abcdefghijklmnop"},
    })

    events = store.load_events("session-a", recorder.run_id)
    event = events[-1]
    assert event.data["api_key"] == "[REDACTED]"
    assert event.data["nested"]["authorization"] == "[REDACTED]"


def test_run_trace_load_tolerates_trailing_malformed_line(temp_dir):
    store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = store.start_run("session-a")
    recorder.append("tool.started", {"name": "read_file"})
    path = store.trace_path("session-a", recorder.run_id)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("{not-json")

    events = store.load_events("session-a", recorder.run_id)
    assert [event.event for event in events] == ["run.started", "tool.started"]


def test_run_trace_load_raises_for_middle_malformed_line(temp_dir):
    store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    recorder = store.start_run("session-a")
    path = store.trace_path("session-a", recorder.run_id)
    first = RunTraceEvent(event="one", run_id=recorder.run_id, session_key="session-a")
    second = RunTraceEvent(event="two", run_id=recorder.run_id, session_key="session-a")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(first.to_dict()) + "\n")
        handle.write("{not-json\n")
        handle.write(json.dumps(second.to_dict()) + "\n")

    with pytest.raises(json.JSONDecodeError):
        store.load_events("session-a", recorder.run_id)


def test_run_trace_store_lists_latest_summary(temp_dir):
    store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
    first = store.start_run("session-a", metadata={"model": "old"})
    first.finish("complete", stop_reason="old")
    second = store.start_run("session-a", metadata={"model": "new"})
    second.summary.started_at = first.summary.started_at + 1
    second.finish("stopped", stop_reason="new")

    summaries = store.list_summaries("session-a")
    latest = store.latest_summary("session-a")

    assert [summary.run_id for summary in summaries] == [first.run_id, second.run_id]
    assert latest.run_id == second.run_id
    assert latest.stop_reason == "new"
