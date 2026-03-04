import logging

from app.lifecycle import MemoryLifecycleManager

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
