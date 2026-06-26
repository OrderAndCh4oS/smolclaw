from __future__ import annotations

import os
import inspect
import time
from dataclasses import dataclass, field
from typing import Literal

from app.storage_paths import (
    atomic_write_json,
    atomic_write_text,
    contained_storage_path,
    load_json_with_backup,
    safe_storage_stem,
)
from app.utilities import make_hash


MemoryDocumentKind = Literal["memory", "journal", "session", "research", "external"]


@dataclass(frozen=True)
class StoredMemoryDocument:
    source_id: str
    path: str | None
    content: str
    kind: MemoryDocumentKind
    ingested: bool


@dataclass
class MemoryIngestionJob:
    job_id: str
    source_id: str
    kind: MemoryDocumentKind
    status: Literal["running", "complete", "failed"] = "running"
    stage: str = "started"
    path: str | None = None
    source: str | None = None
    error: str = ""
    stages: list[str] = field(default_factory=lambda: ["started"])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "source_id": self.source_id,
            "kind": self.kind,
            "status": self.status,
            "stage": self.stage,
            "path": self.path,
            "source": self.source,
            "error": self.error,
            "stages": list(self.stages),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryIngestionJob":
        return cls(
            job_id=str(data.get("job_id") or ""),
            source_id=str(data.get("source_id") or ""),
            kind=str(data.get("kind") or "memory"),  # type: ignore[arg-type]
            status=str(data.get("status") or "running"),  # type: ignore[arg-type]
            stage=str(data.get("stage") or "started"),
            path=str(data.get("path")) if data.get("path") else None,
            source=str(data.get("source")) if data.get("source") else None,
            error=str(data.get("error") or ""),
            stages=[str(item) for item in data.get("stages") or ["started"]],
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
        )


class MemoryDocumentService:
    """Owns durable memory document files and their SmolRAG source lifecycle."""

    def __init__(
        self,
        smol_rag,
        *,
        memory_dir: str | None = None,
        research_dir: str | None = None,
        ingestion_jobs_dir: str | None = None,
    ):
        self.smol_rag = smol_rag
        self.memory_dir = memory_dir
        self.research_dir = research_dir
        self.ingestion_jobs_dir = ingestion_jobs_dir

    def memory_source_id(self, content: str, source_id: str | None = None) -> str:
        return self._normalize_source_id(source_id or make_hash(content, "mem-"))

    def journal_source_id(self, session_key: str) -> str:
        return self._normalize_source_id(f"journal-{session_key}")

    def session_source_id(self, session_key: str) -> str:
        return self._normalize_source_id(f"session-{session_key}")

    def research_source_id(self, stem: str) -> str:
        return f"research/{safe_storage_stem(stem)}"

    def external_source_id(self, source_id: str) -> str:
        return self._normalize_source_id(source_id)

    def resolve_document_path(
        self,
        kind: MemoryDocumentKind,
        source_id: str,
        *,
        extension: str = ".md",
    ) -> str:
        directory = self._directory_for_kind(kind)
        if not directory:
            raise ValueError(f"No storage directory configured for {kind} documents.")
        stem = self._file_stem_for_source(kind, source_id)
        return contained_storage_path(directory, stem, extension)

    async def store_document(
        self,
        content: str,
        *,
        kind: MemoryDocumentKind,
        source_id: str | None = None,
        extension: str = ".md",
        ingest: bool = True,
        source: str | None = None,
        replace: bool = True,
        save: bool = True,
    ) -> StoredMemoryDocument:
        final_source_id = self._source_id_for_kind(kind, content, source_id)
        job = (
            self._start_ingestion_job(final_source_id, kind, source=source)
            if ingest and self.smol_rag is not None
            else None
        )
        path: str | None = None
        try:
            if kind != "external" and self._directory_for_kind(kind):
                path = self.resolve_document_path(kind, final_source_id, extension=extension)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                atomic_write_text(path, content)
                if job is not None:
                    job.path = path
                    self._advance_ingestion_job(job, "document_written")

            if ingest and self.smol_rag is not None:
                if replace:
                    self._advance_ingestion_job(job, "remove_existing")
                    await self._maybe_await(self.smol_rag.remove_document_by_source(final_source_id))
                ingest_kwargs = {"source_id": final_source_id}
                if source is not None:
                    ingest_kwargs["source"] = source
                if save is not True:
                    ingest_kwargs["save"] = save
                self._advance_ingestion_job(job, "ingest")
                await self._maybe_await(self.smol_rag.ingest_text(content, **ingest_kwargs))
                self._complete_ingestion_job(job)
        except Exception as exc:
            self._fail_ingestion_job(job, exc)
            raise

        return StoredMemoryDocument(
            source_id=final_source_id,
            path=path,
            content=content,
            kind=kind,
            ingested=bool(ingest and self.smol_rag is not None),
        )

    async def ingest_external_text(
        self,
        content: str,
        *,
        source_id: str,
        source: str | None = None,
        replace: bool = True,
        save: bool = True,
    ) -> StoredMemoryDocument:
        return await self.store_document(
            content,
            kind="external",
            source_id=source_id,
            ingest=True,
            source=source,
            replace=replace,
            save=save,
        )

    def load_ingestion_job(self, job_id: str) -> MemoryIngestionJob | None:
        if not self.ingestion_jobs_dir:
            return None
        data = load_json_with_backup(self._ingestion_job_path(job_id))
        return MemoryIngestionJob.from_dict(data) if isinstance(data, dict) else None

    def list_ingestion_jobs(self, *, status: str | None = None) -> list[MemoryIngestionJob]:
        if not self.ingestion_jobs_dir or not os.path.isdir(self.ingestion_jobs_dir):
            return []
        jobs: list[MemoryIngestionJob] = []
        for name in sorted(os.listdir(self.ingestion_jobs_dir)):
            if not name.endswith(".json"):
                continue
            data = load_json_with_backup(os.path.join(self.ingestion_jobs_dir, name))
            if not isinstance(data, dict):
                continue
            job = MemoryIngestionJob.from_dict(data)
            if status is None or job.status == status:
                jobs.append(job)
        return sorted(jobs, key=lambda item: item.updated_at, reverse=True)

    async def repair_ingestion_job(
        self,
        job_id: str,
        *,
        content: str | None = None,
        save: bool = True,
    ) -> StoredMemoryDocument:
        job = self.load_ingestion_job(job_id)
        if job is None:
            raise ValueError(f"No ingestion job found: {job_id}")
        repair_content = content
        if repair_content is None and job.path:
            with open(job.path, encoding="utf-8") as handle:
                repair_content = handle.read()
        if repair_content is None:
            raise ValueError("Content is required to repair an external ingestion job.")
        return await self.store_document(
            repair_content,
            kind=job.kind,
            source_id=job.source_id,
            ingest=True,
            source=job.source,
            replace=True,
            save=save,
        )

    def _source_id_for_kind(
        self,
        kind: MemoryDocumentKind,
        content: str,
        source_id: str | None,
    ) -> str:
        if kind == "research":
            value = source_id or make_hash(content, "research-")
            if value.startswith("research/"):
                value = value.split("/", 1)[1]
            return self.research_source_id(value)
        if kind == "memory":
            return self.memory_source_id(content, source_id)
        return self._normalize_source_id(source_id or make_hash(content, f"{kind}-"))

    def _normalize_source_id(self, source_id: str) -> str:
        return safe_storage_stem(source_id)

    def _directory_for_kind(self, kind: MemoryDocumentKind) -> str | None:
        if kind == "research":
            return self.research_dir
        if kind == "external":
            return None
        return self.memory_dir

    def _file_stem_for_source(self, kind: MemoryDocumentKind, source_id: str) -> str:
        if kind == "research" and source_id.startswith("research/"):
            source_id = source_id.split("/", 1)[1]
        return safe_storage_stem(source_id)

    def _ingestion_job_path(self, job_id: str) -> str:
        if not self.ingestion_jobs_dir:
            raise ValueError("No ingestion job directory configured.")
        return contained_storage_path(self.ingestion_jobs_dir, job_id, ".json")

    def _start_ingestion_job(
        self,
        source_id: str,
        kind: MemoryDocumentKind,
        *,
        source: str | None,
    ) -> MemoryIngestionJob | None:
        if not self.ingestion_jobs_dir:
            return None
        job = MemoryIngestionJob(
            job_id=f"{safe_storage_stem(source_id)}-{int(time.time() * 1000)}",
            source_id=source_id,
            kind=kind,
            source=source,
        )
        self._save_ingestion_job(job)
        return job

    def _advance_ingestion_job(self, job: MemoryIngestionJob | None, stage: str):
        if job is None:
            return
        job.stage = stage
        job.updated_at = time.time()
        if stage not in job.stages:
            job.stages.append(stage)
        self._save_ingestion_job(job)

    def _complete_ingestion_job(self, job: MemoryIngestionJob | None):
        if job is None:
            return
        job.status = "complete"
        job.error = ""
        self._advance_ingestion_job(job, "complete")

    def _fail_ingestion_job(self, job: MemoryIngestionJob | None, exc: Exception):
        if job is None:
            return
        job.status = "failed"
        job.error = str(exc)
        self._advance_ingestion_job(job, "failed")

    def _save_ingestion_job(self, job: MemoryIngestionJob):
        if not self.ingestion_jobs_dir:
            return
        atomic_write_json(self._ingestion_job_path(job.job_id), job.to_dict())

    async def _maybe_await(self, value):
        if inspect.isawaitable(value):
            return await value
        return value
