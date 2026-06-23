import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from json import JSONDecodeError
from typing import Any


_SAFE_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%-]{0,119}$")


def safe_storage_stem(key: str) -> str:
    """Return a filesystem-safe filename stem for a user-controlled storage key."""
    value = str(key or "")
    if _SAFE_STEM_RE.fullmatch(value) and value not in {".", ".."}:
        return value

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not slug:
        slug = "session"
    return f"{slug[:80]}--{digest}"


def contained_storage_path(directory: str, key: str, suffix: str) -> str:
    """Build a contained storage path from a user-controlled key and suffix."""
    root = os.path.realpath(directory)
    path = os.path.realpath(os.path.join(root, f"{safe_storage_stem(key)}{suffix}"))
    if os.path.commonpath([root, path]) != root:
        raise ValueError("Storage path escaped the configured directory.")
    return path


def backup_storage_path(path: str) -> str:
    return f"{path}.bak"


def _fsync_directory(directory: str):
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path: str, content: str, *, encoding: str = "utf-8", backup: bool = True):
    """Atomically write text and retain a backup of the previous complete file."""
    directory = os.path.dirname(os.path.realpath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if backup and os.path.exists(path):
            shutil.copy2(path, backup_storage_path(path))
        os.replace(tmp_path, path)
        _fsync_directory(directory)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: str, data: Any, *, indent: int = 2, backup: bool = True):
    atomic_write_text(path, json.dumps(data, indent=indent) + "\n", backup=backup)


def load_with_backup(path: str, loader: Callable[[str], Any], default: Any = None) -> Any:
    """Load a state file, falling back to the last backup if the primary is corrupt."""
    if not os.path.exists(path):
        return default
    try:
        return loader(path)
    except (OSError, JSONDecodeError, ValueError):
        backup_path = backup_storage_path(path)
        if not os.path.exists(backup_path):
            return default
        try:
            return loader(backup_path)
        except (OSError, JSONDecodeError, ValueError):
            return default


def load_json_with_backup(path: str, default: Any = None) -> Any:
    def _load(candidate: str):
        with open(candidate, encoding="utf-8") as handle:
            return json.load(handle)

    return load_with_backup(path, _load, default)
