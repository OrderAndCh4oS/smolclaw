import logging
import time

logger = logging.getLogger("smolclaw.lifecycle")


class MemoryLifecycleManager:
    """Manages memory promotion and decay."""

    def __init__(self, smol_rag):
        self.smol_rag = smol_rag

    async def promote(self, excerpt_id: str, boost: float = 0.1) -> float:
        """Boost importance of a memory on access. Auto-promotes T2→T1 at importance >= 0.8.
        Returns new importance."""
        data = await self.smol_rag.excerpt_kv.get_by_key(excerpt_id)
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
        await self.smol_rag.excerpt_kv.add(excerpt_id, data)
        logger.info(f"Promoted {excerpt_id}: {old_importance:.2f} -> {new_importance:.2f}")
        return new_importance

    # Tier-specific decay factors: T0 never decays, T1 slow, T2 normal
    TIER_DECAY_FACTORS = {0: None, 1: 0.98, 2: 0.95}

    async def decay(self, threshold_days: float = 30.0, factor: float = 0.95) -> int:
        """Reduce importance of stale unreferenced memories. Tier-aware:
        T0 (identity) never decays, T1 (core) decays slowly, T2 (working) decays normally.
        Returns count of decayed items.
        """
        cutoff = time.time() - (threshold_days * 86400)
        excerpt_kv = self.smol_rag.excerpt_kv

        # Use batch SQL update if available (SqliteKvStore)
        from app.sqlite_store import SqliteKvStore
        if isinstance(excerpt_kv, SqliteKvStore):
            # Run separate decay passes per tier (skip T0)
            total = 0
            for tier, tier_factor in self.TIER_DECAY_FACTORS.items():
                if tier_factor is None:
                    continue  # T0 never decays
                count = await excerpt_kv.batch_decay(tier_factor, cutoff, tier=tier)
                total += count
            logger.info(f"Decayed {total} stale memories (threshold: {threshold_days}d, tier-aware)")
            return total

        # Fallback for non-SQLite stores
        decayed_count = 0
        all_data = await excerpt_kv.get_all()
        for key in all_data:
            data = await excerpt_kv.get_by_key(key)
            if not data:
                continue
            tier = data.get("tier", 2)
            tier_factor = self.TIER_DECAY_FACTORS.get(tier, factor)
            if tier_factor is None:
                continue  # T0 never decays
            indexed_at = data.get("indexed_at", 0)
            if indexed_at < cutoff:
                old_importance = data.get("importance", 0.5)
                new_importance = old_importance * tier_factor
                if abs(new_importance - old_importance) > 0.001:
                    data["importance"] = new_importance
                    await excerpt_kv.add(key, data)
                    decayed_count += 1

        logger.info(f"Decayed {decayed_count} stale memories (threshold: {threshold_days}d, tier-aware)")
        return decayed_count


async def expire_old_contradictions(detector, max_age_days: float = 90.0) -> int:
    """Auto-dismiss stale pending contradictions. Suitable as a session-end hook."""
    return await detector.expire_old(max_age_days=max_age_days)
