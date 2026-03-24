import logging

from app.lifecycle import expire_old_contradictions

logger = logging.getLogger("smolclaw.lifecycle_hooks")


class ContradictionExpiryHook:
    """Fires on session end to auto-dismiss stale pending contradictions."""

    def __init__(self, contradiction_detector, max_age_days=90.0):
        self.detector = contradiction_detector
        self.max_age_days = max_age_days

    async def __call__(self, context):
        count = await expire_old_contradictions(self.detector, self.max_age_days)
        if count > 0:
            logger.info(f"Expired {count} stale contradictions")
