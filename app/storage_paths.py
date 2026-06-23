import hashlib
import os
import re


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
