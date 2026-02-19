import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


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
        return os.path.join(self.sessions_dir, f"{key}.jsonl")

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
