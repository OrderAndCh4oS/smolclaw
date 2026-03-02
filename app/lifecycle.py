import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger("smolclaw.lifecycle")


class MemoryLifecycleManager:
    """Manages memory promotion, decay, consolidation, contradiction detection, and audit trails."""

    def __init__(self, smol_rag, llm=None):
        self.smol_rag = smol_rag
        self.llm = llm

    async def promote(self, excerpt_id: str, boost: float = 0.1) -> float:
        """Boost importance of a memory on access. Returns new importance."""
        data = await self.smol_rag.excerpt_kv.get_by_key(excerpt_id)
        if not data:
            return 0.0
        old_importance = data.get("importance", 0.5)
        new_importance = min(old_importance + boost, 1.0)
        data["importance"] = new_importance
        await self.smol_rag.excerpt_kv.add(excerpt_id, data)
        logger.info(f"Promoted {excerpt_id}: {old_importance:.2f} -> {new_importance:.2f}")
        return new_importance

    async def decay(self, threshold_days: float = 30.0, factor: float = 0.95) -> int:
        """Reduce importance of stale unreferenced memories. Returns count of decayed items."""
        cutoff = time.time() - (threshold_days * 86400)
        decayed_count = 0

        all_data = await self.smol_rag.excerpt_kv.get_all()
        for key in all_data:
            data = await self.smol_rag.excerpt_kv.get_by_key(key)
            if not data:
                continue
            indexed_at = data.get("indexed_at", 0)
            if indexed_at < cutoff:
                old_importance = data.get("importance", 0.5)
                new_importance = old_importance * factor
                if abs(new_importance - old_importance) > 0.001:
                    data["importance"] = new_importance
                    await self.smol_rag.excerpt_kv.add(key, data)
                    decayed_count += 1

        logger.info(f"Decayed {decayed_count} stale memories (threshold: {threshold_days}d, factor: {factor})")
        return decayed_count

    async def consolidate(self, excerpt_ids: List[str]) -> Optional[str]:
        """Merge related memories via LLM. Returns the merged content or None."""
        if not self.llm or len(excerpt_ids) < 2:
            return None

        contents = []
        for eid in excerpt_ids:
            data = await self.smol_rag.excerpt_kv.get_by_key(eid)
            if data:
                contents.append(data.get("excerpt", ""))

        if not contents:
            return None

        prompt = (
            "Consolidate the following related memories into a single, concise memory "
            "that preserves all important facts and relationships:\n\n"
            + "\n---\n".join(contents)
            + "\n\nConsolidated memory:"
        )

        merged = await self.llm.get_completion(prompt, use_cache=False)
        logger.info(f"Consolidated {len(excerpt_ids)} memories into one")
        return merged.strip()

    async def detect_contradictions(self, excerpt_id: str) -> List[Dict]:
        """Find potentially contradicting facts in the graph neighborhood."""
        data = await self.smol_rag.excerpt_kv.get_by_key(excerpt_id)
        if not data:
            return []

        excerpt_text = data.get("excerpt", "")
        if not excerpt_text:
            return []

        # Find related excerpts via vector similarity
        embedding = await self.smol_rag.rate_limited_get_embedding(excerpt_text)
        results = await self.smol_rag.embeddings_db.query(embedding, top_k=10)

        contradictions = []
        for r in results:
            other_id = r.get("__id__")
            if other_id == excerpt_id:
                continue
            other_data = await self.smol_rag.excerpt_kv.get_by_key(other_id)
            if not other_data:
                continue

            # If we have an LLM, check for actual contradiction
            if self.llm:
                other_text = other_data.get("excerpt", "")
                check_prompt = (
                    f"Do these two statements contradict each other? "
                    f"Answer 'yes' or 'no' and explain briefly.\n\n"
                    f"Statement 1: {excerpt_text}\n"
                    f"Statement 2: {other_text}\n\n"
                    f"Answer:"
                )
                response = await self.llm.get_completion(check_prompt, use_cache=True)
                if response.strip().lower().startswith("yes"):
                    contradictions.append({
                        "excerpt_id": other_id,
                        "excerpt": other_text,
                        "explanation": response.strip(),
                    })
            else:
                # Without LLM, just return similar items for manual review
                contradictions.append({
                    "excerpt_id": other_id,
                    "excerpt": other_data.get("excerpt", ""),
                    "explanation": "Similar content found (manual review needed)",
                })

        return contradictions

    async def get_audit_trail(self, excerpt_id: str) -> Dict:
        """Return provenance chain for an excerpt."""
        data = await self.smol_rag.excerpt_kv.get_by_key(excerpt_id)
        if not data:
            return {"error": f"Excerpt not found: {excerpt_id}"}

        doc_id = data.get("doc_id")
        source = None
        if doc_id:
            source = await self.smol_rag.source_doc_map.get_left_single(doc_id)

        return {
            "excerpt_id": excerpt_id,
            "doc_id": doc_id,
            "source": source,
            "indexed_at": data.get("indexed_at"),
            "memory_type": data.get("memory_type"),
            "importance": data.get("importance"),
            "confidence": data.get("confidence"),
        }
