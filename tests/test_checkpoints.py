import base64
import json
import os

import pytest

from app.checkpoints import CheckpointStore
from app.tools.checkpointing import CheckpointMiddleware
from app.tools.filesystem import EditFileTool, WriteFileTool
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
