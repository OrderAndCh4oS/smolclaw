"""Wipe all persistent SmolClaw state for a full reset."""
import os
import glob
from pathlib import Path


async def reset_all_stores(data_dir: str) -> list[str]:
    """Delete all persistent data under *data_dir* for a full reset.

    Preserves ``input_docs/`` (user source material).
    Returns a list of human-readable descriptions of what was deleted.
    """
    deleted: list[str] = []
    data = Path(data_dir)

    # 1. SQLite DB + WAL/SHM journal files
    for pattern in ("smolclaw.db", "smolclaw.db-wal", "smolclaw.db-shm"):
        for p in data.glob(pattern):
            p.unlink()
            deleted.append(f"Deleted {p}")

    # 2. Vector / entity JSON stores
    for pattern in ("embeddings_db.json", "entities_db.json", "relationships_db.json"):
        p = data / pattern
        if p.exists():
            p.unlink()
            deleted.append(f"Deleted {p}")

    # 3. Knowledge graph
    p = data / "kg_db.graphml"
    if p.exists():
        p.unlink()
        deleted.append(f"Deleted {p}")

    # 4. Subdirectories: sessions, memory, logs, cache (NOT input_docs)
    for subdir in ("sessions", "memory", "logs", "cache"):
        d = data / subdir
        if not d.is_dir():
            continue
        count = 0
        for f in d.iterdir():
            if f.is_file():
                f.unlink()
                count += 1
        if count:
            deleted.append(f"Cleared {count} file(s) from {d}")

    return deleted
