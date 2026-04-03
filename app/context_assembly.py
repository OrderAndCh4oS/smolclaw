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
    score: float


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


DEFAULT_TYPE_WEIGHTS = {
    "fact": 1.2,
    "decision": 1.2,
    "reference": 1.1,
    "preference": 1.0,
    "task": 1.0,
    "episode": 0.8,
    "journal": 0.8,
}

# Tier 0: identity (always in context, never decays)
# Tier 1: core (high priority, slow decay)
# Tier 2: working (normal priority, normal decay)
TIER_BOOSTS = {0: 2.0, 1: 1.5, 2: 1.0}


class ContextAssembler(ContextBuilder):
    """Budget-aware context builder that retrieves memories from SmolRAG
    and prioritizes by importance * confidence * recency decay * type weight."""

    def __init__(
        self,
        smol_rag,
        token_budget: int = 4000,
        bootstrap_path: str = None,
        persona: str = None,
        shared_bootstrap_path: str = None,
        decay_half_life_days: float = 30.0,
        type_weights: Optional[Dict[str, float]] = None,
        skills_paths: Optional[List[str]] = None,
    ):
        super().__init__(
            bootstrap_path=bootstrap_path,
            persona=persona,
            shared_bootstrap_path=shared_bootstrap_path,
            skills_paths=skills_paths,
        )
        self.smol_rag = smol_rag
        self.token_budget = token_budget
        self.decay_half_life_days = decay_half_life_days
        self.type_weights = type_weights or DEFAULT_TYPE_WEIGHTS
        self.last_manifest: Optional[AssemblyManifest] = None

    def _recency_decay(self, indexed_at: float) -> float:
        """Exponential decay based on age in days."""
        if not indexed_at:
            return 0.5
        age_days = (time.time() - indexed_at) / 86400.0
        return math.exp(-0.693 * age_days / self.decay_half_life_days)

    def _score_excerpt(self, excerpt_data: dict) -> float:
        """Score an excerpt by importance * confidence * recency_decay * type_weight * tier_boost."""
        importance = excerpt_data.get("importance", 0.5)
        confidence = excerpt_data.get("confidence", 1.0)
        indexed_at = excerpt_data.get("indexed_at", 0)
        recency = self._recency_decay(indexed_at)
        memory_type = excerpt_data.get("memory_type")
        type_weight = self.type_weights.get(memory_type, 1.0) if memory_type else 1.0
        tier = excerpt_data.get("tier", 2)
        tier_boost = TIER_BOOSTS.get(tier, 1.0)
        return importance * confidence * recency * type_weight * tier_boost

    async def _gather_scored_items(self, query: str, top_k: int = 20) -> list:
        """Gather excerpt data from vector, KG, and BM25 sources, deduplicate, and score."""
        seen_ids = set()
        scored_items = []

        async def _add_excerpts(excerpts: list):
            for exc in excerpts:
                if not isinstance(exc, dict) or "excerpt" not in exc:
                    continue
                exc_id = exc.get("doc_id") or id(exc)
                if exc_id in seen_ids:
                    continue
                seen_ids.add(exc_id)
                score = self._score_excerpt(exc)
                scored_items.append((str(exc_id), exc, score))

        # 1. Vector similarity (primary)
        try:
            embedding = await self.smol_rag.rate_limited_get_embedding(query)
            vector_results = await self.smol_rag.vector_search(embedding, top_k=top_k)
            for r in vector_results:
                excerpt_id = r.get("__id__")
                if not excerpt_id or excerpt_id in seen_ids:
                    continue
                excerpt_data = await self.smol_rag.get_excerpt(excerpt_id)
                if not excerpt_data:
                    continue
                seen_ids.add(excerpt_id)
                score = self._score_excerpt(excerpt_data)
                scored_items.append((excerpt_id, excerpt_data, score))
        except Exception as e:
            logger.warning(f"Vector retrieval failed: {e}")

        # 2. KG entity/relationship excerpts
        try:
            from app.prompts import get_high_low_level_keywords_prompt
            from app.definitions import KG_SEP

            prompt = get_high_low_level_keywords_prompt(query)

            # Try structured output, fall back to text parsing
            keyword_data = {}
            llm = getattr(self.smol_rag, "llm", None)
            if llm and hasattr(llm, "get_structured_completion"):
                try:
                    from app.schemas import HighLowKeywords
                    result = await llm.get_structured_completion(prompt, HighLowKeywords)
                    keyword_data = result.model_dump()
                except Exception:
                    pass
            if not keyword_data:
                from app.utilities import extract_json_from_text
                kw_result = await self.smol_rag.rate_limited_get_completion(prompt)
                keyword_data = extract_json_from_text(kw_result) or {}

            ll_dataset, ll_entity_excerpts, _ = await self.smol_rag.get_low_level_dataset(keyword_data)
            _, _, hl_entity_excerpts = await self.smol_rag.get_high_level_dataset(keyword_data)
            await _add_excerpts(ll_entity_excerpts)
            await _add_excerpts(hl_entity_excerpts)
        except Exception as e:
            logger.warning(f"KG retrieval failed, using vector-only: {e}")

        # 3. BM25 keyword search
        try:
            bm25_results = await self.smol_rag.bm25_query(query, top_k=top_k)
            await _add_excerpts(bm25_results)
        except Exception as e:
            logger.warning(f"BM25 retrieval failed: {e}")

        return scored_items

    async def _gather_t0_items(self) -> list:
        """Gather all tier-0 (identity) excerpts — always included regardless of query."""
        t0_items = []
        try:
            all_excerpts = await self.smol_rag.get_all_excerpts()
            for excerpt_id, data in all_excerpts.items():
                if isinstance(data, dict) and data.get("tier") == 0:
                    t0_items.append((excerpt_id, data))
        except Exception as e:
            logger.warning(f"Failed to gather T0 items: {e}")
        return t0_items

    async def retrieve_context(self, query: str, top_k: int = 20) -> tuple[str, AssemblyManifest]:
        """Retrieve and assemble context from SmolRAG within token budget.

        T0 (identity) memories are always included outside the token budget.
        T1/T2 memories are retrieved via vector + KG + BM25 and budget-filtered.
        """
        from app.tracing import trace_retrieval

        manifest = AssemblyManifest(total_budget=self.token_budget, used_tokens=0)

        with trace_retrieval(query) as retrieval_span:
            return await self._retrieve_context_inner(query, top_k, manifest, retrieval_span)

    async def _retrieve_context_inner(self, query, top_k, manifest, retrieval_span):
        # T0 memories: always in context (outside budget)
        t0_items = await self._gather_t0_items()
        t0_parts = []
        for excerpt_id, data in t0_items:
            text = data.get("excerpt", "")
            if text:
                t0_parts.append(text)
                manifest.included.append(InclusionRecord(
                    excerpt_id=excerpt_id, included=True,
                    score=self._score_excerpt(data),
                ))

        scored_items = await self._gather_scored_items(query, top_k)
        # Exclude T0 items from budget-scored list (already included above)
        t0_ids = {eid for eid, _ in t0_items}
        scored_items = [(eid, data, score) for eid, data, score in scored_items if eid not in t0_ids]
        # Sort by score descending
        scored_items.sort(key=lambda x: x[2], reverse=True)

        # Build context within budget — summaries first, then expand
        context_parts = list(t0_parts)
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
                    score=score,
                ))
            elif tokens_used + summary_tokens <= self.token_budget and summary:
                context_parts.append(f"[Summary] {summary}")
                tokens_used += summary_tokens
                manifest.included.append(InclusionRecord(
                    excerpt_id=excerpt_id, included=True,
                    score=score,
                ))
            else:
                manifest.excluded.append(InclusionRecord(
                    excerpt_id=excerpt_id, included=False,
                    score=score,
                ))

        manifest.used_tokens = tokens_used
        self.last_manifest = manifest
        logger.info(manifest.summary())

        retrieval_span.set_attribute("retrieval.included_count", len(manifest.included))
        retrieval_span.set_attribute("retrieval.excluded_count", len(manifest.excluded))
        retrieval_span.set_attribute("retrieval.tokens_used", tokens_used)

        return "\n\n---\n\n".join(context_parts), manifest

    async def build_messages_async(
        self,
        history: List[Dict],
        user_content: str,
    ) -> List[Dict]:
        """Build messages with retrieved memory context injected."""
        context_text, _ = await self.retrieve_context(user_content)

        system_prompt = self.build_system_prompt()
        if context_text:
            system_prompt += f"\n\n--- Relevant Memories ---\n{context_text}"

        # Surface pending contradiction count as a lightweight nudge
        try:
            count = await self.smol_rag.get_pending_contradiction_count()
            if count > 0:
                system_prompt += (
                    f"\n\n--- Knowledge Conflicts ---\n"
                    f"{count} unresolved contradiction(s) in memory. "
                    f"Use contradiction_review tool to inspect and resolve when relevant."
                )
        except Exception as e:
            logger.warning(f"Failed to check contradiction count: {e}")

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})
        return messages
