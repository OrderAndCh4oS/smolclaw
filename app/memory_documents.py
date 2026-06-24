from __future__ import annotations

import os
import inspect
from dataclasses import dataclass
from typing import Literal

from app.storage_paths import atomic_write_text, contained_storage_path, safe_storage_stem
from app.utilities import make_hash


MemoryDocumentKind = Literal["memory", "journal", "session", "research", "external"]


@dataclass(frozen=True)
class StoredMemoryDocument:
    source_id: str
    path: str | None
    content: str
    kind: MemoryDocumentKind
    ingested: bool


class MemoryDocumentService:
    """Owns durable memory document files and their SmolRAG source lifecycle."""

    def __init__(
        self,
        smol_rag,
        *,
        memory_dir: str | None = None,
        research_dir: str | None = None,
    ):
        self.smol_rag = smol_rag
        self.memory_dir = memory_dir
        self.research_dir = research_dir

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
        path: str | None = None
        if kind != "external" and self._directory_for_kind(kind):
            path = self.resolve_document_path(kind, final_source_id, extension=extension)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            atomic_write_text(path, content)

        if ingest and self.smol_rag is not None:
            if replace:
                await self._maybe_await(self.smol_rag.remove_document_by_source(final_source_id))
            ingest_kwargs = {"source_id": final_source_id}
            if source is not None:
                ingest_kwargs["source"] = source
            if save is not True:
                ingest_kwargs["save"] = save
            await self._maybe_await(self.smol_rag.ingest_text(content, **ingest_kwargs))

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

    async def _maybe_await(self, value):
        if inspect.isawaitable(value):
            return await value
        return value
