import base64
import io
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp
import numpy as np
from PIL import Image

from csrcqsf.core.settings import (
    model_service_index_timeout_sec,
    model_service_url,
)
from csrcqsf.infra.external.error_response import format_remote_error
from csrcqsf.core.logging_config import logger


def _image_to_base64(image) -> str:
    if isinstance(image, Image.Image):
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=90, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    elif isinstance(image, np.ndarray):
        pil_image = Image.fromarray(image.astype("uint8")).convert("RGB")
        buf = io.BytesIO()
        pil_image.save(buf, format="JPEG", quality=90, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    elif isinstance(image, bytes):
        return base64.b64encode(image).decode()
    else:
        raise ValueError(f"Unsupported image type: {type(image)}")


def _base64_to_numpy(data: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(data), dtype=np.float32)


def _image_to_png_bytes(image) -> bytes:
    if isinstance(image, bytes):
        with Image.open(io.BytesIO(image)) as decoded:
            normalized = decoded.convert("RGB")
    elif isinstance(image, np.ndarray):
        normalized = Image.fromarray(image.astype("uint8")).convert("RGB")
    elif isinstance(image, Image.Image):
        normalized = image.convert("RGB")
    else:
        raise ValueError(f"Unsupported image type: {type(image)}")
    stream = io.BytesIO()
    normalized.save(stream, format="PNG")
    return stream.getvalue()


@dataclass(frozen=True)
class IndexingExtractResult:
    segmented_image: Image.Image
    bbox: tuple[int, int, int, int]
    mask_area: int
    selected_prompt: str
    detection_score: float
    siglip_vector: np.ndarray
    dinov2_global_vector: np.ndarray
    dinov2_patch_tokens: np.ndarray


class ModelServiceError(RuntimeError):
    def __init__(self, status: int, detail: str, error_code: str | None = None):
        super().__init__(f"Model service error [{status}]: {detail}")
        self.status = status
        self.detail = detail
        self.error_code = error_code


class ModelServiceClient:

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or model_service_url).rstrip("/")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_data: dict | None = None,
        data=None,
        timeout_seconds: int = 120,
    ) -> dict:
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        started_at = time.perf_counter()
        image_payload_size = len((json_data or {}).get("image_base64") or "")
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method,
                    url,
                    json=json_data,
                    data=data,
                ) as resp:
                    if resp.status != 200:
                        try:
                            payload = await resp.json()
                        except Exception:
                            payload = await resp.text()
                        error_code = (
                            payload.get("error_code")
                            if isinstance(payload, dict)
                            else None
                        )
                        raise ModelServiceError(
                            resp.status,
                            format_remote_error(payload),
                            error_code=error_code,
                        )
                    return await resp.json()
        finally:
            elapsed = time.perf_counter() - started_at
            logger.info(
                f"模型服务调用: path={path}, elapsed={elapsed:.3f}s, "
                f"image_payload={image_payload_size / 1024:.1f}KiB"
            )

    async def _post(self, path: str, json_data: dict) -> dict:
        return await self._request_json("POST", path, json_data=json_data)

    async def indexing_extract(self, image) -> IndexingExtractResult:
        form = aiohttp.FormData()
        form.add_field(
            "file",
            _image_to_png_bytes(image),
            filename="image.png",
            content_type="image/png",
        )
        data = await self._request_json(
            "POST",
            "/api/v1/indexing/extract",
            data=form,
            timeout_seconds=model_service_index_timeout_sec,
        )
        dtype = data.get("dinov2_patch_tokens_dtype")
        if dtype != "float32":
            raise ValueError(f"Unsupported patch token dtype: {dtype}")
        patch_shape = tuple(int(value) for value in data["dinov2_patch_tokens_shape"])
        patch_tokens = np.frombuffer(
            base64.b64decode(data["dinov2_patch_tokens_base64"]),
            dtype=np.float32,
        ).reshape(patch_shape)
        segmented_image = Image.open(
            io.BytesIO(base64.b64decode(data["segmented_image_base64"]))
        ).convert("RGB")
        return IndexingExtractResult(
            segmented_image=segmented_image,
            bbox=tuple(int(value) for value in data["bbox"]),
            mask_area=int(data["mask_area"]),
            selected_prompt=str(data["selected_prompt"]),
            detection_score=float(data["detection_score"]),
            siglip_vector=np.asarray(data["siglip_vector"], dtype=np.float32),
            dinov2_global_vector=np.asarray(
                data["dinov2_global_vector"],
                dtype=np.float32,
            ),
            dinov2_patch_tokens=patch_tokens,
        )

    async def require_indexing_extract_capability(self) -> None:
        health = await self._request_json("GET", "/health")
        if "indexing_extract" in health.get("capabilities", []):
            return
        reason = health.get(
            "indexing_extract_error",
            "model service did not report indexing_extract capability",
        )
        raise RuntimeError(f"Indexing extraction capability unavailable: {reason}")

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

    async def text_embeddings(self, texts: list[str]) -> np.ndarray:
        normalized = [str(text).strip() for text in texts]
        if not normalized or any(not text for text in normalized):
            raise ValueError("文本向量请求不能为空")

        data = await self._post(
            "/api/v1/text/embeddings",
            {"texts": normalized},
        )
        if int(data.get("count", -1)) != len(normalized):
            raise ValueError("模型服务返回的文本向量数量不一致")
        if int(data.get("dim", -1)) != 1024:
            raise ValueError("模型服务返回的文本向量维度不正确")
        try:
            vectors = np.asarray(data.get("vectors"), dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise ValueError("模型服务返回的文本向量维度不正确") from exc
        if vectors.shape != (len(normalized), 1024):
            raise ValueError("模型服务返回的文本向量维度不正确")
        return vectors

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
