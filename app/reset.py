"""Workspace-owned reset helpers."""

from pathlib import Path
import sqlite3

import networkx as nx

from app.logger import clear_logs
from app.workspace import WorkspaceContext

RESET_COMPONENTS = frozenset({"logs", "memories", "journals", "rag", "kg"})


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


def _clear_matching_files(path: Path, predicate) -> int:
    if not path.is_dir():
        return 0

    removed = 0
    for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_file() or child.is_symlink():
            if predicate(child):
                child.unlink()
                removed += 1
        elif child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass
    return removed


def _delete_files(paths: tuple[Path, ...]) -> list[str]:
    deleted: list[str] = []
    for file_path in paths:
        if file_path.exists():
            file_path.unlink()
            deleted.append(f"Deleted {file_path}")
    return deleted


def _clear_logs_directory(path: Path) -> int:
    removed = len(clear_logs(str(path)))
    removed += _clear_directory_contents(path)
    return removed


def _rag_files(workspace: WorkspaceContext) -> tuple[Path, ...]:
    paths = workspace.paths
    return (
        Path(paths.sqlite_db_path),
        Path(paths.sqlite_db_path + "-wal"),
        Path(paths.sqlite_db_path + "-shm"),
    )


def _kg_files(workspace: WorkspaceContext) -> tuple[Path, ...]:
    return (Path(workspace.paths.kg_db_path),)


def _reset_rag_store(workspace: WorkspaceContext) -> list[str]:
    paths = workspace.paths
    db_path = Path(paths.sqlite_db_path)
    deleted = _delete_files(_rag_files(workspace))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.close()
    deleted.append(f"Created fresh {db_path}")
    return deleted


def _reset_kg_store(workspace: WorkspaceContext) -> list[str]:
    paths = workspace.paths
    kg_path = Path(paths.kg_db_path)
    deleted = _delete_files(_kg_files(workspace))
    kg_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(nx.Graph(), kg_path)
    deleted.append(f"Created fresh {kg_path}")
    return deleted


async def reset_workspace(workspace: WorkspaceContext) -> list[str]:
    """Delete mutable workspace state while preserving research source material."""
    deleted: list[str] = []
    paths = workspace.paths

    deleted.extend(_reset_rag_store(workspace))
    deleted.extend(_reset_kg_store(workspace))

    for directory in (
        Path(paths.sessions_dir),
        Path(paths.checkpoints_dir),
        Path(paths.traces_dir),
        Path(paths.ledgers_dir),
        Path(paths.approvals_dir),
        Path(paths.evals_dir),
        Path(paths.memory_docs_dir),
        Path(paths.cache_dir),
    ):
        removed = _clear_directory_contents(directory)
        if removed:
            deleted.append(f"Cleared {removed} file(s) from {directory}")

    removed_logs = _clear_logs_directory(Path(paths.log_dir))
    if removed_logs:
        deleted.append(f"Cleared {removed_logs} file(s) from {paths.log_dir}")

    return deleted


async def reset_workspace_components(
    workspace: WorkspaceContext,
    components: set[str] | frozenset[str],
) -> list[str]:
    """Delete selected mutable workspace state components."""
    unknown = sorted(set(components) - RESET_COMPONENTS)
    if unknown:
        raise ValueError(f"Unknown reset component(s): {', '.join(unknown)}")

    deleted: list[str] = []
    paths = workspace.paths

    if "rag" in components:
        deleted.extend(_reset_rag_store(workspace))

    if "kg" in components:
        deleted.extend(_reset_kg_store(workspace))

    if "logs" in components:
        removed = _clear_logs_directory(Path(paths.log_dir))
        if removed:
            deleted.append(f"Cleared {removed} file(s) from {paths.log_dir}")

    if "journals" in components:
        removed = _clear_matching_files(
            Path(paths.memory_docs_dir),
            lambda child: child.name.startswith("journal-"),
        )
        if removed:
            deleted.append(f"Cleared {removed} journal file(s) from {paths.memory_docs_dir}")

    if "memories" in components:
        removed = _clear_matching_files(
            Path(paths.memory_docs_dir),
            lambda child: not child.name.startswith("journal-"),
        )
        if removed:
            deleted.append(f"Cleared {removed} memory file(s) from {paths.memory_docs_dir}")

    return deleted


async def reset_all_stores(data_dir: str) -> list[str]:
    """Backward-compatible wrapper for legacy callers and tests."""
    state_root = Path(data_dir).parent
    workspace_root = state_root.parent if state_root.name == ".smolclaw" else state_root
    return await reset_workspace(WorkspaceContext.from_root(workspace_root, state_root=str(state_root)))
