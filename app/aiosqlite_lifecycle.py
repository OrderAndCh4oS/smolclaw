import asyncio


async def close_aiosqlite_connection(db, *, join_timeout: float = 2.0):
    await db.close()
    thread = getattr(db, "_thread", None)
    if thread is not None and thread.is_alive():
        await asyncio.to_thread(thread.join, join_timeout)
