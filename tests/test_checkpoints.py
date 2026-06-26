import base64
import json
import os

import pytest

from app.checkpoints import CheckpointStore, MAX_SNAPSHOT_BYTES
from app.goal_ledger import GoalLedgerStore
from app.run_trace import RunTraceStore
from app.tools.base import ACTIVE_TOOL_CALL_ID_STATE_KEY, ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY, TRACE_RECORDER_STATE_KEY
from app.tools.checkpointing import CheckpointMiddleware
from app.tools.filesystem import ApplyPatchTool, EditFileTool, WriteFileTool
from app.tools.middleware import MiddlewareChain
from app.workspace import WorkspaceContext


def _checkpoint_records(checkpoints_dir: str) -> list[dict]:
    records = []
    for name in sorted(os.listdir(checkpoints_dir)):
        if name.endswith(".json"):
            with open(os.path.join(checkpoints_dir, name), encoding="utf-8") as handle:
                records.append(json.load(handle))
    return records


class TestCheckpointMiddleware:
    @pytest.mark.asyncio
    async def test_records_created_file_checkpoint(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        checkpoints_dir = os.path.join(temp_dir, "stores", "checkpoints")
        store = CheckpointStore(checkpoints_dir)
        chain = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-a"),
        ])

        result = await chain.run(WriteFileTool(workspace=workspace), {
            "path": "new.txt",
            "content": "hello",
            "reason": "create file for test",
        })

        assert "Written" in result
        records = _checkpoint_records(checkpoints_dir)
        assert len(records) == 1
        record = records[0]
        changed_path = os.path.realpath(os.path.join(temp_dir, "new.txt"))
        assert record["tool_name"] == "write_file"
        assert record["session_key"] == "session-a"
        assert record["changed_paths"] == [changed_path]
        assert record["before"][changed_path]["exists"] is False
        assert record["after"][changed_path]["exists"] is True
        assert record["after"][changed_path]["sha256"]
        assert record["metadata"]["reason"] == "create file for test"

    @pytest.mark.asyncio
    async def test_records_before_content_for_edit_checkpoint(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        path = os.path.realpath(os.path.join(temp_dir, "app.py"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("print('old')\n")
        checkpoints_dir = os.path.join(temp_dir, "stores", "checkpoints")
        store = CheckpointStore(checkpoints_dir)
        chain = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-a"),
        ])

        result = await chain.run(EditFileTool(workspace=workspace), {
            "path": "app.py",
            "old_text": "old",
            "new_text": "new",
        })

        assert "Edited" in result
        records = _checkpoint_records(checkpoints_dir)
        assert len(records) == 1
        snapshot = records[0]["before"][path]
        before_content = base64.b64decode(snapshot["content_b64"]).decode("utf-8")
        assert before_content == "print('old')\n"
        assert records[0]["after"][path]["sha256"] != snapshot["sha256"]

    @pytest.mark.asyncio
    async def test_does_not_record_failed_mutation_checkpoint(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        path = os.path.join(temp_dir, "app.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("print('old')\n")
        checkpoints_dir = os.path.join(temp_dir, "stores", "checkpoints")
        store = CheckpointStore(checkpoints_dir)
        chain = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-a"),
        ])

        result = await chain.run(EditFileTool(workspace=workspace), {
            "path": "app.py",
            "old_text": "missing",
            "new_text": "new",
        })

        assert result.startswith("Error:")
        assert _checkpoint_records(checkpoints_dir) == []

    @pytest.mark.asyncio
    async def test_records_checkpoint_trace_and_goal_evidence(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
        recorder = trace_store.start_run("session-a")
        tool_started_event = recorder.append("tool.started", {
            "name": "write_file",
            "summary": "write_file path=new.txt",
        })
        shared_state = {
            "trace_recorder": recorder,
            ACTIVE_TOOL_CALL_ID_STATE_KEY: "call-write-1",
            ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY: tool_started_event.event_id,
        }
        goal_store = GoalLedgerStore(os.path.join(temp_dir, "stores", "ledgers"))
        goal_store.start("session-a", "Track mutation")
        checkpoints_dir = os.path.join(temp_dir, "stores", "checkpoints")
        store = CheckpointStore(checkpoints_dir)
        chain = MiddlewareChain([
            CheckpointMiddleware(
                store,
                workspace=workspace,
                session_key="session-a",
                shared_state=shared_state,
                goal_store=goal_store,
            ),
        ])

        result = await chain.run(WriteFileTool(workspace=workspace), {
            "path": "new.txt",
            "content": "hello",
            "reason": "add requested fixture",
        })
        recorder.finish("complete", stop_reason="test")

        assert "Written" in result
        events = trace_store.load_events("session-a", recorder.run_id)
        assert "checkpoint.created" in [event.event for event in events]
        checkpoint_event = next(event for event in events if event.event == "checkpoint.created")
        ledger_event = next(event for event in events if event.event == "ledger.updated")
        records = _checkpoint_records(checkpoints_dir)
        assert records[0]["metadata"]["tool_call_id"] == "call-write-1"
        assert records[0]["metadata"]["tool_trace_event_id"] == tool_started_event.event_id
        assert ledger_event.data["kind"] == "checkpoint"
        assert ledger_event.data["evidence_id"].startswith("change-")
        assert ledger_event.data["ledger_path"].endswith("session-a.ledger.json")
        assert ledger_event.data["related_trace_event_id"] == checkpoint_event.event_id
        assert checkpoint_event.data["tool_call_id"] == "call-write-1"
        assert checkpoint_event.data["tool_trace_event_id"] == tool_started_event.event_id
        assert ledger_event.data["tool_call_id"] == "call-write-1"
        assert ledger_event.data["tool_trace_event_id"] == tool_started_event.event_id
        assert ledger_event.data["checkpoint_id"] == checkpoint_event.data["checkpoint_id"]
        assert checkpoint_event.data["reason"] == "add requested fixture"
        assert ledger_event.data["reason"] == "add requested fixture"
        summary = trace_store.load_summary("session-a", recorder.run_id)
        assert summary.checkpoints
        assert summary.files_changed == ["new.txt"]
        ledger = goal_store.load("session-a")
        assert [item.path for item in ledger.changed_files] == ["new.txt"]
        assert "add requested fixture" in ledger.changed_files[0].summary
        assert ledger.changed_files[0].id == ledger_event.data["evidence_id"]
        assert ledger.changed_files[0].checkpoint_id == checkpoint_event.data["checkpoint_id"]
        assert ledger.changed_files[0].tool_call_id == "call-write-1"
        assert ledger.changed_files[0].tool_trace_event_id == tool_started_event.event_id


class TestCheckpointUndo:
    @pytest.mark.asyncio
    async def test_undo_restores_edited_file(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        path = os.path.realpath(os.path.join(temp_dir, "app.py"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("print('old')\n")
        store = CheckpointStore(os.path.join(temp_dir, "stores", "checkpoints"))
        chain = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-a"),
        ])

        result = await chain.run(EditFileTool(workspace=workspace), {
            "path": "app.py",
            "old_text": "old",
            "new_text": "new",
        })

        assert "Edited" in result
        undo = store.undo_last(session_key="session-a")
        assert undo.ok is True
        assert undo.restored_paths == [path]
        with open(path, encoding="utf-8") as handle:
            assert handle.read() == "print('old')\n"
        assert store.latest(session_key="session-a") is None

    @pytest.mark.asyncio
    async def test_undo_deletes_created_file(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        path = os.path.realpath(os.path.join(temp_dir, "new.txt"))
        store = CheckpointStore(os.path.join(temp_dir, "stores", "checkpoints"))
        chain = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-a"),
        ])

        result = await chain.run(WriteFileTool(workspace=workspace), {
            "path": "new.txt",
            "content": "hello",
        })

        assert "Written" in result
        assert os.path.exists(path)
        undo = store.undo_last(session_key="session-a")
        assert undo.ok is True
        assert undo.restored_paths == [path]
        assert not os.path.exists(path)

    @pytest.mark.asyncio
    async def test_undo_is_scoped_to_session(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        store = CheckpointStore(os.path.join(temp_dir, "stores", "checkpoints"))

        chain_a = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-a"),
        ])
        chain_b = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-b"),
        ])

        await chain_a.run(WriteFileTool(workspace=workspace), {
            "path": "a.txt",
            "content": "a",
        })
        await chain_b.run(WriteFileTool(workspace=workspace), {
            "path": "b.txt",
            "content": "b",
        })

        undo = store.undo_last(session_key="session-a")
        assert undo.ok is True
        assert not os.path.exists(os.path.join(temp_dir, "a.txt"))
        assert os.path.exists(os.path.join(temp_dir, "b.txt"))
        assert store.latest(session_key="session-b") is not None

    @pytest.mark.asyncio
    async def test_undo_refuses_conflict_when_file_changed_after_checkpoint(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        path = os.path.realpath(os.path.join(temp_dir, "app.py"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("old\n")
        store = CheckpointStore(os.path.join(temp_dir, "stores", "checkpoints"))
        chain = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-a"),
        ])

        await chain.run(EditFileTool(workspace=workspace), {
            "path": "app.py",
            "old_text": "old",
            "new_text": "new",
        })
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("external\n")

        undo = store.undo_last(session_key="session-a")
        assert undo.ok is False
        assert undo.conflicts == [f"{path}: changed since checkpoint"]
        with open(path, encoding="utf-8") as handle:
            assert handle.read() == "external\n"

    @pytest.mark.asyncio
    async def test_undo_apply_patch_restores_add_update_and_delete(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        app_path = os.path.realpath(os.path.join(temp_dir, "app.py"))
        old_path = os.path.realpath(os.path.join(temp_dir, "old.txt"))
        new_path = os.path.realpath(os.path.join(temp_dir, "new.txt"))
        with open(app_path, "w", encoding="utf-8") as handle:
            handle.write("print('old')\n")
        with open(old_path, "w", encoding="utf-8") as handle:
            handle.write("remove me\n")
        store = CheckpointStore(os.path.join(temp_dir, "stores", "checkpoints"))
        chain = MiddlewareChain([
            CheckpointMiddleware(store, workspace=workspace, session_key="session-a"),
        ])
        patch_text = "\n".join([
            "*** Begin Patch",
            "*** Update File: app.py",
            "@@",
            "-print('old')",
            "+print('new')",
            "*** Delete File: old.txt",
            "*** Add File: new.txt",
            "+created",
            "*** End Patch",
        ])

        result = await chain.run(ApplyPatchTool(workspace=workspace), {"patch_text": patch_text})

        assert "Applied patch" in result
        assert os.path.exists(new_path)
        assert not os.path.exists(old_path)
        undo = store.undo_last(session_key="session-a")
        assert undo.ok is True
        with open(app_path, encoding="utf-8") as handle:
            assert handle.read() == "print('old')\n"
        with open(old_path, encoding="utf-8") as handle:
            assert handle.read() == "remove me\n"
        assert not os.path.exists(new_path)

    @pytest.mark.asyncio
    async def test_undo_refuses_skipped_snapshot(self, temp_dir):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        store = CheckpointStore(os.path.join(temp_dir, "stores", "checkpoints"))
        trace_store = RunTraceStore(os.path.join(temp_dir, "stores", "traces"))
        recorder = trace_store.start_run("session-a")
        chain = MiddlewareChain([
            CheckpointMiddleware(
                store,
                workspace=workspace,
                session_key="session-a",
                shared_state={TRACE_RECORDER_STATE_KEY: recorder},
            ),
        ])

        await chain.run(WriteFileTool(workspace=workspace), {
            "path": "large.txt",
            "content": "x" * (MAX_SNAPSHOT_BYTES + 1),
        })

        record = store.latest(session_key="session-a")
        assert record is not None
        skipped = record.metadata["skipped_snapshots"]
        assert skipped[0]["phase"] == "after"
        assert skipped[0]["reason"] == f"larger than {MAX_SNAPSHOT_BYTES} bytes"
        events = trace_store.load_events(recorder.session_key, recorder.run_id)
        checkpoint_event = next(event for event in events if event.event == "checkpoint.created")
        assert checkpoint_event.data["skipped_snapshots"][0]["path"] == "large.txt"

        undo = store.undo_last(session_key="session-a")
        assert undo.ok is False
        assert len(undo.conflicts) == 1
        assert "cannot restore skipped snapshot" in undo.conflicts[0]
