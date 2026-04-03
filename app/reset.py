"""Workspace-owned reset helpers."""

from pathlib import Path

from app.workspace import WorkspaceContext


def _clear_directory_contents(path: Path) -> int:
    if not path.is_dir():
        return 0

    removed = 0
    for child in sorted(path.iterdir(), key=lambda item: len(item.parts), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
            removed += 1
            continue
        for nested in sorted(child.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if nested.is_file() or nested.is_symlink():
                nested.unlink()
                removed += 1
            elif nested.is_dir():
                nested.rmdir()
        child.rmdir()
    return removed


async def reset_workspace(workspace: WorkspaceContext) -> list[str]:
    """Delete mutable workspace state while preserving research source material."""
    deleted: list[str] = []
    paths = workspace.paths

    for file_path in (
        Path(paths.sqlite_db_path),
        Path(paths.sqlite_db_path + "-wal"),
        Path(paths.sqlite_db_path + "-shm"),
        Path(paths.kg_db_path),
    ):
        if file_path.exists():
            file_path.unlink()
            deleted.append(f"Deleted {file_path}")

    for directory in (
        Path(paths.sessions_dir),
        Path(paths.memory_docs_dir),
        Path(paths.log_dir),
        Path(paths.cache_dir),
    ):
        removed = _clear_directory_contents(directory)
        if removed:
            deleted.append(f"Cleared {removed} file(s) from {directory}")

    return deleted


async def reset_all_stores(data_dir: str) -> list[str]:
    """Backward-compatible wrapper for legacy callers and tests."""
    return await reset_workspace(WorkspaceContext.from_root(Path(data_dir).parent))
