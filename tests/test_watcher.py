import os
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.watcher import MemoryFileWatcher


@pytest.fixture
def watcher_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def mock_watcher_rag():
    mock = MagicMock()
    mock.ingest_text = AsyncMock()
    mock.remove_document_by_source = AsyncMock()
    return mock


class TestMemoryFileWatcher:
    @pytest.mark.asyncio
    async def test_detects_new_file(self, watcher_dir, mock_watcher_rag):
        watcher = MemoryFileWatcher(watcher_dir, mock_watcher_rag)
        watcher._hashes = {}  # Start empty

        # Create a file
        path = os.path.join(watcher_dir, "test.md")
        with open(path, "w") as f:
            f.write("# Test Memory\nSome content.")

        changes = await watcher.check_once()
        assert path in changes
        assert changes[path] == "created"
        mock_watcher_rag.ingest_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_detects_modified_file(self, watcher_dir, mock_watcher_rag):
        path = os.path.join(watcher_dir, "test.md")
        with open(path, "w") as f:
            f.write("Original content.")

        watcher = MemoryFileWatcher(watcher_dir, mock_watcher_rag)
        watcher._hashes = watcher._scan()

        # Modify the file
        with open(path, "w") as f:
            f.write("Modified content.")

        changes = await watcher.check_once()
        assert path in changes
        assert changes[path] == "modified"
        mock_watcher_rag.ingest_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_detects_deleted_file(self, watcher_dir, mock_watcher_rag):
        path = os.path.join(watcher_dir, "test.md")
        with open(path, "w") as f:
            f.write("Content to delete.")

        watcher = MemoryFileWatcher(watcher_dir, mock_watcher_rag)
        watcher._hashes = watcher._scan()

        # Delete the file
        os.remove(path)

        changes = await watcher.check_once()
        assert path in changes
        assert changes[path] == "deleted"
        mock_watcher_rag.remove_document_by_source.assert_awaited_once_with(path)

    @pytest.mark.asyncio
    async def test_no_changes_returns_empty(self, watcher_dir, mock_watcher_rag):
        path = os.path.join(watcher_dir, "stable.md")
        with open(path, "w") as f:
            f.write("Stable content.")

        watcher = MemoryFileWatcher(watcher_dir, mock_watcher_rag)
        watcher._hashes = watcher._scan()

        changes = await watcher.check_once()
        assert changes == {}
        mock_watcher_rag.ingest_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_directory(self, watcher_dir, mock_watcher_rag):
        watcher = MemoryFileWatcher(watcher_dir, mock_watcher_rag)
        changes = await watcher.check_once()
        assert changes == {}

    @pytest.mark.asyncio
    async def test_fires_hook_on_change(self, watcher_dir, mock_watcher_rag):
        from app.hooks import HookRunner, ON_FILE_CHANGE

        hook = AsyncMock()
        runner = HookRunner()
        runner.on(ON_FILE_CHANGE, hook)

        watcher = MemoryFileWatcher(watcher_dir, mock_watcher_rag, hook_runner=runner)
        watcher._hashes = {}

        path = os.path.join(watcher_dir, "test.md")
        with open(path, "w") as f:
            f.write("New content.")

        await watcher.check_once()
        hook.assert_awaited_once()
        ctx = hook.call_args[0][0]
        assert ctx["action"] == "created"
        assert ctx["path"] == path

    def test_stop(self, watcher_dir, mock_watcher_rag):
        watcher = MemoryFileWatcher(watcher_dir, mock_watcher_rag)
        watcher._running = True
        watcher.stop()
        assert watcher._running is False

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self, mock_watcher_rag):
        watcher = MemoryFileWatcher("/nonexistent/path", mock_watcher_rag)
        changes = await watcher.check_once()
        assert changes == {}
