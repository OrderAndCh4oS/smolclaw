import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from app.storage_paths import atomic_write_json, contained_storage_path


MAX_SNAPSHOT_BYTES = 1_000_000


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_hash(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


@dataclass
class FileSnapshot:
    path: str
    exists: bool
    is_file: bool
    size: int = 0
    sha256: str | None = None
    content_b64: str | None = None
    skipped: bool = False
    skip_reason: str = ""

    @classmethod
    def capture(cls, path: str, *, max_bytes: int = MAX_SNAPSHOT_BYTES) -> "FileSnapshot":
        real_path = os.path.realpath(path)
        if not os.path.exists(real_path):
            return cls(path=real_path, exists=False, is_file=False)
        if not os.path.isfile(real_path):
            return cls(path=real_path, exists=True, is_file=False, skipped=True, skip_reason="not a file")
        size = os.path.getsize(real_path)
        if size > max_bytes:
            return cls(
                path=real_path,
                exists=True,
                is_file=True,
                size=size,
                skipped=True,
                skip_reason=f"larger than {max_bytes} bytes",
            )
        with open(real_path, "rb") as handle:
            data = handle.read()
        return cls(
            path=real_path,
            exists=True,
            is_file=True,
            size=len(data),
            sha256=_sha256_bytes(data),
            content_b64=base64.b64encode(data).decode("ascii"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "is_file": self.is_file,
            "size": self.size,
            "sha256": self.sha256,
            "content_b64": self.content_b64,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


@dataclass
class CheckpointRecord:
    id: str
    created_at: float
    session_key: str | None
    tool_name: str
    arguments_hash: str
    changed_paths: list[str]
    before: dict[str, FileSnapshot]
    after: dict[str, FileSnapshot]
    run_id: str | None = None
    prompt_id: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "session_key": self.session_key,
            "tool_name": self.tool_name,
            "arguments_hash": self.arguments_hash,
            "changed_paths": self.changed_paths,
            "before": {path: snapshot.to_dict() for path, snapshot in self.before.items()},
            "after": {path: snapshot.to_dict() for path, snapshot in self.after.items()},
            "run_id": self.run_id,
            "prompt_id": self.prompt_id,
            "tool_call_id": self.tool_call_id,
            "metadata": self.metadata,
        }


class CheckpointStore:
    def __init__(self, checkpoints_dir: str):
        self.checkpoints_dir = checkpoints_dir
        os.makedirs(checkpoints_dir, exist_ok=True)

    def path_for(self, checkpoint_id: str) -> str:
        return contained_storage_path(self.checkpoints_dir, checkpoint_id, ".json")

    def save(self, record: CheckpointRecord):
        atomic_write_json(self.path_for(record.id), record.to_dict())

    def create_record(
        self,
        *,
        session_key: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        before: dict[str, FileSnapshot],
        after: dict[str, FileSnapshot],
        run_id: str | None = None,
        prompt_id: str | None = None,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CheckpointRecord | None:
        changed_paths = sorted(
            path for path in set(before) | set(after)
            if self._snapshot_hash(before.get(path)) != self._snapshot_hash(after.get(path))
        )
        if not changed_paths:
            return None
        created_at = time.time()
        checkpoint_id = self._checkpoint_id(created_at, session_key, tool_name, arguments, changed_paths)
        return CheckpointRecord(
            id=checkpoint_id,
            created_at=created_at,
            session_key=session_key,
            tool_name=tool_name,
            arguments_hash=_json_hash(arguments),
            changed_paths=changed_paths,
            before=before,
            after=after,
            run_id=run_id,
            prompt_id=prompt_id,
            tool_call_id=tool_call_id,
            metadata=metadata or {},
        )

    def _checkpoint_id(
        self,
        created_at: float,
        session_key: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        changed_paths: list[str],
    ) -> str:
        digest = _json_hash({
            "created_at": created_at,
            "session_key": session_key,
            "tool_name": tool_name,
            "arguments": arguments,
            "changed_paths": changed_paths,
        })[:16]
        return f"chk-{int(created_at * 1000)}-{digest}"

    def _snapshot_hash(self, snapshot: FileSnapshot | None) -> tuple:
        if snapshot is None:
            return (False, False, None, 0, True)
        return (
            snapshot.exists,
            snapshot.is_file,
            snapshot.sha256,
            snapshot.size,
            snapshot.skipped,
        )
