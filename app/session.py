import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.storage_paths import atomic_write_text, contained_storage_path, load_with_backup


@dataclass
class Session:
    key: str
    messages: List[Dict] = field(default_factory=list)
    last_consolidated: int = 0

    def add_message(self, message: Dict):
        self.messages.append(message)

    def get_history(self, n: int) -> List[Dict]:
        return self.messages[-n:]

    def clear(self):
        self.messages = []


class SessionManager:
    def __init__(self, sessions_dir: str):
        self.sessions_dir = sessions_dir
        os.makedirs(sessions_dir, exist_ok=True)

    def _file_path(self, key: str) -> str:
        return contained_storage_path(self.sessions_dir, key, ".jsonl")

    def get_or_create(self, key: str) -> Session:
        existing = self.load(key)
        if existing is not None:
            return existing
        return Session(key=key)

    def save(self, session: Session):
        path = self._file_path(session.key)
        meta = {"key": session.key, "last_consolidated": session.last_consolidated}
        lines = [json.dumps(meta)]
        lines.extend(json.dumps(msg) for msg in session.messages)
        atomic_write_text(path, "\n".join(lines) + "\n")

    def load(self, key: str) -> Optional[Session]:
        path = self._file_path(key)
        return self.load_file(path)

    def load_file(self, path: str) -> Optional[Session]:
        path = os.path.realpath(path)
        root = os.path.realpath(self.sessions_dir)
        if os.path.commonpath([root, path]) != root:
            raise ValueError("Session path escaped the configured directory.")
        return load_with_backup(path, self._load_file_once)

    def _load_file_once(self, path: str) -> Optional[Session]:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return None
        meta = json.loads(lines[0])
        session = Session(key=meta["key"], last_consolidated=meta.get("last_consolidated", 0))
        for line in lines[1:]:
            session.messages.append(json.loads(line))
        return session
