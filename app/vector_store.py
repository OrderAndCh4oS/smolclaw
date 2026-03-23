import asyncio
import json
import os

import aiosqlite
import numpy as np


class SqliteVectorStore:
    """Vector store backed by SQLite with an in-memory matrix for fast queries."""

    def __init__(self, db_path: str, dimensions: int, table: str = "vectors"):
        self.db_path = db_path
        self.dimensions = dimensions
        self.table = table
        self._db = None
        self._loaded = False
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._keys: list[str] = []
        self._rows: list[dict] = []
        self._matrix = np.empty((0, self.dimensions), dtype=np.float32)
        self._index: dict[str, int] = {}

    async def _get_db(self):
        if self._db is None:
            async with self._init_lock:
                if self._db is None:
                    os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
                    self._db = await aiosqlite.connect(self.db_path)
                    await self._db.execute("PRAGMA journal_mode=WAL")
                    await self._db.execute(
                        f"CREATE TABLE IF NOT EXISTS [{self.table}] "
                        "(key TEXT PRIMARY KEY, payload TEXT NOT NULL, vector BLOB NOT NULL)"
                    )
                    await self._db.commit()
        return self._db

    @staticmethod
    def _serialize_id(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _normalize_vector(self, vector) -> np.ndarray:
        array = np.asarray(vector, dtype=np.float32)
        if array.ndim != 1 or array.shape[0] != self.dimensions:
            raise ValueError(f"Vector must be 1-D with {self.dimensions} dimensions")
        norm = np.linalg.norm(array)
        if norm == 0:
            raise ValueError("Vector norm must be non-zero")
        return array / norm

    async def _ensure_loaded_unlocked(self):
        if self._loaded:
            return
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT key, payload, vector FROM [{self.table}] ORDER BY rowid"
        )
        rows = await cursor.fetchall()
        keys: list[str] = []
        data_rows: list[dict] = []
        matrix = np.empty((len(rows), self.dimensions), dtype=np.float32)
        for idx, (key, payload_json, vector_blob) in enumerate(rows):
            payload = json.loads(payload_json)
            vector = np.frombuffer(vector_blob, dtype=np.float32)
            if vector.size != self.dimensions:
                raise ValueError(
                    f"Stored vector in table {self.table} has {vector.size} dimensions, "
                    f"expected {self.dimensions}"
                )
            keys.append(key)
            data_rows.append(payload)
            matrix[idx] = vector
        self._keys = keys
        self._rows = data_rows
        self._matrix = matrix
        self._index = {key: idx for idx, key in enumerate(self._keys)}
        self._loaded = True

    async def upsert(self, rows):
        async with self._lock:
            await self._ensure_loaded_unlocked()
            if not rows:
                return

            db = await self._get_db()
            inserts: list[tuple[str, dict, np.ndarray]] = []
            serialized_rows = []

            for row in rows:
                if "__id__" not in row or "__vector__" not in row:
                    raise KeyError("Vector rows must include __id__ and __vector__")
                key = self._serialize_id(row["__id__"])
                payload = {k: v for k, v in row.items() if k != "__vector__"}
                vector = self._normalize_vector(row["__vector__"])
                serialized_rows.append((
                    key,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    vector.astype(np.float32).tobytes(),
                ))

                if key in self._index:
                    idx = self._index[key]
                    self._rows[idx] = payload
                    self._matrix[idx] = vector
                else:
                    inserts.append((key, payload, vector))

            if inserts:
                new_vectors = np.array([vector for _, _, vector in inserts], dtype=np.float32)
                if len(self._rows):
                    self._matrix = np.vstack([self._matrix, new_vectors])
                else:
                    self._matrix = new_vectors
                start_idx = len(self._rows)
                for offset, (key, payload, _vector) in enumerate(inserts):
                    self._keys.append(key)
                    self._rows.append(payload)
                    self._index[key] = start_idx + offset

            await db.executemany(
                f"INSERT OR REPLACE INTO [{self.table}] (key, payload, vector) VALUES (?, ?, ?)",
                serialized_rows,
            )
            await db.commit()

    async def delete(self, ids):
        async with self._lock:
            await self._ensure_loaded_unlocked()
            delete_keys = {self._serialize_id(value) for value in ids}
            if not delete_keys:
                return

            keep_indices = [idx for idx, key in enumerate(self._keys) if key not in delete_keys]
            self._keys = [self._keys[idx] for idx in keep_indices]
            self._rows = [self._rows[idx] for idx in keep_indices]
            if keep_indices:
                self._matrix = self._matrix[keep_indices]
            else:
                self._matrix = np.empty((0, self.dimensions), dtype=np.float32)
            self._index = {key: idx for idx, key in enumerate(self._keys)}

            db = await self._get_db()
            await db.executemany(
                f"DELETE FROM [{self.table}] WHERE key = ?",
                [(key,) for key in delete_keys],
            )
            await db.commit()

    async def query(self, query, top_k=10, better_than_threshold=0.02, filter_lambda=None):
        async with self._lock:
            await self._ensure_loaded_unlocked()
            if not len(self._rows) or top_k <= 0:
                return []

            query_vector = self._normalize_vector(query)
            if filter_lambda is None:
                filter_index = np.arange(len(self._rows))
                use_matrix = self._matrix
            else:
                filter_index = np.array(
                    [idx for idx, row in enumerate(self._rows) if filter_lambda(dict(row))],
                    dtype=int,
                )
                if filter_index.size == 0:
                    return []
                use_matrix = self._matrix[filter_index]

            scores = np.dot(use_matrix, query_vector)
            top_k = min(top_k, len(filter_index))
            sort_index = np.argsort(scores)[-top_k:][::-1]
            sort_abs_index = filter_index[sort_index]
            results = []
            for abs_i, rel_i in zip(sort_abs_index, sort_index):
                score = float(scores[rel_i])
                if better_than_threshold is not None and score < better_than_threshold:
                    break
                results.append({**self._rows[int(abs_i)], "__metrics__": score})
            return results

    async def get(self, ids):
        async with self._lock:
            await self._ensure_loaded_unlocked()
            lookup = {self._serialize_id(value) for value in ids}
            return [dict(row) for key, row in zip(self._keys, self._rows) if key in lookup]

    async def save(self):
        async with self._lock:
            await self._ensure_loaded_unlocked()
            if self._db is not None:
                await self._db.commit()

    async def close(self):
        async with self._lock:
            if self._db is not None:
                await self._db.close()
                self._db = None
                self._loaded = False
