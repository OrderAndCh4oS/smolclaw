from types import SimpleNamespace

import pytest

from app.voyage_llm import VoyageEmbeddingLlm


class FakeVoyageResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeVoyageClient:
    def __init__(self):
        self.posts = []
        self.closed = False

    async def post(self, url, *, headers, json):
        self.posts.append({"url": url, "headers": headers, "json": json})
        data = [
            {"embedding": [float(index), float(index + 1)], "index": index}
            for index, _ in enumerate(json["input"])
        ]
        return FakeVoyageResponse({
            "data": data,
            "model": json["model"],
            "usage": {"total_tokens": 7},
        })

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_get_embeddings_calls_voyage_api_and_caches(temp_dir):
    client = FakeVoyageClient()
    llm = VoyageEmbeddingLlm(
        embedding_model="voyage-4",
        voyage_api_key="test-key",
        db_path=f"{temp_dir}/test.db",
        client=client,
    )

    first = await llm.get_embeddings(["alpha", "beta"])
    second = await llm.get_embeddings(["alpha", "beta"])

    assert first == [[0.0, 1.0], [1.0, 2.0]]
    assert second == first
    assert len(client.posts) == 1
    assert client.posts[0]["url"] == "https://api.voyageai.com/v1/embeddings"
    assert client.posts[0]["headers"]["Authorization"] == "Bearer test-key"
    assert client.posts[0]["json"] == {
        "input": ["alpha", "beta"],
        "model": "voyage-4",
    }
    await llm.close()
    assert client.closed is False


@pytest.mark.asyncio
async def test_get_embedding_records_usage(temp_dir):
    client = FakeVoyageClient()
    collector = SimpleNamespace(records=[], record=lambda record: collector.records.append(record))
    llm = VoyageEmbeddingLlm(
        embedding_model="voyage-4",
        voyage_api_key="test-key",
        db_path=f"{temp_dir}/test.db",
        client=client,
    )
    llm.usage_collector = collector

    assert await llm.get_embedding("alpha") == [0.0, 1.0]

    assert len(collector.records) == 1
    record = collector.records[0]
    assert record.operation == "embeddings"
    assert record.model == "voyage-4"
    assert record.total_tokens == 7
    await llm.close()


@pytest.mark.asyncio
async def test_missing_voyage_api_key_raises(temp_dir):
    llm = VoyageEmbeddingLlm(
        embedding_model="voyage-4",
        voyage_api_key="",
        db_path=f"{temp_dir}/test.db",
        client=FakeVoyageClient(),
    )

    with pytest.raises(ValueError, match="VOYAGE_API_KEY"):
        await llm.get_embedding("alpha")
    await llm.close()
