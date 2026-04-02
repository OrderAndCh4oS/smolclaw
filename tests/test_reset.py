"""Tests for app.reset — full store wipe."""
import os
from pathlib import Path

import pytest

from app.reset import reset_all_stores


@pytest.fixture
def data_dir(temp_dir):
    """Populate a fake data_dir with the files reset should delete."""
    d = Path(temp_dir)

    # SQLite DB + journal files
    (d / "smolclaw.db").write_text("fake-db")
    (d / "smolclaw.db-wal").write_text("wal")
    (d / "smolclaw.db-shm").write_text("shm")

    # Knowledge graph
    (d / "kg_db.graphml").write_text("<graphml/>")

    # Subdirectories with files
    for sub in ("sessions", "memory", "logs", "cache"):
        (d / sub).mkdir()
        (d / sub / "file1.txt").write_text("data")
        (d / sub / "file2.txt").write_text("data")

    # research and legacy input_docs — should be preserved
    (d / "research").mkdir()
    (d / "research" / "keep_me.md").write_text("important")
    (d / "input_docs").mkdir()
    (d / "input_docs" / "keep_me.md").write_text("important")

    return str(d)


@pytest.mark.asyncio
async def test_reset_deletes_all_stores(data_dir):
    deleted = await reset_all_stores(data_dir)

    d = Path(data_dir)
    # DB files gone
    assert not (d / "smolclaw.db").exists()
    assert not (d / "smolclaw.db-wal").exists()
    assert not (d / "smolclaw.db-shm").exists()

    # Graph gone
    assert not (d / "kg_db.graphml").exists()

    # Subdirectory contents cleared
    for sub in ("sessions", "memory", "logs", "cache"):
        assert list((d / sub).iterdir()) == []

    # Should have reported actions
    assert len(deleted) > 0


@pytest.mark.asyncio
async def test_reset_preserves_research_docs(data_dir):
    await reset_all_stores(data_dir)

    d = Path(data_dir)
    assert (d / "research" / "keep_me.md").exists()
    assert (d / "research" / "keep_me.md").read_text() == "important"
    assert (d / "input_docs" / "keep_me.md").exists()
    assert (d / "input_docs" / "keep_me.md").read_text() == "important"


@pytest.mark.asyncio
async def test_reset_on_empty_dir(temp_dir):
    """Reset on a clean directory does nothing and doesn't error."""
    deleted = await reset_all_stores(temp_dir)
    assert deleted == []


@pytest.mark.asyncio
async def test_stores_recreate_after_reset(data_dir):
    """After reset, SQLite stores can be created fresh."""
    await reset_all_stores(data_dir)

    db_path = os.path.join(data_dir, "smolclaw.db")
    from app.sqlite_store import SqliteKvStore

    store = SqliteKvStore(db_path, "test_table")
    await store.add("key", {"value": 1})
    result = await store.get_by_key("key")
    assert result == {"value": 1}
    await store.close()
