import base64
import io
from typing import Optional

import aiohttp
import numpy as np
from PIL import Image

from csrcqsf.settings import model_service_url
from globals_vars import logger


def _image_to_base64(image) -> str:
    if isinstance(image, Image.Image):
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    elif isinstance(image, np.ndarray):
        pil_image = Image.fromarray(image.astype("uint8"))
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    elif isinstance(image, bytes):
        return base64.b64encode(image).decode()
    else:
        raise ValueError(f"Unsupported image type: {type(image)}")


def _base64_to_numpy(data: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(data), dtype=np.float32)


class ModelServiceClient:

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or model_service_url).rstrip("/")

    async def _post(self, path: str, json_data: dict) -> dict:
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=json_data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Model service error [{resp.status}]: {text}")
                return await resp.json()

    async def siglip_image_features(self, image) -> np.ndarray:
        data = await self._post("/api/v1/siglip/image-features", {
            "image_base64": _image_to_base64(image),
        })
        return np.array(data["vector"], dtype=np.float32)

    async def siglip_text_features(self, text: str) -> np.ndarray:
        data = await self._post("/api/v1/siglip/text-features", {
            "text": text,
        })
        return np.array(data["vector"], dtype=np.float32)

    async def siglip_batch_images(self, images: list) -> np.ndarray:
        data = await self._post("/api/v1/siglip/batch-images", {
            "images_base64": [_image_to_base64(img) for img in images],
        })
        return np.array(data["vectors"], dtype=np.float32)

    async def dinov2_global_vector(self, image) -> np.ndarray:
        data = await self._post("/api/v1/dinov2/global-vector", {
            "image_base64": _image_to_base64(image),
        })
        return np.array(data["vector"], dtype=np.float32)

    async def dinov2_patch_tokens(self, image) -> np.ndarray:
        data = await self._post("/api/v1/dinov2/patch-tokens", {
            "image_base64": _image_to_base64(image),
        })
        raw = base64.b64decode(data["tokens_base64"])
        shape = tuple(data["shape"])
        return np.frombuffer(raw, dtype=np.float32).reshape(shape)

    async def dinov2_patch_mean(self, image) -> np.ndarray:
        data = await self._post("/api/v1/dinov2/patch-mean", {
            "image_base64": _image_to_base64(image),
        })
        return np.array(data["vector"], dtype=np.float32)

    async def sam_embedding(self, image) -> np.ndarray:
        data = await self._post("/api/v1/sam/embedding", {
            "image_base64": _image_to_base64(image),
        })
        raw = base64.b64decode(data["embedding_base64"])
        shape = tuple(data["shape"])
        return np.frombuffer(raw, dtype=np.float32).reshape(shape)

    async def sam3_preprocess(self, image, item_name: str) -> Optional[Image.Image]:
        data = await self._post("/api/v1/sam3/preprocess", {
            "image_base64": _image_to_base64(image),
            "item_name": item_name,
        })
        if not data.get("success"):
            return None
        img_bytes = base64.b64decode(data["result_image_base64"])
        return Image.open(io.BytesIO(img_bytes))

    async def ocr_recognize(self, image) -> list:
        data = await self._post("/api/v1/ocr/recognize", {
            "image_base64": _image_to_base64(image),
        })
        return data.get("results", [])


_client: Optional[ModelServiceClient] = None


def get_model_client() -> ModelServiceClient:
    global _client
    if _client is None:
        _client = ModelServiceClient()
    return _client
