import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.storage_paths import contained_storage_path


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
        with open(path, "w") as f:
            meta = {"key": session.key, "last_consolidated": session.last_consolidated}
            f.write(json.dumps(meta) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg) + "\n")

    def load(self, key: str) -> Optional[Session]:
        path = self._file_path(key)
        return self.load_file(path)

    def load_file(self, path: str) -> Optional[Session]:
        path = os.path.realpath(path)
        root = os.path.realpath(self.sessions_dir)
        if os.path.commonpath([root, path]) != root:
            raise ValueError("Session path escaped the configured directory.")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            lines = f.readlines()
        if not lines:
            return None
        meta = json.loads(lines[0])
        session = Session(key=meta["key"], last_consolidated=meta.get("last_consolidated", 0))
        for line in lines[1:]:
            session.messages.append(json.loads(line))
        return session

    def save_usage(self, session_key: str, usage_data: dict):
        path = contained_storage_path(self.sessions_dir, session_key, ".usage.json")
        with open(path, "w") as f:
            json.dump(usage_data, f, indent=2)

    def load_usage(self, session_key: str) -> Optional[dict]:
        path = contained_storage_path(self.sessions_dir, session_key, ".usage.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)
