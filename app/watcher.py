import asyncio
import logging
import os
from typing import Dict, Optional

from app.hooks import HookRunner, ON_FILE_CHANGE
from app.utilities import make_hash, get_docs

logger = logging.getLogger("smolclaw.watcher")


class MemoryFileWatcher:
    """Poll-based file watcher for the memory directory.

    Detects new, changed, and deleted files by comparing content hashes.
    On change: re-ingests into SmolRAG.
    On delete: removes from SmolRAG graph.
    """

    def __init__(
        self,
        memory_dir: str,
        smol_rag,
        poll_interval: float = 5.0,
        hook_runner: Optional[HookRunner] = None,
    ):
        self.memory_dir = memory_dir
        self.smol_rag = smol_rag
        self.poll_interval = poll_interval
        self.hook_runner = hook_runner or HookRunner()
        self._hashes: Dict[str, str] = {}
        self._running = False

    def _scan(self) -> Dict[str, str]:
        """Scan the memory directory and return {filepath: content_hash}."""
        result = {}
        if not os.path.isdir(self.memory_dir):
            return result
        for file_path in get_docs(self.memory_dir):
            try:
                with open(file_path) as f:
                    content = f.read()
                result[file_path] = make_hash(content)
            except (IOError, OSError) as e:
                logger.warning(f"Could not read {file_path}: {e}")
        return result

    async def check_once(self) -> Dict[str, str]:
        """Run a single poll cycle. Returns dict of changes: {path: action}.

        Actions: "created", "modified", "deleted"
        """
        current = self._scan()
        changes = {}

        # New or modified files
        for path, hash_val in current.items():
            if path not in self._hashes:
                changes[path] = "created"
            elif self._hashes[path] != hash_val:
                changes[path] = "modified"

        # Deleted files
        for path in self._hashes:
            if path not in current:
                changes[path] = "deleted"

        # Process changes
        for path, action in changes.items():
            logger.info(f"File {action}: {path}")
            if action in ("created", "modified"):
                try:
                    with open(path) as f:
                        content = f.read()
                    await self.smol_rag.ingest_text(content, source_id=path)
                except Exception as e:
                    logger.error(f"Failed to ingest {path}: {e}")
            elif action == "deleted":
                try:
                    await self.smol_rag.remove_document_by_source(path)
                except Exception as e:
                    logger.warning(f"Failed to remove {path} from index: {e}")

            await self.hook_runner.fire(ON_FILE_CHANGE, {
                "path": path,
                "action": action,
            })

        self._hashes = current
        return changes

    async def start(self):
        """Start the polling loop."""
        self._running = True
        # Initial scan to populate hashes
        self._hashes = self._scan()
        logger.info(f"Watcher started on {self.memory_dir} ({len(self._hashes)} files)")

        while self._running:
            await asyncio.sleep(self.poll_interval)
            await self.check_once()

    def stop(self):
        """Stop the polling loop."""
        self._running = False
