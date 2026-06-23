"""Tests for app.reset workspace resets."""

import os
from pathlib import Path

import pytest

from app.reset import reset_all_stores, reset_workspace
from app.workspace import WorkspaceContext


@pytest.fixture
def workspace(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    paths = workspace.paths

    Path(paths.sqlite_db_path).write_text("fake-db")
    Path(paths.sqlite_db_path + "-wal").write_text("wal")
    Path(paths.sqlite_db_path + "-shm").write_text("shm")
    Path(paths.kg_db_path).write_text("<graphml/>")

    for subdir in (
        paths.sessions_dir,
        paths.checkpoints_dir,
        paths.memory_docs_dir,
        paths.log_dir,
        paths.cache_dir,
    ):
        directory = Path(subdir)
        (directory / "file1.txt").write_text("data")
        nested = directory / "nested"
        nested.mkdir(exist_ok=True)
        (nested / "file2.txt").write_text("data")

    Path(paths.research_dir, "keep_me.md").write_text("important")
    return workspace


@pytest.mark.asyncio
async def test_reset_workspace_deletes_mutable_state(workspace):
    deleted = await reset_workspace(workspace)
    paths = workspace.paths

    assert not Path(paths.sqlite_db_path).exists()
    assert not Path(paths.sqlite_db_path + "-wal").exists()
    assert not Path(paths.sqlite_db_path + "-shm").exists()
    assert not Path(paths.kg_db_path).exists()

    for subdir in (
        paths.sessions_dir,
        paths.checkpoints_dir,
        paths.memory_docs_dir,
        paths.log_dir,
        paths.cache_dir,
    ):
        assert list(Path(subdir).iterdir()) == []

    assert deleted


@pytest.mark.asyncio
async def test_reset_workspace_preserves_research(workspace):
    await reset_workspace(workspace)
    keep = Path(workspace.paths.research_dir, "keep_me.md")
    assert keep.exists()
    assert keep.read_text() == "important"


@pytest.mark.asyncio
async def test_reset_all_stores_legacy_wrapper_uses_workspace_root(workspace):
    deleted = await reset_all_stores(workspace.paths.data_dir)
    assert deleted
    assert list(Path(workspace.paths.memory_docs_dir).iterdir()) == []
    assert Path(workspace.paths.research_dir, "keep_me.md").exists()


@pytest.mark.asyncio
async def test_stores_recreate_after_reset(workspace):
    await reset_workspace(workspace)

    db_path = os.path.join(workspace.paths.data_dir, "smolclaw.db")
    from app.sqlite_store import SqliteKvStore

    store = SqliteKvStore(db_path, "test_table")
    await store.add("key", {"value": 1})
    result = await store.get_by_key("key")
    assert result == {"value": 1}
    await store.close()
