import asyncio
import os
import tempfile
from typing import Optional

import networkx as nx

from app import diagnostics
from app.logger import logger


GRAPH_STORE_SCHEMA_VERSION = 1


class NetworkXGraphStore:
    def __init__(self, file_path):
        self.file_path = file_path
        self._lock = asyncio.Lock()  # Protect concurrent access to graph
        if os.path.exists(file_path):
            try:
                self.graph = nx.read_graphml(file_path)
                logger.info(f"Knowledge graph loaded from {file_path}")
            except Exception as e:
                diagnostics.record_exception(e, boundary="graph_store.load", path=file_path)
                logger.error(f"Error loading knowledge graph from {file_path}: {e}")
                self.graph = nx.Graph()
        else:
            self.graph = nx.Graph()
            logger.info("No existing knowledge graph found; creating a new one.")
        self._ensure_metadata()

    def _ensure_metadata(self):
        self.graph.graph.setdefault("schema_version", str(GRAPH_STORE_SCHEMA_VERSION))

    def _write_graphml_atomic(self):
        self._ensure_metadata()
        directory = os.path.dirname(os.path.realpath(self.file_path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.file_path)}.",
            suffix=".tmp",
            dir=directory,
        )
        os.close(fd)
        try:
            nx.write_graphml(self.graph, temp_path)
            os.replace(temp_path, self.file_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def get_node(self, name):
        logger.debug(f"Getting node {name}")
        # Note: NetworkX dict access is atomic for reads, no lock needed for single dict lookups
        return self.graph.nodes.get(name)

    def get_edge(self, edge):
        logger.debug(f"Getting edge {edge}")
        return self.graph.edges.get(edge)

    def get_node_edges(self, name):
        return list(self.graph.edges(name))

    def add_node(self, name, **kwargs):
        # Synchronous wrapper for use in sync contexts
        logger.info(f"Adding node {name}")
        self.graph.add_node(name, **kwargs)

    def add_edge(self, source, destination, **kwargs):
        # Synchronous wrapper for use in sync contexts
        logger.info(f"Adding edge {(source, destination)}")
        self.graph.add_edge(source, destination, **kwargs)

    def remove_node(self, name):
        if self.graph.has_node(name):
            logger.info(f"Removing node {name}")
            self.graph.remove_node(name)

    def remove_edge(self, source, destination):
        if self.graph.has_edge(source, destination):
            logger.info(f"Removing edge {(source, destination)}")
            self.graph.remove_edge(source, destination)

    def degree(self, name):
        if not self.graph.has_node(name):
            return 0
        return self.graph.degree(name)

    async def async_add_node(self, name, **kwargs):
        """Async version with lock protection for concurrent writes."""
        async with self._lock:
            logger.info(f"Adding node {name}")
            self.graph.add_node(name, **kwargs)

    async def async_add_edge(self, source, destination, **kwargs):
        """Async version with lock protection for concurrent writes."""
        async with self._lock:
            logger.info(f"Adding edge {(source, destination)}")
            self.graph.add_edge(source, destination, **kwargs)

    async def async_remove_node(self, name):
        async with self._lock:
            if self.graph.has_node(name):
                logger.info(f"Removing node {name}")
                self.graph.remove_node(name)

    async def async_remove_edge(self, source, destination):
        async with self._lock:
            if self.graph.has_edge(source, destination):
                logger.info(f"Removing edge {(source, destination)}")
                self.graph.remove_edge(source, destination)

    async def async_set_field(self, key, value):
        """Async version with lock protection for concurrent writes."""
        async with self._lock:
            self.graph.graph[key] = value
            logger.info(f"Graph metadata '{key}' updated to: {value}")

    @staticmethod
    def _split_values(value: Optional[str], sep: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, str):
            value = str(value)
        return [item for item in value.split(sep) if item]

    @staticmethod
    def _merge_values(existing: Optional[str], new_value: str, sep: str, limit: Optional[int] = None) -> str:
        merged = list(dict.fromkeys(NetworkXGraphStore._split_values(existing, sep) + [new_value]))
        if limit is not None:
            merged = merged[-limit:]
        return sep.join(merged)

    async def async_upsert_entity_node(self, name, category, description, excerpt_id, sep):
        """
        Upsert entity attributes atomically to avoid read/modify/write races.
        """
        async with self._lock:
            existing = self.graph.nodes.get(name)
            if existing:
                categories = self._merge_values(existing.get("category"), category, sep)
                descriptions = self._merge_values(existing.get("description"), description, sep, limit=10)
                excerpt_ids = self._merge_values(existing.get("excerpt_id"), excerpt_id, sep)
                self.graph.add_node(
                    name,
                    category=categories,
                    description=descriptions,
                    excerpt_id=excerpt_ids,
                )
                return

            self.graph.add_node(name, category=category, description=description, excerpt_id=excerpt_id)

    async def async_upsert_relationship_edge(
            self, source, destination, description, keywords, weight, excerpt_id, sep
    ):
        """
        Upsert relationship attributes atomically to avoid read/modify/write races.
        """
        async with self._lock:
            existing = self.graph.edges.get((source, destination))
            if existing:
                descriptions = self._merge_values(existing.get("description"), description, sep, limit=10)
                merged_keywords = self._merge_values(existing.get("keywords"), keywords, sep, limit=20)
                excerpt_ids = self._merge_values(existing.get("excerpt_id"), excerpt_id, sep)
                try:
                    existing_weight = float(existing.get("weight", 0.0))
                except (TypeError, ValueError):
                    existing_weight = 0.0
                self.graph.add_edge(
                    source,
                    destination,
                    description=descriptions,
                    keywords=merged_keywords,
                    weight=existing_weight + weight,
                    excerpt_id=excerpt_ids,
                )
                return

            self.graph.add_edge(
                source,
                destination,
                description=description,
                keywords=keywords,
                weight=weight,
                excerpt_id=excerpt_id,
            )

    def save(self):
        self._write_graphml_atomic()

    async def async_save(self):
        """Async version that runs atomic persistence in executor to avoid blocking."""
        async with self._lock:
            await asyncio.to_thread(self._write_graphml_atomic)
            logger.info(f"Graph saved to {self.file_path}")
