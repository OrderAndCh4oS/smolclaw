import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from app.storage_paths import atomic_write_bytes, atomic_write_json, contained_storage_path, load_json_with_backup


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileSnapshot":
        return cls(
            path=str(data["path"]),
            exists=bool(data["exists"]),
            is_file=bool(data["is_file"]),
            size=int(data.get("size") or 0),
            sha256=data.get("sha256"),
            content_b64=data.get("content_b64"),
            skipped=bool(data.get("skipped")),
            skip_reason=str(data.get("skip_reason") or ""),
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckpointRecord":
        return cls(
            id=str(data["id"]),
            created_at=float(data["created_at"]),
            session_key=data.get("session_key"),
            tool_name=str(data["tool_name"]),
            arguments_hash=str(data["arguments_hash"]),
            changed_paths=[str(path) for path in data.get("changed_paths", [])],
            before={
                str(path): FileSnapshot.from_dict(snapshot)
                for path, snapshot in data.get("before", {}).items()
            },
            after={
                str(path): FileSnapshot.from_dict(snapshot)
                for path, snapshot in data.get("after", {}).items()
            },
            run_id=data.get("run_id"),
            prompt_id=data.get("prompt_id"),
            tool_call_id=data.get("tool_call_id"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class CheckpointUndoResult:
    ok: bool
    message: str
    checkpoint_id: str | None = None
    restored_paths: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


class CheckpointStore:
    def __init__(self, checkpoints_dir: str):
        self.checkpoints_dir = checkpoints_dir
        os.makedirs(checkpoints_dir, exist_ok=True)

    def path_for(self, checkpoint_id: str) -> str:
        return contained_storage_path(self.checkpoints_dir, checkpoint_id, ".json")

    def save(self, record: CheckpointRecord):
        atomic_write_json(self.path_for(record.id), record.to_dict())

    def load(self, checkpoint_id: str) -> CheckpointRecord | None:
        data = load_json_with_backup(self.path_for(checkpoint_id))
        if not data:
            return None
        return CheckpointRecord.from_dict(data)

    def list_records(self, *, session_key: str | None = None) -> list[CheckpointRecord]:
        records: list[CheckpointRecord] = []
        for name in os.listdir(self.checkpoints_dir):
            if not name.endswith(".json") or name.endswith(".json.bak"):
                continue
            checkpoint_id = name.removesuffix(".json")
            record = self.load(checkpoint_id)
            if record is None:
                continue
            if session_key is not None and record.session_key != session_key:
                continue
            records.append(record)
        return sorted(records, key=lambda record: record.created_at)

    def latest(self, *, session_key: str | None = None, include_undone: bool = False) -> CheckpointRecord | None:
        records = self.list_records(session_key=session_key)
        for record in reversed(records):
            if include_undone or not record.metadata.get("undone_at"):
                return record
        return None

    def undo_last(self, *, session_key: str | None = None) -> CheckpointUndoResult:
        record = self.latest(session_key=session_key)
        if record is None:
            return CheckpointUndoResult(ok=False, message="No checkpoint to undo.")

        conflicts = self._undo_conflicts(record)
        if conflicts:
            return CheckpointUndoResult(
                ok=False,
                message="Checkpoint undo refused because current files no longer match the checkpoint.",
                checkpoint_id=record.id,
                conflicts=conflicts,
            )

        restored_paths = []
        for path in record.changed_paths:
            before = record.before[path]
            if before.exists:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                atomic_write_bytes(path, base64.b64decode(before.content_b64 or ""), backup=True)
            elif os.path.exists(path):
                os.unlink(path)
            restored_paths.append(path)

        record.metadata["undone_at"] = time.time()
        self.save(record)
        count = len(restored_paths)
        plural = "" if count == 1 else "s"
        return CheckpointUndoResult(
            ok=True,
            message=f"Undid checkpoint {record.id}; restored {count} path{plural}.",
            checkpoint_id=record.id,
            restored_paths=restored_paths,
        )

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

    def _undo_conflicts(self, record: CheckpointRecord) -> list[str]:
        conflicts = []
        for path in record.changed_paths:
            before = record.before.get(path)
            after = record.after.get(path)
            if before is None or after is None:
                conflicts.append(f"{path}: incomplete checkpoint record")
                continue
            if before.skipped or after.skipped:
                reason = before.skip_reason or after.skip_reason or "snapshot skipped"
                conflicts.append(f"{path}: cannot restore skipped snapshot ({reason})")
                continue
            if before.exists and not before.content_b64:
                conflicts.append(f"{path}: checkpoint does not contain original content")
                continue
            current = FileSnapshot.capture(path)
            if self._snapshot_hash(current) != self._snapshot_hash(after):
                conflicts.append(f"{path}: changed since checkpoint")
        return conflicts
