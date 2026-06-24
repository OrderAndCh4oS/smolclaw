from __future__ import annotations

import fnmatch


DEFAULT_DISCOVERY_EXCLUDES = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".nltk_data",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".venv*",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".smolclaw",
    "stores",
    "workspace",
    "memory",
    "research",
    "*.egg-info",
})


def is_discovery_excluded(name: str, patterns=DEFAULT_DISCOVERY_EXCLUDES) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
