import asyncio

import numpy as np
import pytest

from csrcqsf.infra.external.model_client import ModelServiceClient


def test_text_embeddings_posts_batch_and_returns_float32_matrix(monkeypatch):
    client = ModelServiceClient(base_url="http://model-service:5555")
    captured = {}

    async def fake_post(path, payload):
        captured.update(path=path, payload=payload)
        return {
            "vectors": [[0.1] * 1024, [0.2] * 1024],
            "dim": 1024,
            "count": 2,
            "model": "bge-m3",
        }

    monkeypatch.setattr(client, "_post", fake_post)

    result = asyncio.run(client.text_embeddings(["监控室对面窗帘", "底板螺栓"]))

    assert captured == {
        "path": "/api/v1/text/embeddings",
        "payload": {"texts": ["监控室对面窗帘", "底板螺栓"]},
    }
    assert result.shape == (2, 1024)
    assert result.dtype == np.float32


@pytest.mark.parametrize("texts", [[], [""], ["  "]])
def test_text_embeddings_rejects_empty_texts(texts):
    client = ModelServiceClient(base_url="http://model-service:5555")

    with pytest.raises(ValueError, match="文本向量请求不能为空"):
        asyncio.run(client.text_embeddings(texts))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"vectors": [[0.1] * 1024], "dim": 1024, "count": 1},
            "文本向量数量不一致",
        ),
        (
            {"vectors": [[0.1] * 12, [0.2] * 12], "dim": 12, "count": 2},
            "文本向量维度不正确",
        ),
        (
            {"vectors": [[0.1] * 1024, [0.2] * 100], "dim": 1024, "count": 2},
            "文本向量维度不正确",
        ),
    ],
)
def test_text_embeddings_validates_model_response(monkeypatch, payload, message):
    client = ModelServiceClient(base_url="http://model-service:5555")

    async def fake_post(_path, _payload):
        return payload

    monkeypatch.setattr(client, "_post", fake_post)

    with pytest.raises(ValueError, match=message):
        asyncio.run(client.text_embeddings(["描述一", "描述二"]))
