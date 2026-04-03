import asyncio
import logging
from typing import Any

from app.definitions import KG_SEP
from app.utilities import make_hash, split_string_by_multi_markers

logger = logging.getLogger("smolclaw.document_manager")


class DocumentManager:
    """Handles document removal and KG cleanup with provenance tracking."""

    def __init__(self, stores):
        self.stores = stores

    @staticmethod
    def _prune_kg_ids(raw_value: Any, ids_to_remove: set[str]) -> str:
        values = split_string_by_multi_markers(str(raw_value or ""), [KG_SEP])
        filtered = [value for value in values if value not in ids_to_remove]
        deduped = list(dict.fromkeys(filtered))
        return KG_SEP.join(deduped)

    def _find_entity_name_for_id(self, entity_id: str):
        for entity_name in self.stores.graph.graph.nodes:
            if make_hash(entity_name, prefix="ent-") == entity_id:
                return entity_name
        return None

    def _find_relationship_endpoints_for_id(self, relationship_id: str):
        for source, target in self.stores.graph.graph.edges:
            sorted_source, sorted_target = sorted((source, target))
            current_id = make_hash(f"{sorted_source}_{sorted_target}", prefix="rel-")
            if current_id == relationship_id:
                return sorted_source, sorted_target
        return None, None

    async def _cleanup_entity_contributions(self, doc_id: str, doc_excerpt_ids: set[str]) -> bool:
        entity_ids = await self.stores.doc_entity_map.get_by_left(doc_id)
        if not entity_ids:
            return False

        rows = await self.stores.entities_db.get(entity_ids)
        entity_rows_by_id = {row.get("__id__"): row for row in rows}
        ids_to_delete = []

        for entity_id in entity_ids:
            docs = await self.stores.doc_entity_map.get_by_right(entity_id)
            remaining_docs = [item for item in docs if item != doc_id]

            entity_row = entity_rows_by_id.get(entity_id)
            entity_name = entity_row.get("__entity_name__") if entity_row else None
            if entity_name is None:
                entity_name = self._find_entity_name_for_id(entity_id)
            node = self.stores.graph.get_node(entity_name) if entity_name else None

            if node and "excerpt_id" in node:
                pruned_excerpt_ids = self._prune_kg_ids(node.get("excerpt_id"), doc_excerpt_ids)
                if remaining_docs:
                    effective_excerpt_ids = pruned_excerpt_ids or node.get("excerpt_id", "")
                    updated_node = {**node, "excerpt_id": effective_excerpt_ids}
                    await self.stores.graph.async_add_node(entity_name, **updated_node)
                    if not pruned_excerpt_ids:
                        logger.debug(
                            "Retaining entity %s after prune because remaining docs still reference it.",
                            entity_name,
                        )
                else:
                    await self.stores.graph.async_remove_node(entity_name)

            if not remaining_docs:
                await self.stores.doc_entity_map.remove_by_right(entity_id)
                ids_to_delete.append(entity_id)

        await self.stores.doc_entity_map.remove_by_left(doc_id)
        if ids_to_delete:
            await self.stores.entities_db.delete(ids_to_delete)
        return True

    async def _cleanup_relationship_contributions(self, doc_id: str, doc_excerpt_ids: set[str]) -> bool:
        relationship_ids = await self.stores.doc_relationship_map.get_by_left(doc_id)
        if not relationship_ids:
            return False

        rows = await self.stores.relationships_db.get(relationship_ids)
        relationship_rows_by_id = {row.get("__id__"): row for row in rows}
        ids_to_delete = []

        for relationship_id in relationship_ids:
            docs = await self.stores.doc_relationship_map.get_by_right(relationship_id)
            remaining_docs = [item for item in docs if item != doc_id]

            relationship_row = relationship_rows_by_id.get(relationship_id)
            source = relationship_row.get("__source__") if relationship_row else None
            target = relationship_row.get("__target__") if relationship_row else None
            if not source or not target:
                source, target = self._find_relationship_endpoints_for_id(relationship_id)
            edge = self.stores.graph.get_edge((source, target)) if source and target else None

            if edge and "excerpt_id" in edge:
                pruned_excerpt_ids = self._prune_kg_ids(edge.get("excerpt_id"), doc_excerpt_ids)
                if remaining_docs:
                    effective_excerpt_ids = pruned_excerpt_ids or edge.get("excerpt_id", "")
                    updated_edge = {**edge, "excerpt_id": effective_excerpt_ids}
                    await self.stores.graph.async_add_edge(source, target, **updated_edge)
                    if not pruned_excerpt_ids:
                        logger.debug(
                            "Retaining relationship %s -> %s after prune because remaining docs still reference it.",
                            source,
                            target,
                        )
                else:
                    await self.stores.graph.async_remove_edge(source, target)

            if not remaining_docs:
                await self.stores.doc_relationship_map.remove_by_right(relationship_id)
                ids_to_delete.append(relationship_id)

        await self.stores.doc_relationship_map.remove_by_left(doc_id)
        if ids_to_delete:
            await self.stores.relationships_db.delete(ids_to_delete)
        return True

    async def remove_document_by_id(self, doc_id, persist=True):
        removed_excerpt_data = False
        removed_kg_data = False
        excerpt_ids = []

        if await self.stores.source_doc_map.has_right(doc_id):
            await self.stores.source_doc_map.remove_by_right(doc_id)

        excerpt_ids = await self.stores.doc_excerpt_map.get_by_left(doc_id)
        if excerpt_ids:
            excerpts_to_remove = [self.stores.excerpt_kv.remove(excerpt_id) for excerpt_id in excerpt_ids]
            bm25_removes = [self.stores.bm25_store.remove(excerpt_id) for excerpt_id in excerpt_ids]
            await asyncio.gather(self.stores.embeddings_db.delete(excerpt_ids), *excerpts_to_remove, *bm25_removes)
            await self.stores.doc_excerpt_map.remove_by_left(doc_id)
            removed_excerpt_data = True

        excerpt_ids_set = set(excerpt_ids)
        async with self.stores.provenance_lock:
            entity_removed = await self._cleanup_entity_contributions(doc_id, excerpt_ids_set)
            relationship_removed = await self._cleanup_relationship_contributions(doc_id, excerpt_ids_set)
        removed_kg_data = entity_removed or relationship_removed

        if not persist:
            return

        save_tasks = []
        if removed_excerpt_data:
            save_tasks.append(self.stores.embeddings_db.save())
        if removed_kg_data:
            save_tasks.extend([
                self.stores.entities_db.save(),
                self.stores.relationships_db.save(),
            ])
            save_tasks.append(self.stores.graph.async_save())
        if save_tasks:
            await asyncio.gather(*save_tasks)

    async def remove_document_by_source(self, source_id: str):
        """Remove a document by its source ID (file path)."""
        doc_id = await self.stores.source_doc_map.get_right_single(source_id)
        if doc_id:
            await self.remove_document_by_id(doc_id)
