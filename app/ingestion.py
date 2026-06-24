import asyncio
import logging
import re
import time

import numpy as np

from app.definitions import KG_SEP, TUPLE_SEP, REC_SEP, COMPLETE_TAG
from app.obsidian import parse_wiki_links, parse_tags
from app.prompts import excerpt_summary_prompt, get_extract_entities_prompt
from app.utilities import read_file, get_docs, make_hash, split_string_by_multi_markers, clean_str

logger = logging.getLogger("smolclaw.ingestion")


def _is_standalone_tag_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and re.fullmatch(r"(#[A-Za-z0-9_/-]+)(\s+#[A-Za-z0-9_/-]+)*", stripped))


class IngestionPipeline:
    """Handles document ingestion: chunking, embedding, entity extraction, and provenance tracking."""

    def __init__(self, stores, llm_provider, doc_manager, excerpt_fn, excerpt_size=2000, overlap=200,
                 ingest_concurrency=4, input_docs_dir=None):
        self.stores = stores
        self._llm_provider = llm_provider
        self.doc_manager = doc_manager
        self.excerpt_fn = excerpt_fn
        self.excerpt_size = excerpt_size
        self.overlap = overlap
        self.ingest_concurrency = max(1, ingest_concurrency)
        self.input_docs_dir = input_docs_dir
        self._current_ingest_source = "extraction"

    async def _get_completion(self, *args, **kwargs):
        return await self._llm_provider.rate_limited_get_extract_completion(*args, **kwargs)

    async def _get_embedding(self, *args, **kwargs):
        return await self._llm_provider.rate_limited_get_embedding(*args, **kwargs)

    async def _get_embeddings(self, *args, **kwargs):
        return await self._llm_provider.rate_limited_get_embeddings(*args, **kwargs)

    async def ingest_text(self, content: str, source_id: str = None, save: bool = True, source: str = "extraction"):
        """Ingest raw text into the RAG pipeline (chunks, embeds, extracts entities).
        Also parses obsidian wiki links into graph edges and tags into entity labels.
        Set save=False to defer store persistence (caller must call _save_stores).
        source: "extraction" or "user" — user input gets higher priority for contradictions."""
        self._current_ingest_source = source
        source_key = source_id or make_hash(content, "text-")
        doc_id = make_hash(content, "doc_")

        await self.stores.source_doc_map.add(source_key, doc_id)

        await self._embed_document(content, doc_id)
        await self._extract_entities(content, doc_id)

        # Parse obsidian wiki links and add as graph edges
        links = parse_wiki_links(content)
        for target, _alias in links:
            await self.stores.graph.async_upsert_entity_node(
                name=target, category="wiki_link", description="Linked from content",
                excerpt_id=make_hash(content[:200], "excerpt_id_"), sep=KG_SEP,
            )

        # Parse obsidian tags and add as entity nodes
        tags = parse_tags(content)
        for tag in tags:
            await self.stores.graph.async_upsert_entity_node(
                name=f"#{tag}", category="tag", description=f"Tag: {tag}",
                excerpt_id=make_hash(content[:200], "excerpt_id_"), sep=KG_SEP,
            )

        self._current_ingest_source = "extraction"

        if save:
            await self._save_stores()

    async def import_documents(self):
        sources = get_docs(self.input_docs_dir)
        semaphore = asyncio.Semaphore(self.ingest_concurrency)
        await asyncio.gather(*(self._process_source(source, semaphore) for source in sources))
        await self._save_stores()

    async def _save_stores(self):
        await asyncio.gather(
            self.stores.embeddings_db.save(),
            self.stores.entities_db.save(),
            self.stores.relationships_db.save(),
        )
        self.stores.graph.save()

    async def _process_source(self, source, semaphore):
        async with semaphore:
            content = read_file(source)
            doc_id = make_hash(content, "doc_")
            if not await self.stores.source_doc_map.has_left(source):
                logger.info(f"Importing new document: {source} (ID: {doc_id})")
                await self._add_document_maps(source, content)
                await self._embed_document(content, doc_id)
                await self._extract_entities(content, doc_id)
                return

            if not await self.stores.source_doc_map.equal_right(source, doc_id):
                logger.info(f"Updating document: {source} (New ID: {doc_id})")
                old_doc_id = await self.stores.source_doc_map.get_right_single(source)
                await self.doc_manager.remove_document_by_id(old_doc_id, persist=False)
                await self._add_document_maps(source, content)
                await self._embed_document(content, doc_id)
                await self._extract_entities(content, doc_id)
                return

            logger.debug(f"No changes detected for document: {source} (ID: {doc_id})")

    async def _add_document_maps(self, source, content):
        doc_id = make_hash(content, "doc_")
        await self.stores.source_doc_map.add(source, doc_id)

    @staticmethod
    def _extract_frontmatter(content: str) -> dict:
        """Extract YAML frontmatter metadata from content if present."""
        metadata = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                import yaml
                try:
                    fm = yaml.safe_load(parts[1])
                    if isinstance(fm, dict):
                        for key in ("memory_type", "tags", "confidence", "importance", "source_id", "tier"):
                            if key in fm:
                                metadata[key] = fm[key]
                except Exception:
                    pass
        return metadata

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Return content without YAML frontmatter."""
        if not content.startswith("---"):
            return content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return content
        return parts[2].lstrip("\n")

    @classmethod
    def _content_for_indexing(cls, content: str) -> str:
        """Remove storage metadata that should not become searchable project knowledge."""
        body = cls._strip_frontmatter(content)
        lines = body.splitlines()
        while lines and (_is_standalone_tag_line(lines[0]) or not lines[0].strip()):
            lines.pop(0)
        return "\n".join(lines).strip() or body.strip() or content

    async def _embed_document(self, content, doc_id):
        start_time = time.time()
        doc_metadata = self._extract_frontmatter(content)
        index_content = self._content_for_indexing(content)
        excerpts = self.excerpt_fn(index_content, self.excerpt_size, self.overlap)
        excerpt_ids = []

        summary_tasks = [self._get_excerpt_summary(index_content, excerpt) for excerpt in excerpts]
        summaries = await asyncio.gather(*summary_tasks)

        # Batch all embeddings into a single API call
        embedding_contents = [f"{excerpt}\n\n{summary}" for excerpt, summary in zip(excerpts, summaries)]
        embedding_results = await self._get_embeddings(embedding_contents)
        storage_tasks = []
        for i, (excerpt, summary, embedding_result) in enumerate(zip(excerpts, summaries, embedding_results)):
            excerpt_id = make_hash(excerpt, "excerpt_id_")
            excerpt_ids.append(excerpt_id)
            vector = np.array(embedding_result, dtype=np.float32)
            storage_tasks.append(self.stores.embeddings_db.upsert([
                {
                    "__id__": excerpt_id,
                    "__vector__": vector,
                    "__doc_id__": doc_id,
                    "__inserted_at__": time.time()
                }
            ]))
            excerpt_data = {
                "doc_id": doc_id,
                "doc_order_index": i,
                "excerpt": excerpt,
                "summary": summary,
                "indexed_at": time.time(),
                "__embedding_model__": getattr(self.stores.embeddings_db, "embedding_model", None),
                "__embedding_dimensions__": getattr(self.stores.embeddings_db, "dimensions", None),
            }
            # Propagate taxonomy metadata from frontmatter
            for key in ("memory_type", "tags", "confidence", "importance", "tier"):
                if key in doc_metadata:
                    excerpt_data[key] = doc_metadata[key]
            storage_tasks.append(self.stores.excerpt_kv.add(excerpt_id, excerpt_data))
            storage_tasks.append(self.stores.bm25_store.add(excerpt_id, excerpt))
            logger.info(f"Created embedding for excerpt {excerpt_id} associated with document {doc_id}")
        await asyncio.gather(*storage_tasks)

        await self.stores.doc_excerpt_map.add_many(doc_id, excerpt_ids)
        elapsed = time.time() - start_time
        logger.info(f"Document {doc_id} processed with {len(excerpts)} excerpts in {elapsed:.2f} seconds.")

    async def _get_excerpt_summary(self, full_doc, excerpt):
        prompt = excerpt_summary_prompt(full_doc, excerpt)
        try:
            summary = await self._get_completion(prompt)
        except Exception as e:
            logger.error(f"LLM call in _get_excerpt_summary failed: {e}")
            summary = "Summary unavailable."
        return summary

    async def _extract_entities(self, content, doc_id):
        start_time = time.time()
        total_entities = 0
        total_relationships = 0
        doc_entity_ids = set()
        doc_relationship_ids = set()
        index_content = self._content_for_indexing(content)
        excerpts = self.excerpt_fn(index_content, self.excerpt_size, self.overlap)

        extract_entity_tasks = [self._get_completion(get_extract_entities_prompt(excerpt)) for excerpt in
                                excerpts]
        entity_results = await asyncio.gather(*extract_entity_tasks)

        for (excerpt, result) in zip(excerpts, entity_results):
            excerpt_id = make_hash(excerpt, "excerpt_id_")
            data_str = result.replace(COMPLETE_TAG, '').strip()
            records = split_string_by_multi_markers(data_str, [REC_SEP])

            clean_records = []
            for record in records:
                if record.startswith('(') and record.endswith(')'):
                    record = record[1:-1]
                clean_records.append(clean_str(record))
            records = clean_records

            entities_to_upsert = []
            relationships_to_upsert = []
            embedding_contents = []

            for record in records:
                fields = split_string_by_multi_markers(record, [TUPLE_SEP])
                if not fields:
                    continue
                fields = [field[1:-1] if field.startswith('"') and field.endswith('"') else field for field in fields]
                record_type = fields[0].lower()

                if record_type == 'entity':
                    if len(fields) >= 4:
                        _, name, category, description = fields[:4]
                        # Contradiction check before upsert
                        if self.stores.contradiction_detector:
                            existing = self.stores.graph.get_node(name)
                            if existing:
                                contradictions = await self.stores.contradiction_detector.check_entity(
                                    name, category, description, excerpt_id,
                                    source=self._current_ingest_source,
                                )
                                if any(c.get("status") == "dismissed" for c in contradictions):
                                    continue  # Skip upsert for auto-dismissed contradictions
                        await self.stores.graph.async_upsert_entity_node(
                            name=name,
                            category=category,
                            description=description,
                            excerpt_id=excerpt_id,
                            sep=KG_SEP,
                        )
                        total_entities += 1
                        entity_id = make_hash(name, prefix="ent-")
                        doc_entity_ids.add(entity_id)
                        embedding_content = f"{name} {description}"
                        embedding_contents.append(embedding_content)
                        entities_to_upsert.append({
                            "__id__": entity_id,
                            "__entity_name__": name,
                            "__inserted_at__": time.time(),
                        })
                elif record_type == 'relationship':
                    if len(fields) >= 6:
                        _, source, target, description, keywords, weight = fields[:6]
                        source, target = sorted([source, target])
                        try:
                            parsed_weight = float(weight)
                        except (TypeError, ValueError):
                            parsed_weight = 1.0

                        # Contradiction check before upsert
                        if self.stores.contradiction_detector:
                            existing = self.stores.graph.get_edge((source, target))
                            if existing:
                                contradictions = await self.stores.contradiction_detector.check_relationship(
                                    source, target, description, excerpt_id,
                                    source_type=self._current_ingest_source,
                                )
                                if any(c.get("status") == "dismissed" for c in contradictions):
                                    continue  # Skip upsert for auto-dismissed contradictions

                        await self.stores.graph.async_upsert_relationship_edge(
                            source=source,
                            destination=target,
                            description=description,
                            keywords=keywords,
                            weight=parsed_weight,
                            excerpt_id=excerpt_id,
                            sep=KG_SEP,
                        )
                        total_relationships += 1

                        relationship_id = make_hash(f"{source}_{target}", prefix="rel-")
                        doc_relationship_ids.add(relationship_id)
                        embedding_content = f"{keywords} {source} {target} {description}"
                        embedding_contents.append(embedding_content)
                        relationships_to_upsert.append({
                            "__id__": relationship_id,
                            "__source__": source,
                            "__target__": target,
                            "__inserted_at__": time.time(),
                        })
                elif record_type == 'content_keywords':
                    if len(fields) >= 2:
                        await self.stores.graph.async_set_field('content_keywords', fields[1])

            # Batch all embeddings into a single API call
            if embedding_contents:
                results = await self._get_embeddings(embedding_contents)

                idx = 0
                for entity in entities_to_upsert:
                    vector = np.array(results[idx], dtype=np.float32)
                    entity["__vector__"] = vector
                    idx += 1

                for relation in relationships_to_upsert:
                    vector = np.array(results[idx], dtype=np.float32)
                    relation["__vector__"] = vector
                    idx += 1

            upsert_tasks = []
            if entities_to_upsert:
                upsert_tasks.append(self.stores.entities_db.upsert(entities_to_upsert))
            if relationships_to_upsert:
                upsert_tasks.append(self.stores.relationships_db.upsert(relationships_to_upsert))
            if upsert_tasks:
                await asyncio.gather(*upsert_tasks)

        await self._track_kg_provenance(doc_id, doc_entity_ids, doc_relationship_ids)
        # Saves are batched in import_documents()
        elapsed = time.time() - start_time
        logger.info(f"Extracted {total_entities} entities and {total_relationships} relationships "
                    f"from document {doc_id} in {elapsed:.2f} seconds.")

    async def _track_kg_provenance(self, doc_id: str, entity_ids: set[str], relationship_ids: set[str]):
        async with self.stores.provenance_lock:
            for entity_id in entity_ids:
                await self.stores.doc_entity_map.add(doc_id, entity_id)

            for relationship_id in relationship_ids:
                await self.stores.doc_relationship_map.add(doc_id, relationship_id)
