import asyncio
import base64
import io

import numpy as np
import pytest
from PIL import Image

from csrcqsf.infra.external.model_client import ModelServiceClient


def _response_payload() -> dict:
    segmented_stream = io.BytesIO()
    Image.new("RGB", (3, 2), "black").save(segmented_stream, format="PNG")
    tokens = np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    return {
        "segmented_image_base64": base64.b64encode(
            segmented_stream.getvalue()
        ).decode("ascii"),
        "bbox": [2, 3, 4, 5],
        "mask_area": 19,
        "selected_prompt": "object",
        "detection_score": 0.82,
        "siglip_vector": [0.1, 0.2],
        "dinov2_global_vector": [0.3, 0.4, 0.5],
        "dinov2_patch_tokens_base64": base64.b64encode(tokens.tobytes()).decode(
            "ascii"
        ),
        "dinov2_patch_tokens_shape": [2, 2],
        "dinov2_patch_tokens_dtype": "float32",
    }


def test_indexing_extract_uses_multipart_file_and_configured_timeout(monkeypatch):
    client = ModelServiceClient(base_url="http://model-service:5555")
    captured = {}

    async def fake_request(method, path, *, data=None, timeout_seconds=None):
        captured.update(
            method=method,
            path=path,
            data=data,
            timeout_seconds=timeout_seconds,
        )
        return _response_payload()

    monkeypatch.setattr(client, "_request_json", fake_request)
    image = Image.new("RGB", (5, 4), "white")

    result = asyncio.run(client.indexing_extract(image))

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/indexing/extract"
    assert captured["timeout_seconds"] == 120
    form_fields = captured["data"]._fields
    assert len(form_fields) == 1
    disposition, headers, content = form_fields[0]
    assert disposition["name"] == "file"
    assert disposition["filename"] == "image.png"
    assert headers["Content-Type"] == "image/png"
    assert content.startswith(b"\x89PNG")
    assert result.segmented_image.size == (3, 2)
    assert result.bbox == (2, 3, 4, 5)
    assert result.mask_area == 19
    assert result.selected_prompt == "object"
    assert result.detection_score == pytest.approx(0.82)
    assert result.siglip_vector.dtype == np.float32
    assert result.dinov2_global_vector.dtype == np.float32
    assert result.dinov2_patch_tokens.dtype == np.float32
    np.testing.assert_array_equal(
        result.dinov2_patch_tokens,
        [[1.0, 2.0], [3.0, 4.0]],
    )


def test_indexing_extract_rejects_unexpected_patch_token_dtype(monkeypatch):
    client = ModelServiceClient(base_url="http://model-service:5555")
    payload = _response_payload()
    payload["dinov2_patch_tokens_dtype"] = "float16"

    async def fake_request(*args, **kwargs):
        return payload

    monkeypatch.setattr(client, "_request_json", fake_request)

    with pytest.raises(ValueError, match="patch token dtype"):
        asyncio.run(client.indexing_extract(Image.new("RGB", (2, 2))))


def test_capability_precheck_requires_indexing_extract(monkeypatch):
    client = ModelServiceClient(base_url="http://model-service:5555")

    async def health_without_capability(*args, **kwargs):
        return {
            "status": "ok",
            "capabilities": [],
            "indexing_extract_error": "FileNotFoundError: /models/sam2",
        }

    monkeypatch.setattr(client, "_request_json", health_without_capability)

    with pytest.raises(RuntimeError, match="/models/sam2"):
        asyncio.run(client.require_indexing_extract_capability())


def test_capability_precheck_succeeds_when_model_service_reports_it(monkeypatch):
    client = ModelServiceClient(base_url="http://model-service:5555")

    async def healthy(*args, **kwargs):
        return {"status": "ok", "capabilities": ["indexing_extract"]}

    monkeypatch.setattr(client, "_request_json", healthy)

    asyncio.run(client.require_indexing_extract_capability())
