import asyncio
import os

import aiosqlite

from app.aiosqlite_lifecycle import close_aiosqlite_connection


class SqliteMappingStore:
    """Relational many-to-many (or 1:1) mapping store backed by SQLite.

    For a 1:1 map (source↔doc), each left key maps to exactly one right key.
    For 1:many maps (doc→excerpts), one left key maps to many right keys.
    """

    def __init__(self, db_path: str, table: str, left_col: str, right_col: str):
        self.db_path = db_path
        self.table = table
        self.left_col = left_col
        self.right_col = right_col
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
                        f"({self.left_col} TEXT NOT NULL, "
                        f"{self.right_col} TEXT NOT NULL, "
                        f"PRIMARY KEY ({self.left_col}, {self.right_col}))"
                    )
                    await self._db.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{self.table}_{self.right_col} "
                        f"ON [{self.table}] ({self.right_col})"
                    )
                    await self._db.commit()
        return self._db

    async def add(self, left_key: str, right_key: str):
        """Insert a single (left, right) pair."""
        db = await self._get_db()
        await db.execute(
            f"INSERT OR IGNORE INTO [{self.table}] ({self.left_col}, {self.right_col}) "
            f"VALUES (?, ?)",
            (str(left_key), str(right_key)),
        )
        await db.commit()

    async def add_many(self, left_key: str, right_keys: list[str]):
        """Set all right-side values for a left key (replaces existing)."""
        db = await self._get_db()
        await db.execute(
            f"DELETE FROM [{self.table}] WHERE {self.left_col} = ?",
            (str(left_key),),
        )
        await db.executemany(
            f"INSERT INTO [{self.table}] ({self.left_col}, {self.right_col}) "
            f"VALUES (?, ?)",
            [(str(left_key), str(rk)) for rk in right_keys],
        )
        await db.commit()

    async def remove_by_left(self, left_key: str):
        """Remove all rows with the given left key."""
        db = await self._get_db()
        await db.execute(
            f"DELETE FROM [{self.table}] WHERE {self.left_col} = ?",
            (str(left_key),),
        )
        await db.commit()

    async def remove_by_right(self, right_key: str):
        """Remove all rows with the given right key."""
        db = await self._get_db()
        await db.execute(
            f"DELETE FROM [{self.table}] WHERE {self.right_col} = ?",
            (str(right_key),),
        )
        await db.commit()

    async def get_by_left(self, left_key: str) -> list[str]:
        """Get all right values for a left key."""
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT {self.right_col} FROM [{self.table}] WHERE {self.left_col} = ?",
            (str(left_key),),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_by_right(self, right_key: str) -> list[str]:
        """Get all left values for a right key."""
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT {self.left_col} FROM [{self.table}] WHERE {self.right_col} = ?",
            (str(right_key),),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def has_left(self, left_key: str) -> bool:
        """Check if any rows exist with the given left key."""
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT 1 FROM [{self.table}] WHERE {self.left_col} = ? LIMIT 1",
            (str(left_key),),
        )
        row = await cursor.fetchone()
        return row is not None

    async def has_right(self, right_key: str) -> bool:
        """Check if any rows exist with the given right key."""
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT 1 FROM [{self.table}] WHERE {self.right_col} = ? LIMIT 1",
            (str(right_key),),
        )
        row = await cursor.fetchone()
        return row is not None

    async def get_right_single(self, left_key: str) -> str | None:
        """For 1:1 maps — get the single right value for a left key, or None."""
        db = await self._get_db()
        cursor = await db.execute(
            f"SELECT {self.right_col} FROM [{self.table}] WHERE {self.left_col} = ? LIMIT 1",
            (str(left_key),),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def equal_right(self, left_key: str, right_key: str) -> bool:
        """For 1:1 maps — check if left_key maps to exactly right_key."""
        result = await self.get_right_single(left_key)
        return result == right_key

    async def close(self):
        if self._db is not None:
            await close_aiosqlite_connection(self._db)
            self._db = None
