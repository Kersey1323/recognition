import base64
import io
from pathlib import Path
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
    """将业务层支持的图片类型统一编码为模型服务请求载荷。"""
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
    """封装小模型服务协议，使业务层只接触稳定的领域结果。"""

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
        """统一处理模型服务超时、错误响应和调用耗时日志。"""
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
                        # 保留远端错误码，索引任务可据此记录准确的失败阶段和原因。
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

    async def _request_binary_to_file(
        self,
        path: str,
        *,
        data,
        destination: Path,
        timeout_seconds: int,
    ) -> Path:
        """流式保存模型文件响应，避免大型分割结果完整驻留主服务内存。"""
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        started_at = time.perf_counter()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=data) as resp:
                    if resp.status != 200:
                        try:
                            payload = await resp.json()
                        except Exception:
                            payload = await resp.text()
                        error_code = payload.get("error_code") if isinstance(payload, dict) else None
                        raise ModelServiceError(
                            resp.status,
                            format_remote_error(payload),
                            error_code=error_code,
                        )
                    with destination.open("wb") as output:
                        async for chunk in resp.content.iter_chunked(1024 * 1024):
                            output.write(chunk)
                    return destination
        finally:
            logger.info(
                "模型服务文件调用: path=%s, elapsed=%.3fs",
                path,
                time.perf_counter() - started_at,
            )

    async def _post(self, path: str, json_data: dict) -> dict:
        return await self._request_json("POST", path, json_data=json_data)

    async def indexing_extract(self, image) -> IndexingExtractResult:
        """一次获取分割结果及全部索引特征，减少同一图片的重复模型推理。"""
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
        # Patch Token 按二进制传输，解码前必须校验类型和形状，避免静默写入错误向量。
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

    async def segment_video_frames(
        self,
        frame_paths: list[Path] | tuple[Path, ...],
        *,
        request_id: str,
        angle_id: str,
        destination: Path,
        timeout_seconds: int,
    ) -> Path:
        """将单个采集角度的连续帧提交给模型服务并保存分割结果 ZIP。"""
        from csrcqsf.modules.railway_parts.services.viewer360_archive import (
            create_frame_archive,
        )

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        request_archive = destination.with_name(f".{destination.stem}-frames.zip")
        create_frame_archive(frame_paths, request_archive)
        try:
            with request_archive.open("rb") as archive_stream:
                form = aiohttp.FormData()
                form.add_field(
                    "frames",
                    archive_stream,
                    filename="frames.zip",
                    content_type="application/zip",
                )
                form.add_field("request_id", request_id)
                form.add_field("angle_id", angle_id)
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                temporary.unlink(missing_ok=True)
                await self._request_binary_to_file(
                    "/api/v1/segmentation/video",
                    data=form,
                    destination=temporary,
                    timeout_seconds=timeout_seconds,
                )
            temporary.replace(destination)
            return destination
        finally:
            request_archive.unlink(missing_ok=True)
            destination.with_suffix(destination.suffix + ".tmp").unlink(missing_ok=True)

    async def require_indexing_extract_capability(self) -> None:
        """在批量索引前确认模型服务具备聚合提取能力。"""
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
        """生成询码描述的 BGE-M3 向量，并校验模型接口契约。"""
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
    # 客户端不持有会话连接，可在进程内复用其地址配置。
    global _client
    if _client is None:
        _client = ModelServiceClient()
    return _client
