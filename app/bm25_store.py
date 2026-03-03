import asyncio
import json
import math
import os
import re
from collections import Counter

import aiosqlite


class BM25Store:
    """In-memory BM25 index backed by SQLite for durability.

    Okapi BM25 with k1=1.5, b=0.75. Tokenizer is simple word splitting.
    """

    def __init__(self, db_path: str, table: str = "bm25_index", k1: float = 1.5, b: float = 0.75):
        self.db_path = db_path
        self.table = table
        self.k1 = k1
        self.b = b
        self._docs: dict[str, Counter] = {}  # doc_id -> term frequency Counter
        self._doc_lengths: dict[str, int] = {}  # doc_id -> total token count
        self._avg_dl: float = 0.0
        self._idf_cache: dict[str, float] = {}
        self._db = None
        self._loaded = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"\w+", text.lower())

    def _recompute_stats(self):
        if self._docs:
            self._avg_dl = sum(self._doc_lengths.values()) / len(self._docs)
        else:
            self._avg_dl = 0.0
        self._recompute_idf()

    def _recompute_idf(self):
        self._idf_cache.clear()
        n = len(self._docs)
        if n == 0:
            return
        # Collect document frequency for each term
        df: dict[str, int] = {}
        for tf in self._docs.values():
            for term in tf:
                df[term] = df.get(term, 0) + 1
        for term, freq in df.items():
            self._idf_cache[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)

    async def _get_db(self):
        if self._db is None:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            self._db = await aiosqlite.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute(
                f"CREATE TABLE IF NOT EXISTS [{self.table}] "
                f"(doc_id TEXT PRIMARY KEY, tokens TEXT)"
            )
            await self._db.commit()
        return self._db

    async def _ensure_loaded_unlocked(self):
        if self._loaded:
            return
        db = await self._get_db()
        cursor = await db.execute(f"SELECT doc_id, tokens FROM [{self.table}]")
        rows = await cursor.fetchall()
        docs = {}
        doc_lengths = {}
        for doc_id, tokens_json in rows:
            tf = Counter(json.loads(tokens_json))
            docs[doc_id] = tf
            doc_lengths[doc_id] = sum(tf.values())
        self._docs = docs
        self._doc_lengths = doc_lengths
        self._recompute_stats()
        self._loaded = True

    async def add(self, doc_id: str, text: str):
        async with self._lock:
            await self._ensure_loaded_unlocked()
            tokens = self._tokenize(text)
            tf = Counter(tokens)
            self._docs[doc_id] = tf
            self._doc_lengths[doc_id] = len(tokens)
            self._recompute_stats()
            db = await self._get_db()
            await db.execute(
                f"INSERT OR REPLACE INTO [{self.table}] (doc_id, tokens) VALUES (?, ?)",
                (doc_id, json.dumps(dict(tf))),
            )
            await db.commit()

    async def remove(self, doc_id: str):
        async with self._lock:
            await self._ensure_loaded_unlocked()
            if doc_id not in self._docs:
                return
            del self._docs[doc_id]
            del self._doc_lengths[doc_id]
            self._recompute_stats()
            db = await self._get_db()
            await db.execute(
                f"DELETE FROM [{self.table}] WHERE doc_id = ?", (doc_id,)
            )
            await db.commit()

    async def query(self, text: str, top_k: int = 10) -> list[dict]:
        async with self._lock:
            await self._ensure_loaded_unlocked()
            if not self._docs:
                return []
            docs = dict(self._docs)
            doc_lengths = dict(self._doc_lengths)
            avg_dl = self._avg_dl
            idf_cache = dict(self._idf_cache)
        query_tokens = self._tokenize(text)
        if not query_tokens:
            return []

        scores: dict[str, float] = {}
        for token in query_tokens:
            idf = idf_cache.get(token, 0.0)
            if idf <= 0:
                continue
            for doc_id, tf in docs.items():
                if token not in tf:
                    continue
                freq = tf[token]
                dl = doc_lengths[doc_id]
                numerator = freq * (self.k1 + 1)
                denominator = freq + self.k1 * (1 - self.b + self.b * dl / avg_dl)
                score = idf * (numerator / denominator)
                scores[doc_id] = scores.get(doc_id, 0.0) + score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [{"doc_id": doc_id, "score": score} for doc_id, score in ranked]

    async def save(self):
        """No-op — writes are immediate. Preserved for API compatibility."""
        pass

    async def close(self):
        async with self._lock:
            if self._db is not None:
                await self._db.close()
                self._db = None
