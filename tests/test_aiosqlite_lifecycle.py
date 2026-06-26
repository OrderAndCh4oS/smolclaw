from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.aiosqlite_lifecycle import close_aiosqlite_connection


@pytest.mark.asyncio
async def test_close_aiosqlite_connection_uses_bounded_thread_join():
    db = MagicMock()
    db.close = AsyncMock()
    db._thread.is_alive.return_value = True

    with patch("app.aiosqlite_lifecycle.asyncio.to_thread", new=AsyncMock()) as to_thread:
        await close_aiosqlite_connection(db, join_timeout=0.25)

    db.close.assert_awaited_once()
    to_thread.assert_awaited_once_with(db._thread.join, 0.25)
