import base64

import numpy as np
from PIL import Image

from csrcqsf.infra.external.model_client import ModelServiceClient, _image_to_base64


def test_pil_image_transport_uses_compact_jpeg_payload():
    pixels = np.random.default_rng(7).integers(0, 256, size=(240, 320, 3), dtype=np.uint8)
    encoded = _image_to_base64(Image.fromarray(pixels, mode="RGB"))

    payload = base64.b64decode(encoded)

    assert payload.startswith(b"\xff\xd8")
    assert len(payload) < pixels.nbytes


def test_model_client_does_not_expose_removed_sam3_api():
    client = ModelServiceClient(base_url="http://model-service:5555")

    assert not hasattr(client, "sam3_preprocess")
    assert not hasattr(client, "supports_model")
    assert not hasattr(client, "_get")
