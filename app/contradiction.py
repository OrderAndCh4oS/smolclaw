"""Contradiction detection and belief revision for the knowledge graph.

Inspired by KARMA (arxiv:2502.06472) — structural checks first, LLM adjudication
only when needed. User-explicit input always outranks automatic extraction.
"""

import hashlib
import json
import logging
import time

import numpy as np

from app.definitions import KG_SEP
from app.prompts import get_contradiction_adjudication_prompt
from app.utilities import extract_json_from_text, split_string_by_multi_markers

logger = logging.getLogger("smolclaw.contradiction")

# Similarity threshold: below this, descriptions are considered potentially conflicting
SIMILARITY_THRESHOLD = 0.75


def _cosine_similarity(a, b) -> float:
    """Cosine similarity between two vectors."""
    a = np.asarray(a, dtype=np.float32).flatten()
    b = np.asarray(b, dtype=np.float32).flatten()
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _make_contradiction_id(entity_name: str, new_value: str, timestamp: float) -> str:
    raw = f"{entity_name}|{new_value}|{timestamp}"
    return "ctr-" + hashlib.md5(raw.encode()).hexdigest()[:16]


class ContradictionDetector:
    """Detects and manages contradictions in the knowledge graph.

    Two-phase detection:
      Phase A — Embedding similarity (structural check, no LLM)
      Phase B — LLM adjudication (only when structural check flags a candidate)

    Resolution strategy (simplified from KARMA):
      agree + any source        → silently merge
      contradict + extraction   → auto-dismiss
      contradict + user         → store as pending
      ambiguous + any           → store as pending
    """

    def __init__(self, graph_store, contradiction_store, llm, embedding_fn):
        self.graph = graph_store
        self.store = contradiction_store
        self.llm = llm
        self.embedding_fn = embedding_fn
        self._hook_fn = None

    def set_hook(self, hook_fn):
        """Set a callback fired when a contradiction is detected."""
        self._hook_fn = hook_fn

    async def _fire_hook(self, contradiction: dict):
        if self._hook_fn:
            try:
                await self._hook_fn(contradiction)
            except Exception as e:
                logger.warning(f"Contradiction hook error: {e}")

    # ── Public API ──────────────────────────────────────────────

    async def check_entity(
        self, name: str, category: str, description: str,
        excerpt_id: str, source: str = "extraction",
    ) -> list[dict]:
        """Check if a new entity description contradicts existing KG data."""
        existing = self.graph.get_node(name)
        if not existing:
            return []

        existing_desc = existing.get("description", "")
        existing_descriptions = split_string_by_multi_markers(existing_desc, [KG_SEP])
        existing_descriptions = [d for d in existing_descriptions if d.strip()]
        if not existing_descriptions:
            return []

        # Phase A: structural check
        is_candidate = await self._structural_check(description, existing_descriptions)
        if not is_candidate:
            return []

        # Phase B: LLM adjudication
        verdict, confidence, reasoning = await self._llm_adjudicate(
            name, existing_descriptions, description,
        )

        # Find provenance for existing value
        existing_excerpt_id = existing.get("excerpt_id", "")
        first_existing_excerpt = split_string_by_multi_markers(existing_excerpt_id, [KG_SEP])
        first_existing_excerpt = first_existing_excerpt[0] if first_existing_excerpt else ""

        now = time.time()
        record = {
            "id": _make_contradiction_id(name, description, now),
            "entity_name": name,
            "edge_key": None,
            "kind": "entity_description",
            "existing_value": existing_desc,
            "new_value": description,
            "existing_excerpt_id": first_existing_excerpt,
            "new_excerpt_id": excerpt_id,
            "status": self._decide_status(verdict, source),
            "verdict": verdict,
            "confidence": confidence,
            "resolution_note": reasoning,
            "source": source,
            "created_at": now,
            "resolved_at": now if verdict == "agree" else None,
        }

        # Category conflict check
        existing_cat = existing.get("category", "")
        existing_categories = split_string_by_multi_markers(existing_cat, [KG_SEP])
        if category and existing_categories and category not in existing_categories:
            cat_record = {
                **record,
                "id": _make_contradiction_id(name, f"cat:{category}", now),
                "kind": "entity_category",
                "existing_value": existing_cat,
                "new_value": category,
                "status": "pending" if source == "user" else "dismissed",
                "verdict": "ambiguous",
                "confidence": 0.5,
                "resolution_note": f"Category mismatch: existing={existing_cat}, new={category}",
            }
            await self._store_record(cat_record)

        if verdict != "agree":
            await self._store_record(record)
            await self._fire_hook(record)

        return [record]

    async def check_relationship(
        self, source: str, target: str, description: str,
        excerpt_id: str, source_type: str = "extraction",
    ) -> list[dict]:
        """Check if a new relationship description contradicts existing KG data."""
        sorted_source, sorted_target = sorted((source, target))
        existing = self.graph.get_edge((sorted_source, sorted_target))
        if not existing:
            return []

        existing_desc = existing.get("description", "")
        existing_descriptions = split_string_by_multi_markers(existing_desc, [KG_SEP])
        existing_descriptions = [d for d in existing_descriptions if d.strip()]
        if not existing_descriptions:
            return []

        is_candidate = await self._structural_check(description, existing_descriptions)
        if not is_candidate:
            return []

        edge_label = f"{sorted_source}||{sorted_target}"
        verdict, confidence, reasoning = await self._llm_adjudicate(
            edge_label, existing_descriptions, description,
        )

        existing_excerpt_id = existing.get("excerpt_id", "")
        first_existing_excerpt = split_string_by_multi_markers(existing_excerpt_id, [KG_SEP])
        first_existing_excerpt = first_existing_excerpt[0] if first_existing_excerpt else ""

        now = time.time()
        record = {
            "id": _make_contradiction_id(edge_label, description, now),
            "entity_name": None,
            "edge_key": edge_label,
            "kind": "relationship_description",
            "existing_value": existing_desc,
            "new_value": description,
            "existing_excerpt_id": first_existing_excerpt,
            "new_excerpt_id": excerpt_id,
            "status": self._decide_status(verdict, source_type),
            "verdict": verdict,
            "confidence": confidence,
            "resolution_note": reasoning,
            "source": source_type,
            "created_at": now,
            "resolved_at": now if verdict == "agree" else None,
        }

        if verdict != "agree":
            await self._store_record(record)
            await self._fire_hook(record)

        return [record]

    async def get_pending(self, limit: int = 10) -> list[dict]:
        """Get pending contradictions."""
        all_records = await self.store.get_all()
        pending = [
            v for v in all_records.values()
            if isinstance(v, dict) and v.get("status") == "pending"
        ]
        pending.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return pending[:limit]

    async def get_for_entity(self, entity_name: str) -> list[dict]:
        """Get all contradictions for a specific entity."""
        all_records = await self.store.get_all()
        return [
            v for v in all_records.values()
            if isinstance(v, dict) and v.get("entity_name") == entity_name
        ]

    async def resolve(
        self, contradiction_id: str, resolution: str, note: str = None,
    ) -> dict | None:
        """Resolve a contradiction.

        resolution: "keep_existing" | "keep_new" | "merge" | "dismiss"
        """
        record = await self.store.get_by_key(contradiction_id)
        if not record:
            return None

        status_map = {
            "keep_existing": "resolved_kept_existing",
            "keep_new": "resolved_kept_new",
            "merge": "resolved_merged",
            "dismiss": "dismissed",
        }
        record["status"] = status_map.get(resolution, "dismissed")
        record["resolved_at"] = time.time()
        if note:
            record["resolution_note"] = note

        # Apply resolution to KG
        if resolution == "keep_new":
            await self._apply_keep_new(record)
        elif resolution == "merge":
            await self._apply_merge(record)
        # keep_existing and dismiss: no KG changes needed

        await self.store.add(contradiction_id, record)
        return record

    async def get_count(self, status: str = "pending") -> int:
        """Count contradictions by status."""
        all_records = await self.store.get_all()
        return sum(
            1 for v in all_records.values()
            if isinstance(v, dict) and v.get("status") == status
        )

    async def expire_old(self, max_age_days: float = 90.0) -> int:
        """Auto-dismiss stale pending contradictions."""
        cutoff = time.time() - (max_age_days * 86400)
        all_records = await self.store.get_all()
        expired = 0
        for key, record in all_records.items():
            if not isinstance(record, dict):
                continue
            if record.get("status") != "pending":
                continue
            if record.get("created_at", 0) < cutoff:
                record["status"] = "dismissed"
                record["resolved_at"] = time.time()
                record["resolution_note"] = f"Auto-expired after {max_age_days} days"
                await self.store.add(key, record)
                expired += 1
        if expired:
            logger.info(f"Expired {expired} stale contradictions older than {max_age_days} days")
        return expired

    # ── Internal ────────────────────────────────────────────────

    @staticmethod
    def _decide_status(verdict: str, source: str) -> str:
        """Decide contradiction status based on verdict and source."""
        if verdict == "agree":
            return "resolved_kept_existing"
        if verdict == "contradict":
            if source == "user":
                return "pending"
            return "dismissed"
        # ambiguous
        return "pending"

    async def _structural_check(
        self, new_description: str, existing_descriptions: list[str],
    ) -> bool:
        """Phase A: embedding similarity check.

        Returns True if the new description is a contradiction candidate
        (low similarity to ALL existing descriptions).
        """
        new_embedding = await self.embedding_fn(new_description)

        for desc in existing_descriptions:
            desc_embedding = await self.embedding_fn(desc)
            sim = _cosine_similarity(new_embedding, desc_embedding)
            if sim >= SIMILARITY_THRESHOLD:
                # High similarity to at least one existing description — compatible
                return False

        # Low similarity to all existing descriptions — potential conflict
        return True

    async def _llm_adjudicate(
        self, entity_or_edge: str,
        existing_descriptions: list[str],
        new_description: str,
    ) -> tuple[str, float, str]:
        """Phase B: LLM adjudication for ambiguous cases.

        Returns (verdict, confidence, reasoning).
        """
        prompt = get_contradiction_adjudication_prompt(
            entity_or_edge, existing_descriptions, new_description,
        )
        try:
            result = await self.llm(prompt)
            parsed = extract_json_from_text(result)
            if parsed:
                verdict = parsed.get("verdict", "ambiguous")
                if verdict not in ("agree", "contradict", "ambiguous"):
                    verdict = "ambiguous"
                confidence = float(parsed.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))
                reasoning = parsed.get("reasoning", "")
                return verdict, confidence, reasoning
        except Exception as e:
            logger.warning(f"LLM adjudication failed: {e}")

        return "ambiguous", 0.5, "LLM adjudication failed"

    async def _store_record(self, record: dict):
        """Store a contradiction record."""
        await self.store.add(record["id"], record)
        logger.info(
            f"Contradiction {record['id']}: {record['kind']} "
            f"verdict={record['verdict']} status={record['status']}"
        )

    async def _apply_keep_new(self, record: dict):
        """Replace existing KG value with new value."""
        kind = record.get("kind")
        new_value = record.get("new_value", "")

        if kind == "entity_description" and record.get("entity_name"):
            node = self.graph.get_node(record["entity_name"])
            if node:
                await self.graph.async_add_node(
                    record["entity_name"],
                    **{**node, "description": new_value},
                )
        elif kind == "entity_category" and record.get("entity_name"):
            node = self.graph.get_node(record["entity_name"])
            if node:
                await self.graph.async_add_node(
                    record["entity_name"],
                    **{**node, "category": new_value},
                )
        elif kind == "relationship_description" and record.get("edge_key"):
            parts = record["edge_key"].split("||")
            if len(parts) == 2:
                edge = self.graph.get_edge((parts[0], parts[1]))
                if edge:
                    await self.graph.async_add_edge(
                        parts[0], parts[1],
                        **{**edge, "description": new_value},
                    )

    async def _apply_merge(self, record: dict):
        """Append new value to existing KG value."""
        kind = record.get("kind")
        new_value = record.get("new_value", "")

        if kind == "entity_description" and record.get("entity_name"):
            node = self.graph.get_node(record["entity_name"])
            if node:
                existing_desc = node.get("description", "")
                merged = f"{existing_desc}{KG_SEP}{new_value}" if existing_desc else new_value
                await self.graph.async_add_node(
                    record["entity_name"],
                    **{**node, "description": merged},
                )
        elif kind == "relationship_description" and record.get("edge_key"):
            parts = record["edge_key"].split("||")
            if len(parts) == 2:
                edge = self.graph.get_edge((parts[0], parts[1]))
                if edge:
                    existing_desc = edge.get("description", "")
                    merged = f"{existing_desc}{KG_SEP}{new_value}" if existing_desc else new_value
                    await self.graph.async_add_edge(
                        parts[0], parts[1],
                        **{**edge, "description": merged},
                    )
