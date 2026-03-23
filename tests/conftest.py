import asyncio
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import numpy as np

from app.graph_store import NetworkXGraphStore
from app.sqlite_store import SqliteKvStore
from app.sqlite_mapping_store import SqliteMappingStore
from app.vector_store import SqliteVectorStore


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_graph_path(temp_dir):
    """Provide a temporary path for graph storage."""
    return os.path.join(temp_dir, "test_graph.graphml")


@pytest.fixture
def temp_vector_db_path(temp_dir):
    """Provide a temporary path for vector DB storage."""
    return os.path.join(temp_dir, "test_vectors")


@pytest.fixture
def graph_store(temp_graph_path):
    """Create a NetworkXGraphStore instance for testing."""
    store = NetworkXGraphStore(temp_graph_path)
    # Loads automatically in __init__
    yield store


@pytest.fixture
def vector_store(temp_vector_db_path):
    """Create a SqliteVectorStore instance for testing."""
    store = SqliteVectorStore(temp_vector_db_path, dimensions=1536)
    yield store


@pytest.fixture
def mock_openai_llm():
    """Mock OpenAI LLM for testing without API calls."""
    mock_llm = MagicMock()

    # Mock embedding generation (plural - for batches)
    async def mock_get_embeddings(texts):
        return [np.random.rand(1536).tolist() for _ in texts]

    # Mock embedding generation (singular - for single text)
    async def mock_get_embedding(text):
        return np.random.rand(1536).tolist()

    # Mock completion
    async def mock_get_completion(text, **kwargs):
        return "Mock completion response"

    mock_llm.get_embeddings = AsyncMock(side_effect=mock_get_embeddings)
    mock_llm.get_embedding = AsyncMock(side_effect=mock_get_embedding)
    mock_llm.get_completion = AsyncMock(side_effect=mock_get_completion)

    return mock_llm


@pytest.fixture
def sample_entities():
    """Provide sample entity data for testing."""
    return [
        {
            "entity_name": "Python",
            "entity_type": "Programming Language",
            "description": "A high-level programming language",
            "source_id": "doc1"
        },
        {
            "entity_name": "JavaScript",
            "entity_type": "Programming Language",
            "description": "A scripting language for web development",
            "source_id": "doc1"
        },
        {
            "entity_name": "FastAPI",
            "entity_type": "Framework",
            "description": "A modern web framework for Python",
            "source_id": "doc2"
        }
    ]


@pytest.fixture
def sample_relationships():
    """Provide sample relationship data for testing."""
    return [
        {
            "source": "FastAPI",
            "target": "Python",
            "description": "FastAPI is built with Python",
            "keywords": "framework, built-with",
            "weight": 1.0,
            "source_id": "doc2"
        },
        {
            "source": "Python",
            "target": "JavaScript",
            "description": "Both are popular programming languages",
            "keywords": "comparison, alternatives",
            "weight": 0.5,
            "source_id": "doc1"
        }
    ]


@pytest.fixture
def sample_document_content():
    """Provide sample document content for testing."""
    return """# Python Programming

Python is a high-level, interpreted programming language known for its simplicity and readability.

## Features
- Easy to learn syntax
- Extensive standard library
- Large ecosystem of third-party packages

## Popular Frameworks
FastAPI is a modern web framework built with Python that enables building APIs quickly.

## Code Example
```python
def hello_world():
    print("Hello, World!")
```
"""


@pytest.fixture
def sample_excerpts():
    """Provide sample excerpts for testing."""
    return [
        "Python is a high-level programming language.",
        "FastAPI is a modern web framework for Python.",
        "JavaScript is used for web development.",
        "Both Python and JavaScript are popular languages."
    ]


@pytest.fixture
def large_entity_set():
    """Generate a large set of entities for performance testing."""
    entities = []
    for i in range(1000):
        entities.append({
            "entity_name": f"Entity_{i}",
            "entity_type": f"Type_{i % 10}",
            "description": f"Description for entity {i} " * 10,  # Make descriptions longer
            "source_id": f"doc_{i % 100}"
        })
    return entities


@pytest.fixture
def mock_smol_rag():
    """Mock SmolRag for testing memory tools and agent loop."""
    mock = MagicMock()
    mock.mix_query = AsyncMock(return_value="Mock query result")
    mock.ingest_text = AsyncMock()
    mock.remove_document_by_source = AsyncMock()
    mock.graph = MagicMock()
    return mock


@pytest.fixture
def mock_tool_llm():
    """Mock LLM with tool completion support for agent loop tests."""
    mock = MagicMock()
    mock.get_tool_completion = AsyncMock(return_value={
        "content": "Mock response",
        "tool_calls": None,
        "has_tool_calls": False,
    })
    return mock


@pytest.fixture
def sessions_dir(temp_dir):
    """Temp directory for session storage."""
    d = os.path.join(temp_dir, "sessions")
    os.makedirs(d)
    return d


import json


class FakeWebSocket:
    """Queue-based fake WebSocket for testing the gateway protocol."""

    def __init__(self):
        self._inbox = asyncio.Queue()
        self._messages: list = []
        self._closed = False

    async def send(self, data):
        self._messages.append(json.loads(data))

    async def recv(self):
        return await self._inbox.get()

    async def close(self, code=None, reason=None):
        _ = code, reason
        self._closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return self._inbox.get_nowait()
        except asyncio.QueueEmpty:
            raise StopAsyncIteration


@pytest.fixture
def fake_ws():
    """Return a fresh FakeWebSocket instance."""
    return FakeWebSocket()
