#!/usr/bin/env python3
"""One-time migration: import existing JSON store data into SQLite.

Usage:
    python scripts/migrate_json_to_sqlite.py

Reads the old JSON files from store/ and cache/ directories and inserts
their data into the new smolclaw.db SQLite database.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.definitions import DATA_DIR, SQLITE_DB_PATH
from app.sqlite_store import SqliteKvStore
from app.sqlite_mapping_store import SqliteMappingStore

CACHE_DIR = os.path.join(os.path.dirname(DATA_DIR), "cache")

# Old JSON file paths
OLD_FILES = {
    "source_to_doc": os.path.join(DATA_DIR, "source_to_doc_id_map.json"),
    "doc_to_source": os.path.join(DATA_DIR, "doc_id_to_source_map.json"),
    "doc_to_excerpt": os.path.join(DATA_DIR, "doc_id_to_excerpt_ids.json"),
    "doc_to_entity": os.path.join(DATA_DIR, "doc_id_to_entity_ids.json"),
    "doc_to_relationship": os.path.join(DATA_DIR, "doc_id_to_relationship_ids.json"),
    "entity_to_doc": os.path.join(DATA_DIR, "entity_id_to_doc_ids.json"),
    "relationship_to_doc": os.path.join(DATA_DIR, "relationship_id_to_doc_ids.json"),
    "excerpts": os.path.join(DATA_DIR, "excerpt_db.json"),
    "query_cache": os.path.join(CACHE_DIR, "query_cache.json"),
    "embedding_cache": os.path.join(CACHE_DIR, "embedding_cache.json"),
}


def load_json(path):
    if not os.path.exists(path):
        print(f"  SKIP (not found): {path}")
        return None
    with open(path) as f:
        data = json.load(f)
    print(f"  Loaded {len(data)} entries from {path}")
    return data


async def migrate():
    print(f"Migrating to SQLite: {SQLITE_DB_PATH}\n")

    # --- KV stores ---
    for table_name, json_path in [
        ("excerpts", OLD_FILES["excerpts"]),
        ("query_cache", OLD_FILES["query_cache"]),
        ("embedding_cache", OLD_FILES["embedding_cache"]),
    ]:
        data = load_json(json_path)
        if data is None:
            continue
        store = SqliteKvStore(SQLITE_DB_PATH, table_name)
        count = 0
        for key, value in data.items():
            await store.add(key, value)
            count += 1
        await store.close()
        print(f"  -> {table_name}: {count} rows inserted\n")

    # --- Mapping stores (forward maps) ---
    # source_to_doc is 1:1
    data = load_json(OLD_FILES["source_to_doc"])
    if data:
        store = SqliteMappingStore(SQLITE_DB_PATH, "source_doc_map", "source", "doc_id")
        count = 0
        for source, doc_id in data.items():
            await store.add(source, doc_id)
            count += 1
        await store.close()
        print(f"  -> source_doc_map: {count} rows inserted\n")

    # doc_to_excerpt is 1:many (value is list)
    data = load_json(OLD_FILES["doc_to_excerpt"])
    if data:
        store = SqliteMappingStore(SQLITE_DB_PATH, "doc_excerpt_map", "doc_id", "excerpt_id")
        count = 0
        for doc_id, excerpt_ids in data.items():
            if isinstance(excerpt_ids, list):
                for eid in excerpt_ids:
                    await store.add(doc_id, eid)
                    count += 1
        await store.close()
        print(f"  -> doc_excerpt_map: {count} rows inserted\n")

    # doc_to_entity is 1:many
    data = load_json(OLD_FILES["doc_to_entity"])
    if data:
        store = SqliteMappingStore(SQLITE_DB_PATH, "doc_entity_map", "doc_id", "entity_id")
        count = 0
        for doc_id, entity_ids in data.items():
            if isinstance(entity_ids, list):
                for eid in entity_ids:
                    await store.add(doc_id, eid)
                    count += 1
        await store.close()
        print(f"  -> doc_entity_map: {count} rows inserted\n")

    # doc_to_relationship is 1:many
    data = load_json(OLD_FILES["doc_to_relationship"])
    if data:
        store = SqliteMappingStore(SQLITE_DB_PATH, "doc_relationship_map", "doc_id", "relationship_id")
        count = 0
        for doc_id, rel_ids in data.items():
            if isinstance(rel_ids, list):
                for rid in rel_ids:
                    await store.add(doc_id, rid)
                    count += 1
        await store.close()
        print(f"  -> doc_relationship_map: {count} rows inserted\n")

    # Note: entity_to_doc and relationship_to_doc reverse maps are NOT migrated
    # because they are now derived from the forward maps via SQL reverse lookups.

    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
