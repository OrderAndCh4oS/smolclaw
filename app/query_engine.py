import asyncio
import inspect
import logging

import numpy as np

from app.definitions import KG_SEP
from app.prompts import get_query_system_prompt, get_high_low_level_keywords_prompt, \
    get_kg_query_system_prompt, get_mix_system_prompt
from app.utilities import extract_json_from_text, truncate_list_by_token_size, \
    list_of_list_to_csv, split_string_by_multi_markers

logger = logging.getLogger("smolclaw.query_engine")


class QueryEngine:
    """Handles all query strategies: vector, KG (local/global/hybrid), BM25, and mixed."""

    def __init__(self, stores, llm_provider):
        self.stores = stores
        self._llm_provider = llm_provider

    async def _get_completion(self, *args, **kwargs):
        return await self._get_extract_completion(*args, **kwargs)

    async def _get_extract_completion(self, *args, **kwargs):
        return await self._llm_provider.rate_limited_get_extract_completion(*args, **kwargs)

    async def _get_query_completion(self, *args, **kwargs):
        return await self._llm_provider.rate_limited_get_query_completion(*args, **kwargs)

    async def _get_embedding(self, *args, **kwargs):
        return await self._llm_provider.rate_limited_get_embedding(*args, **kwargs)

    async def _get_embeddings(self, *args, **kwargs):
        return await self._llm_provider.rate_limited_get_embeddings(*args, **kwargs)

    async def query(self, text):
        logger.info(f"Received query: {text}")
        excerpts = await self._get_query_excerpts(text)
        logger.info(f"Retrieved {len(excerpts)} excerpts for the query.")
        excerpt_context = self._get_excerpt_context(excerpts)
        system_prompt = get_query_system_prompt(excerpt_context)
        return await self._get_query_completion(text, context=system_prompt.strip(), use_cache=True)

    def _get_excerpt_context(self, excerpts):
        context = ""
        for excerpt in excerpts:
            context += inspect.cleandoc(f"""
                ## Excerpt

                {excerpt["excerpt"]}

                ## Summary

                {excerpt["summary"]}
            """)
            context += "\n\n"
        return context

    @staticmethod
    def _attach_excerpt_id(excerpt_id: str, excerpt_data: dict | None) -> dict | None:
        if excerpt_data is None or "excerpt" not in excerpt_data:
            return None
        return {**excerpt_data, "excerpt_id": excerpt_id}

    @staticmethod
    def _excerpt_matches_embedding_model(
        excerpt_data: dict,
        embedding_model: str | None,
        embedding_dimensions: int | None = None,
    ) -> bool:
        if embedding_model is None:
            return True
        return (
            excerpt_data.get("__embedding_model__") == embedding_model
            and excerpt_data.get("__embedding_dimensions__") == embedding_dimensions
        )

    def _attach_current_excerpt_id(self, excerpt_id: str, excerpt_data: dict | None) -> dict | None:
        attached = self._attach_excerpt_id(excerpt_id, excerpt_data)
        if attached is None:
            return None
        embedding_model = getattr(self.stores.embeddings_db, "embedding_model", None)
        embedding_dimensions = getattr(self.stores.embeddings_db, "dimensions", None)
        if not self._excerpt_matches_embedding_model(attached, embedding_model, embedding_dimensions):
            return None
        return attached

    async def _get_query_excerpts(self, text):
        embedding = await self._get_embedding(text)
        embedding_array = np.array(embedding)
        results = await self.stores.embeddings_db.query(query=embedding_array, top_k=5, better_than_threshold=0.02)
        excerpt_ids = [result["__id__"] for result in results]
        excerpts = await asyncio.gather(*[self.stores.excerpt_kv.get_by_key(excerpt_id) for excerpt_id in excerpt_ids])
        excerpts = [
            self._attach_current_excerpt_id(excerpt_id, excerpt)
            for excerpt_id, excerpt in zip(excerpt_ids, excerpts)
        ]
        excerpts = [excerpt for excerpt in excerpts if excerpt is not None]
        excerpts = truncate_list_by_token_size(excerpts, get_text_for_row=lambda x: x["excerpt"], max_token_size=4000)
        return excerpts

    async def hybrid_kg_query(self, text):
        prompt = get_high_low_level_keywords_prompt(text)
        result = await self._get_extract_completion(prompt)
        keyword_data = extract_json_from_text(result) or {}
        logger.info("Processed high/low level keywords for hybrid KG query.")

        (ll_dataset, ll_entity_excerpts, ll_relations), (hl_dataset, hl_entities, hl_entity_excerpts) = (
            await asyncio.gather(
                self.get_low_level_dataset(keyword_data),
                self.get_high_level_dataset(keyword_data),
            )
        )

        entities = ll_dataset + hl_entities
        relations = ll_relations + hl_dataset
        excerpts = ll_entity_excerpts + hl_entity_excerpts
        context = self._get_kg_query_context(entities, excerpts, relations)
        system_prompt = get_kg_query_system_prompt(context)
        return await self._get_query_completion(text, context=system_prompt.strip(), use_cache=True)

    async def local_kg_query(self, text):
        prompt = get_high_low_level_keywords_prompt(text)
        result = await self._get_extract_completion(prompt)
        keyword_data = extract_json_from_text(result) or {}
        logger.info("Processed high/low level keywords for local KG query.")

        ll_dataset, ll_entity_excerpts, ll_relations = await self.get_low_level_dataset(keyword_data)
        entities = ll_dataset
        relations = ll_relations
        excerpts = ll_entity_excerpts
        context = self._get_kg_query_context(entities, excerpts, relations)
        system_prompt = get_kg_query_system_prompt(context)
        return await self._get_query_completion(text, context=system_prompt.strip(), use_cache=True)

    async def global_kg_query(self, text):
        prompt = get_high_low_level_keywords_prompt(text)
        result = await self._get_extract_completion(prompt)
        keyword_data = extract_json_from_text(result) or {}
        logger.info("Processed high/low level keywords for global KG query.")

        hl_dataset, hl_entities, hl_entity_excerpts = await self.get_high_level_dataset(keyword_data)
        entities = hl_entities
        relations = hl_dataset
        excerpts = hl_entity_excerpts
        context = self._get_kg_query_context(entities, excerpts, relations)
        system_prompt = get_kg_query_system_prompt(context)
        return await self._get_query_completion(text, context=system_prompt.strip(), use_cache=True)

    async def bm25_query(self, text: str, top_k: int = 10) -> list[dict]:
        """Pure BM25 keyword search over excerpts."""
        results = await self.stores.bm25_store.query(text, top_k=top_k)
        excerpt_ids = [result["doc_id"] for result in results]
        fetched = await asyncio.gather(*[self.stores.excerpt_kv.get_by_key(excerpt_id) for excerpt_id in excerpt_ids])
        return [
            excerpt
            for excerpt in (
                self._attach_current_excerpt_id(excerpt_id, data)
                for excerpt_id, data in zip(excerpt_ids, fetched)
            )
            if excerpt is not None
        ]

    @staticmethod
    def _filter_excerpts_by_memory_type(excerpts: list[dict], memory_type: str) -> list[dict]:
        filtered = []
        for excerpt in excerpts:
            excerpt_type = excerpt.get("memory_type")
            if excerpt_type == memory_type:
                filtered.append(excerpt)
        return filtered

    @staticmethod
    def _collect_excerpt_ids(excerpts: list[dict]) -> list[str]:
        excerpt_ids = []
        seen = set()
        for excerpt in excerpts:
            excerpt_id = excerpt.get("excerpt_id")
            if not excerpt_id or excerpt_id in seen:
                continue
            seen.add(excerpt_id)
            excerpt_ids.append(excerpt_id)
        return excerpt_ids

    async def mix_query(
        self,
        text,
        memory_type: str | None = None,
        include_bm25: bool = False,
        return_metadata: bool = False,
    ):
        prompt = get_high_low_level_keywords_prompt(text)
        result = await self._get_extract_completion(prompt)
        keyword_data = extract_json_from_text(result) or {}
        logger.info("Processed high/low level keywords for mixed KG query.")

        tasks = [
            self.get_low_level_dataset(keyword_data),
            self.get_high_level_dataset(keyword_data),
            self._get_query_excerpts(text),
        ]
        if include_bm25:
            tasks.append(self.bm25_query(text, top_k=10))

        results = await asyncio.gather(*tasks)
        ll_dataset, ll_entity_excerpts, ll_relations = results[0]
        hl_dataset, hl_entities, hl_entity_excerpts = results[1]
        query_excerpts = list(results[2])

        kg_entities = ll_dataset + hl_entities
        kg_relations = ll_relations + hl_dataset
        kg_excerpts = ll_entity_excerpts + hl_entity_excerpts

        # Merge BM25 results when requested
        if include_bm25:
            bm25_excerpts = results[3]
            seen_ids = set(self._collect_excerpt_ids(query_excerpts))
            for e in bm25_excerpts:
                excerpt_id = e.get("excerpt_id")
                if excerpt_id and excerpt_id in seen_ids:
                    continue
                query_excerpts.append(e)
                if excerpt_id:
                    seen_ids.add(excerpt_id)

        if memory_type:
            kg_excerpts = self._filter_excerpts_by_memory_type(kg_excerpts, memory_type)
            query_excerpts = self._filter_excerpts_by_memory_type(query_excerpts, memory_type)

        excerpt_ids = self._collect_excerpt_ids(query_excerpts + kg_excerpts)
        kg_context = self._get_kg_query_context(kg_entities, kg_excerpts, kg_relations)
        excerpt_context = self._get_excerpt_context(query_excerpts)
        system_prompt = get_mix_system_prompt(excerpt_context, kg_context)
        content = await self._get_query_completion(text, context=system_prompt.strip(), use_cache=True)
        if return_metadata:
            return {"content": content, "excerpt_ids": excerpt_ids}
        return content

    def _get_kg_query_context(self, entities, excerpts, relations):
        entity_csv = [["entity", "type", "description", "rank"]]
        for entity in entities:
            entity_csv.append([
                entity["entity_name"],
                entity.get("category", "UNKNOWN"),
                entity.get("description", "UNKNOWN"),
                entity["rank"],
            ])
        entity_context = list_of_list_to_csv(entity_csv)
        relation_csv = [["source", "target", "description", "keywords", "weight", "rank"]]
        for relation in relations:
            relation_csv.append([
                relation["src_tgt"][0],
                relation["src_tgt"][1],
                relation["description"],
                relation["keywords"],
                relation["weight"],
                relation["rank"],
            ])
        relations_context = list_of_list_to_csv(relation_csv)
        excerpt_csv = [["excerpt"]]
        for excerpt in excerpts:
            excerpt_csv.append([excerpt["excerpt"]])
        excerpt_context = list_of_list_to_csv(excerpt_csv)
        context = inspect.cleandoc(f"""
            -----Entities-----
            ```csv
            {entity_context}
            ```
            -----Relationships-----
            ```csv
            {relations_context}
            ```
            -----Excerpts-----
            ```csv
            {excerpt_context}
            ```
        """)
        logger.info(f"KG query context built with {len(entities)} entities, {len(relations)} relationships, "
                    f"and {len(excerpts)} excerpts.")
        return context

    async def get_high_level_dataset(self, keyword_data):
        keyword_data = keyword_data if isinstance(keyword_data, dict) else {}
        hl_keywords = self._normalize_keywords(keyword_data.get("high_level_keywords", []))
        logger.info(f"Found {len(hl_keywords)} high-level keywords.")
        hl_results = []
        if len(hl_keywords):
            hl_embedding = await self._get_embedding(hl_keywords)
            hl_embedding_array = np.array(hl_embedding)
            hl_results = await self.stores.relationships_db.query(query=hl_embedding_array, top_k=25, better_than_threshold=0.02)
        hl_data = [self.stores.graph.get_edge((r["__source__"], r["__target__"])) for r in hl_results]
        hl_degrees = [self.stores.graph.degree(r["__source__"]) + self.stores.graph.degree(r["__target__"]) for r in hl_results]
        hl_dataset = []
        for k, n, d in zip(hl_results, hl_data, hl_degrees):
            if n is None:
                logger.warning(
                    "Skipping stale relationship vector row because graph edge is missing: %s -> %s",
                    k.get("__source__"),
                    k.get("__target__"),
                )
                continue
            if not {"description", "keywords", "weight", "excerpt_id"}.issubset(set(n.keys())):
                logger.warning(
                    "Skipping relationship with incomplete graph payload for edge %s -> %s",
                    k.get("__source__"),
                    k.get("__target__"),
                )
                continue
            hl_dataset.append({"src_tgt": (k["__source__"], k["__target__"]), "rank": d, **n})
        hl_dataset = sorted(hl_dataset, key=lambda x: (x["rank"], x["weight"]), reverse=True)
        hl_dataset = truncate_list_by_token_size(
            hl_dataset,
            get_text_for_row=lambda x: x["description"],
            max_token_size=4000,
        )
        hl_entity_excerpts = await self._get_excerpts_for_relationships(hl_dataset)
        hl_entities = self._get_entities_from_relationships(hl_dataset)
        logger.info(f"High-level dataset: {len(hl_dataset)} relationships, {len(hl_entities)} entities extracted.")
        return hl_dataset, hl_entities, hl_entity_excerpts

    async def get_low_level_dataset(self, keyword_data):
        keyword_data = keyword_data if isinstance(keyword_data, dict) else {}
        ll_keywords = self._normalize_keywords(keyword_data.get("low_level_keywords", []))
        logger.info(f"Found {len(ll_keywords)} low-level keywords.")
        ll_results = []
        if len(ll_keywords):
            ll_embedding = await self._get_embedding(ll_keywords)
            ll_embedding_array = np.array(ll_embedding)
            ll_results = await self.stores.entities_db.query(query=ll_embedding_array, top_k=25, better_than_threshold=0.02)
        ll_data = [self.stores.graph.get_node(r["__entity_name__"]) for r in ll_results]
        ll_degrees = [self.stores.graph.degree(r["__entity_name__"]) for r in ll_results]
        ll_dataset = []
        for k, n, d in zip(ll_results, ll_data, ll_degrees):
            if n is None:
                logger.warning(
                    "Skipping stale entity vector row because graph node is missing: %s",
                    k.get("__entity_name__"),
                )
                continue
            if "excerpt_id" not in n:
                logger.warning(
                    "Skipping entity with incomplete graph payload: %s",
                    k.get("__entity_name__"),
                )
                continue
            ll_dataset.append({**n, "entity_name": k["__entity_name__"], "rank": d})
        ll_entity_excerpts = await self._get_excerpts_for_entities(ll_dataset)
        ll_relations = self._get_relationships_from_entities(ll_dataset)
        logger.info(f"Low-level dataset: {len(ll_dataset)} entities, {len(ll_relations)} relationships extracted.")
        return ll_dataset, ll_entity_excerpts, ll_relations

    async def _get_excerpts_for_entities(self, kg_dataset):
        excerpt_ids = [split_string_by_multi_markers(row["excerpt_id"], [KG_SEP]) for row in kg_dataset]
        all_edges = [self.stores.graph.get_node_edges(row["entity_name"]) for row in kg_dataset]
        sibling_names = set()
        for edge in all_edges:
            if not edge:
                continue
            sibling_names.update([e[1] for e in edge])
        sibling_nodes = [self.stores.graph.get_node(name) for name in list(sibling_names)]
        sibling_excerpt_lookup = {
            k: set(split_string_by_multi_markers(v["excerpt_id"], [KG_SEP]))
            for k, v in zip(sibling_names, sibling_nodes)
            if v is not None and "excerpt_id" in v
        }
        all_excerpt_data_lookup = {}
        for index, (excerpt_ids, edges) in enumerate(zip(excerpt_ids, all_edges)):
            for excerpt_id in excerpt_ids:
                if excerpt_id in all_excerpt_data_lookup:
                    continue
                relation_counts = 0
                if edges:
                    for edge in edges:
                        sibling_name = edge[1]
                        if sibling_name in sibling_excerpt_lookup and excerpt_id in sibling_excerpt_lookup[
                            sibling_name]:
                            relation_counts += 1
                excerpt_data = await self.stores.excerpt_kv.get_by_key(excerpt_id)
                excerpt_data = self._attach_current_excerpt_id(excerpt_id, excerpt_data)
                if excerpt_data is not None:
                    all_excerpt_data_lookup[excerpt_id] = {
                        "data": excerpt_data,
                        "order": index,
                        "relation_counts": relation_counts,
                    }

        all_excerpts = [
            {"id": k, **v}
            for k, v in all_excerpt_data_lookup.items()
            if v is not None and v.get("data") is not None and "excerpt" in v["data"]
        ]

        if not all_excerpts:
            logger.warning("No valid excerpts found for low-level entities.")
            return []

        all_excerpts = sorted(all_excerpts, key=lambda x: (x["order"], -x["relation_counts"]))
        all_excerpts = [t["data"] for t in all_excerpts]

        all_excerpts = truncate_list_by_token_size(
            all_excerpts,
            get_text_for_row=lambda x: x["excerpt"],
            max_token_size=4000,
        )
        logger.info(f"Extracted {len(all_excerpts)} excerpts for low-level entities.")
        return all_excerpts

    def _get_relationships_from_entities(self, kg_dataset):
        node_edges_list = [self.stores.graph.get_node_edges(row["entity_name"]) for row in kg_dataset]

        edges = []
        seen = set()

        for node_edges in node_edges_list:
            for edge in node_edges:
                sorted_edge = tuple(sorted(edge))
                if sorted_edge not in seen:
                    seen.add(sorted_edge)
                    edges.append(sorted_edge)

        edges_pack = [self.stores.graph.get_edge((e[0], e[1])) for e in edges]
        edges_degree = [self.stores.graph.degree(e[0]) + self.stores.graph.degree(e[1]) for e in edges]

        edges_data = [
            {"src_tgt": k, "rank": d, **v}
            for k, v, d in zip(edges, edges_pack, edges_degree)
            if v is not None
        ]
        edges_data = sorted(edges_data, key=lambda x: (x["rank"], x["weight"]), reverse=True)
        edges_data = truncate_list_by_token_size(
            edges_data,
            get_text_for_row=lambda x: x["description"],
            max_token_size=1000,
        )
        logger.info(f"Extracted {len(edges_data)} relationships from low-level entities.")
        return edges_data

    async def _get_excerpts_for_relationships(self, kg_dataset):
        excerpt_ids = [
            split_string_by_multi_markers(dp["excerpt_id"], [KG_SEP])
            for dp in kg_dataset
        ]

        all_excerpts_lookup = {}

        for index, excerpt_ids in enumerate(excerpt_ids):
            for excerpt_id in excerpt_ids:
                if excerpt_id not in all_excerpts_lookup:
                    excerpt_data = await self.stores.excerpt_kv.get_by_key(excerpt_id)
                    attached = self._attach_current_excerpt_id(excerpt_id, excerpt_data)
                    if attached is None:
                        logger.debug("Skipping excerpt %s: data is None (stale reference)", excerpt_id)
                    all_excerpts_lookup[excerpt_id] = {
                        "data": attached,
                        "order": index,
                    }

        all_excerpts = [
            {"id": k, **v} for k, v in all_excerpts_lookup.items()
            if v is not None and v.get("data") is not None
        ]
        all_excerpts = sorted(all_excerpts, key=lambda x: x["order"])
        all_excerpts = [t["data"] for t in all_excerpts]

        all_excerpts = truncate_list_by_token_size(
            all_excerpts,
            get_text_for_row=lambda x: x["excerpt"],
            max_token_size=4000,
        )

        return all_excerpts

    def _get_entities_from_relationships(self, kg_dataset):
        entity_names = []
        seen = set()

        for e in kg_dataset:
            if e["src_tgt"][0] not in seen:
                entity_names.append(e["src_tgt"][0])
                seen.add(e["src_tgt"][0])
            if e["src_tgt"][1] not in seen:
                entity_names.append(e["src_tgt"][1])
                seen.add(e["src_tgt"][1])

        data = [self.stores.graph.get_node(entity_name) for entity_name in entity_names]
        degrees = [self.stores.graph.degree(entity_name) for entity_name in entity_names]

        data = [
            {**n, "entity_name": k, "rank": d}
            for k, n, d in zip(entity_names, data, degrees)
            if n is not None and "description" in n
        ]

        data = truncate_list_by_token_size(
            data,
            get_text_for_row=lambda x: x.get("description", x.get("entity_name", "")),
            max_token_size=4000,
        )
        logger.info(f"Extracted {len(data)} entities from relationships.")
        return data

    @staticmethod
    def _normalize_keywords(keywords):
        if keywords is None:
            return []
        if isinstance(keywords, str):
            return [keywords] if keywords.strip() else []
        if not isinstance(keywords, list):
            return []
        return [str(k) for k in keywords if str(k).strip()]
