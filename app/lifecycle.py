import logging

logger = logging.getLogger("smolclaw.lifecycle")


class MemoryLifecycleManager:
    """Manages memory promotion (importance only goes up, never down).
    Temporal relevance is handled by recency scoring at query time."""

    def __init__(self, smol_rag):
        self.smol_rag = smol_rag

    async def promote(self, excerpt_id: str, boost: float = 0.1) -> float:
        """Boost importance of a memory on access. Auto-promotes T2→T1 at importance >= 0.8.
        Returns new importance."""
        data = await self.smol_rag.get_excerpt(excerpt_id)
        if not data:
            return 0.0
        old_importance = data.get("importance", 0.5)
        new_importance = min(old_importance + boost, 1.0)
        data["importance"] = new_importance
        # Auto-promote: T2 → T1 when importance crosses 0.8
        tier = data.get("tier", 2)
        if tier == 2 and new_importance >= 0.8:
            data["tier"] = 1
            logger.info(f"Auto-promoted {excerpt_id} from tier 2 → tier 1 (importance {new_importance:.2f})")
        await self.smol_rag.update_excerpt(excerpt_id, data)
        logger.info(f"Promoted {excerpt_id}: {old_importance:.2f} -> {new_importance:.2f}")
        return new_importance



async def expire_old_contradictions(detector, max_age_days: float = 90.0) -> int:
    """Auto-dismiss stale pending contradictions. Suitable as a session-end hook."""
    return await detector.expire_old(max_age_days=max_age_days)
