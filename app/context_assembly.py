import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.context_builder import ContextBuilder
from app.utilities import get_encoded_tokens

logger = logging.getLogger("smolclaw.context_assembly")


@dataclass
class InclusionRecord:
    excerpt_id: str
    included: bool
    reason: str
    score: float
    token_count: int


@dataclass
class AssemblyManifest:
    total_budget: int
    used_tokens: int
    included: List[InclusionRecord] = field(default_factory=list)
    excluded: List[InclusionRecord] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Context assembly: {len(self.included)} included, "
            f"{len(self.excluded)} excluded, "
            f"{self.used_tokens}/{self.total_budget} tokens used"
        )


class ContextAssembler(ContextBuilder):
    """Budget-aware context builder that retrieves memories from SmolRAG
    and prioritizes by importance * confidence * recency decay."""

    def __init__(
        self,
        smol_rag,
        token_budget: int = 4000,
        bootstrap_path: str = None,
        persona: str = None,
        shared_bootstrap_path: str = None,
        decay_half_life_days: float = 30.0,
    ):
        super().__init__(
            bootstrap_path=bootstrap_path,
            persona=persona,
            shared_bootstrap_path=shared_bootstrap_path,
        )
        self.smol_rag = smol_rag
        self.token_budget = token_budget
        self.decay_half_life_days = decay_half_life_days
        self.last_manifest: Optional[AssemblyManifest] = None

    def _recency_decay(self, indexed_at: float) -> float:
        """Exponential decay based on age in days."""
        if not indexed_at:
            return 0.5
        age_days = (time.time() - indexed_at) / 86400.0
        return math.exp(-0.693 * age_days / self.decay_half_life_days)

    def _score_excerpt(self, excerpt_data: dict) -> float:
        """Score an excerpt by importance * confidence * recency_decay."""
        importance = excerpt_data.get("importance", 0.5)
        confidence = excerpt_data.get("confidence", 1.0)
        indexed_at = excerpt_data.get("indexed_at", 0)
        recency = self._recency_decay(indexed_at)
        return importance * confidence * recency

    async def retrieve_context(self, query: str, top_k: int = 20) -> tuple[str, AssemblyManifest]:
        """Retrieve and assemble context from SmolRAG within token budget."""
        manifest = AssemblyManifest(total_budget=self.token_budget, used_tokens=0)

        # Query SmolRAG for relevant excerpts
        results = await self.smol_rag.embeddings_db.query(
            await self.smol_rag.rate_limited_get_embedding(query),
            top_k=top_k,
        )

        # Gather excerpt data and score each
        scored_items = []
        for r in results:
            excerpt_id = r.get("__id__")
            if not excerpt_id:
                continue
            excerpt_data = await self.smol_rag.excerpt_kv.get_by_key(excerpt_id)
            if not excerpt_data:
                continue
            score = self._score_excerpt(excerpt_data)
            scored_items.append((excerpt_id, excerpt_data, score))

        # Sort by score descending
        scored_items.sort(key=lambda x: x[2], reverse=True)

        # Build context within budget — summaries first, then expand
        context_parts = []
        tokens_used = 0

        for excerpt_id, data, score in scored_items:
            summary = data.get("summary", "")
            excerpt_text = data.get("excerpt", "")

            # Try summary first
            summary_tokens = len(get_encoded_tokens(summary)) if summary else 0
            excerpt_tokens = len(get_encoded_tokens(excerpt_text)) if excerpt_text else 0

            # Prefer full excerpt if it fits, otherwise summary
            if tokens_used + excerpt_tokens <= self.token_budget:
                context_parts.append(excerpt_text)
                tokens_used += excerpt_tokens
                manifest.included.append(InclusionRecord(
                    excerpt_id=excerpt_id, included=True,
                    reason="full excerpt fits budget", score=score,
                    token_count=excerpt_tokens,
                ))
            elif tokens_used + summary_tokens <= self.token_budget and summary:
                context_parts.append(f"[Summary] {summary}")
                tokens_used += summary_tokens
                manifest.included.append(InclusionRecord(
                    excerpt_id=excerpt_id, included=True,
                    reason="summary fits budget", score=score,
                    token_count=summary_tokens,
                ))
            else:
                manifest.excluded.append(InclusionRecord(
                    excerpt_id=excerpt_id, included=False,
                    reason="exceeds budget", score=score,
                    token_count=excerpt_tokens,
                ))

        manifest.used_tokens = tokens_used
        self.last_manifest = manifest
        logger.info(manifest.summary())

        return "\n\n---\n\n".join(context_parts), manifest

    async def build_messages_with_context(
        self,
        history: List[Dict],
        user_content: str,
    ) -> List[Dict]:
        """Build messages with retrieved memory context injected."""
        context_text, _ = await self.retrieve_context(user_content)

        system_prompt = self.build_system_prompt()
        if context_text:
            system_prompt += f"\n\n--- Relevant Memories ---\n{context_text}"

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})
        return messages
