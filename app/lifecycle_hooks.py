import logging

from app.lifecycle import MemoryLifecycleManager, expire_old_contradictions

logger = logging.getLogger("smolclaw.lifecycle_hooks")


class MemoryDecayHook:
    """Fires on session end to decay stale memories."""

    def __init__(self, smol_rag, threshold_days=30.0, factor=0.95):
        self.manager = MemoryLifecycleManager(smol_rag)
        self.threshold_days = threshold_days
        self.factor = factor

    async def __call__(self, context):
        count = await self.manager.decay(self.threshold_days, self.factor)
        if count > 0:
            logger.info(f"Decayed {count} memories")


class ContradictionExpiryHook:
    """Fires on session end to auto-dismiss stale pending contradictions."""

    def __init__(self, contradiction_detector, max_age_days=90.0):
        self.detector = contradiction_detector
        self.max_age_days = max_age_days

    async def __call__(self, context):
        count = await expire_old_contradictions(self.detector, self.max_age_days)
        if count > 0:
            logger.info(f"Expired {count} stale contradictions")
