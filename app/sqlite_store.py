import asyncio
import json
import os

import aiosqlite

from app.aiosqlite_lifecycle import close_aiosqlite_connection


class SqliteKvStore:
    """Async KV store backed by a SQLite table."""

    def __init__(self, db_path: str, table: str):
        self.db_path = db_path
        self.table = table
        self._db = None
        self._init_lock = asyncio.Lock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _get_db(self):
        if self._db is None:
            async with self._init_lock:
                if self._db is None:
                    os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
                    self._db = await aiosqlite.connect(self.db_path)
                    await self._db.execute("PRAGMA journal_mode=WAL")
                    await self._db.execute(
                        f"CREATE TABLE IF NOT EXISTS [{self.table}] "
                        f"(key TEXT PRIMARY KEY, value TEXT)"
                    )
                    await self._db.commit()
        return self._db

    async def add(self, key, value):
        db = await self._get_db()
        serialized = json.dumps(value)
        await db.execute(
            f"INSERT OR REPLACE INTO [{self.table}] (key, value) VALUES (?, ?)",
            (str(key), serialized),
        )
        await db.commit()

    async def remove(self, key):
        db = await self._get_db()
        await db.execute(
            f"DELETE FROM [{self.table}] WHERE key = ?", (str(key),)
        )
        await db.commit()

    async def has(self, key) -> bool:
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT 1 FROM [{self.table}] WHERE key = ?", (str(key),)
        )
        row = await cursor.fetchone()
        return row is not None

    async def get_by_key(self, key):
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT value FROM [{self.table}] WHERE key = ?", (str(key),)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    async def get_all(self) -> dict:
        db = await self._get_db()
        cursor = await db.execute(f"SELECT key, value FROM [{self.table}]")
        rows = await cursor.fetchall()
        return {k: json.loads(v) for k, v in rows}

    async def close(self):
        if self._db is not None:
            await close_aiosqlite_connection(self._db)
            self._db = None
