import json
import os
from unittest.mock import MagicMock

import pytest

from app.agent_factory import ChildAgentFactory
from app.session import Session, SessionManager


def _make_child_session_key(parent_session_key: str = "parent:root") -> str:
    factory = ChildAgentFactory(
        master_registry=MagicMock(),
        smol_rag=MagicMock(),
        workspace=None,
        session_manager=MagicMock(),
        parent_session_key=parent_session_key,
    )
    return factory.make_session_key("worker", "spawn-sub-1")


class TestSession:
    def test_session_add_message(self):
        session = Session(key="test")
        session.add_message({"role": "user", "content": "hello"})
        session.add_message({"role": "assistant", "content": "hi"})
        assert len(session.messages) == 2

    def test_session_get_history(self):
        session = Session(key="test")
        for i in range(10):
            session.add_message({"role": "user", "content": f"msg-{i}"})
        history = session.get_history(5)
        assert len(history) == 5
        assert history[0]["content"] == "msg-5"
        assert history[-1]["content"] == "msg-9"

    def test_session_clear(self):
        session = Session(key="test")
        session.add_message({"role": "user", "content": "hello"})
        session.clear()
        assert len(session.messages) == 0
        assert session.key == "test"


class TestSessionManager:
    def test_session_manager_get_or_create(self, temp_dir):
        manager = SessionManager(temp_dir)
        session = manager.get_or_create("my-session")
        assert session.key == "my-session"
        assert len(session.messages) == 0

    def test_session_manager_save_and_load(self, temp_dir):
        manager = SessionManager(temp_dir)
        session = manager.get_or_create("persist-test")
        session.add_message({"role": "user", "content": "remember me"})
        session.add_message({"role": "assistant", "content": "noted"})
        manager.save(session)

        manager2 = SessionManager(temp_dir)
        loaded = manager2.load("persist-test")
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["content"] == "remember me"
        assert loaded.messages[1]["content"] == "noted"

    def test_session_manager_jsonl_format(self, temp_dir):
        manager = SessionManager(temp_dir)
        session = manager.get_or_create("format-test")
        session.add_message({"role": "user", "content": "hello"})
        manager.save(session)

        file_path = os.path.join(temp_dir, "format-test.jsonl")
        with open(file_path) as f:
            lines = f.readlines()

        assert len(lines) == 2
        meta = json.loads(lines[0])
        assert meta["key"] == "format-test"
        msg = json.loads(lines[1])
        assert msg["role"] == "user"
        assert msg["content"] == "hello"

    def test_session_last_consolidated_persists(self, temp_dir):
        manager = SessionManager(temp_dir)
        session = manager.get_or_create("consol-test")
        session.add_message({"role": "user", "content": "a"})
        session.last_consolidated = 1
        manager.save(session)

        loaded = manager.load("consol-test")
        assert loaded.last_consolidated == 1

    def test_session_manager_save_and_load_generated_child_session_key(self, temp_dir):
        manager = SessionManager(temp_dir)
        child_key = _make_child_session_key()
        session = Session(key=child_key)
        session.add_message({"role": "user", "content": "remember child session"})

        manager.save(session)

        expected = os.path.join(temp_dir, f"{child_key}.jsonl")
        assert os.path.exists(expected)
        assert ":" not in os.path.basename(expected)

        loaded = manager.load(child_key)
        assert loaded is not None
        assert loaded.key == child_key
        assert loaded.messages[0]["content"] == "remember child session"
