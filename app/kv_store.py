import asyncio
import aiofiles
import json


from app.utilities import create_file_if_not_exists, get_json


class JsonKvStore:
    def __init__(self, file_path, initial_data="{}"):
        self.file_path = file_path
        create_file_if_not_exists(file_path, initial_data)
        self.store = get_json(self.file_path)
        self._lock = asyncio.Lock()

    async def remove(self, key):
        async with self._lock:
            if key in self.store:
                del self.store[key]

    async def add(self, key, value):
        async with self._lock:
            self.store[key] = value

    async def has(self, key):
        async with self._lock:
            return key in self.store

    async def equal(self, key, value):
        async with self._lock:
            return self.store.get(key) == value

    async def get_all(self):
        async with self._lock:
            return self.store.copy()

    async def get_by_key(self, key):
        async with self._lock:
            return self.store.get(key, None)

    async def save(self):
        async with self._lock:
            async with aiofiles.open(self.file_path, 'w') as f:
                await f.write(json.dumps(self.store, indent=2))
