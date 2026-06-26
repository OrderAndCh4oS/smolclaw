import asyncio


async def close_aiosqlite_connection(db, *, join_timeout: float = 2.0, to_thread=None):
    await db.close()
    thread = getattr(db, "_thread", None)
    if thread is not None and thread.is_alive():
        to_thread = to_thread or asyncio.to_thread
        await to_thread(thread.join, join_timeout)
