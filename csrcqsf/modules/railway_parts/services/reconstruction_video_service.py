"""三维重构源视频的直传、分片上传和本地兜底同步门面。"""

from __future__ import annotations

import math
import re
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from csrcqsf.modules.railway_parts.services import source_video_service, upload_service

# 依赖由 reconstruction_service 兼容门面注入，保持原调用入口不变。
run_sync: Any = None
get_id: Any = None
logger: Any = None
Part: Any = None
SessionLocal: Any = None
Items: Any = None
ReconstructionVideoUploadSession: Any = None
ReconstructionBusinessError: Any = None
LocalFilePartReader: Any = None
minio_env_configured: Any = None
minio_reconstruction_video_bucket: Any = None
_get_minio_helpers: Any = None

PartType = Any
ItemsType = Any


def bind_runtime_dependencies(
    reconstruction_service_module: ModuleType | None = None,
) -> None:
    """绑定上传实现需要的数据库、MinIO 和本地文件依赖。"""
    if reconstruction_service_module is None:
        from csrcqsf.modules.railway_parts.services import (
            reconstruction_service as reconstruction_service_module,
        )

    globals().update(
        {
            "datetime": reconstruction_service_module.datetime,
            "timedelta": reconstruction_service_module.timedelta,
            "math": reconstruction_service_module.math,
            "os": reconstruction_service_module.os,
            "re": reconstruction_service_module.re,
            "urlsplit": reconstruction_service_module.urlsplit,
            "urlunsplit": reconstruction_service_module.urlunsplit,
            "Path": reconstruction_service_module.Path,
            "uuid4": reconstruction_service_module.uuid4,
            "run_sync": reconstruction_service_module.run_sync,
            "get_id": reconstruction_service_module.get_id,
            "logger": reconstruction_service_module.logger,
            "Part": reconstruction_service_module.Part,
            "SessionLocal": reconstruction_service_module.SessionLocal,
            "Items": reconstruction_service_module.Items,
            "ReconstructionVideoUploadSession": reconstruction_service_module.ReconstructionVideoUploadSession,
            "ReconstructionBusinessError": reconstruction_service_module.ReconstructionBusinessError,
            "LocalFilePartReader": reconstruction_service_module.LocalFilePartReader,
            "minio_env_configured": reconstruction_service_module.minio_env_configured,
            "minio_reconstruction_video_bucket": reconstruction_service_module.minio_reconstruction_video_bucket,
            "_get_minio_helpers": reconstruction_service_module._get_minio_helpers,
        }
    )


def _runtime_context():
    return SimpleNamespace(**globals())


def _safe_filename(filename: str | None) -> str:
    raw_name = Path(filename or "source_video.mp4").name
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    return safe_name or "source_video.mp4"


def _choose_multipart_part_size(file_size: int) -> int:
    # 分片大小同时满足 MinIO 最小分片和最多一万片限制。
    min_part_size = 5 * 1024 * 1024
    max_part_size = 5 * 1024 * 1024 * 1024
    mb_10 = 10 * 1024 * 1024
    mb_20 = 20 * 1024 * 1024
    mb_50 = 50 * 1024 * 1024
    mb_100 = 100 * 1024 * 1024
    gb_1 = 1024 * 1024 * 1024
    gb_5 = 5 * 1024 * 1024 * 1024

    if file_size <= mb_100:
        part_size = mb_10
    elif file_size <= gb_1:
        part_size = mb_20
    elif file_size <= gb_5:
        part_size = mb_50
    else:
        part_size = math.ceil(file_size / 10000)

    return min(max(part_size, min_part_size), max_part_size)


def _build_source_video_multipart_object_name(cls, item_id: int, file_name: str) -> str:
    safe_name = cls._safe_filename(file_name)
    date_dir = datetime.now().strftime("%Y%m%d")
    return f"raw-videos/{item_id}/{date_dir}/{get_id()}_{safe_name}"


def _multipart_upload_expires_at() -> str:
    return (datetime.utcnow() + timedelta(days=7)).isoformat()


def _strip_presigned_url_host(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))


def _normalize_complete_parts(cls, parts: list[dict], total_parts: int) -> list[PartType]:
    # 完成请求必须覆盖连续的全部分片，防止 MinIO 合并出缺段视频。
    normalized_parts = []
    for item in sorted(parts, key=lambda value: int(value["part_number"])):
        normalized_parts.append(
            Part(
                part_number=int(item["part_number"]),
                etag=str(item["etag"]).strip().strip('"'),
            )
        )

    expected_numbers = list(range(1, total_parts + 1))
    actual_numbers = [part.part_number for part in normalized_parts]
    if actual_numbers != expected_numbers:
        raise ReconstructionBusinessError("完成上传时必须提交全部分片及其ETag")

    return normalized_parts


def _validate_part_numbers(cls, part_numbers: list[int], total_parts: int) -> list[int]:
    normalized_part_numbers = sorted({int(part_number) for part_number in part_numbers})
    if not normalized_part_numbers:
        raise ReconstructionBusinessError("part_numbers不能为空")
    for part_number in normalized_part_numbers:
        if part_number < 1 or part_number > total_parts:
            raise ReconstructionBusinessError(f"分片编号超出范围: {part_number}")
    return normalized_part_numbers


def _expected_local_part_size(cls, upload_session, part_number: int) -> int:
    total_parts = int(upload_session.total_parts)
    part_size = int(upload_session.part_size)
    file_size = int(upload_session.file_size)

    if part_number < 1 or part_number > total_parts:
        raise ReconstructionBusinessError(f"分片编号超出范围: {part_number}")

    if part_number < total_parts:
        return part_size

    final_part_size = file_size - part_size * (total_parts - 1)
    if final_part_size <= 0:
        raise ReconstructionBusinessError("上传会话分片配置异常")
    return final_part_size


def _build_upload_session_payload(
    cls, upload_session, upload_urls: list[dict] | None = None
) -> dict:
    payload = {
        "upload_session_id": upload_session.id,
        "item_id": upload_session.item_id,
        "upload_id": upload_session.upload_id,
        "bucket": upload_session.bucket,
        "object_name": upload_session.object_name,
        "video_path": cls._public_asset_url(upload_session.video_path),
        "part_size": upload_session.part_size,
        "total_parts": upload_session.total_parts,
    }
    if upload_urls is not None:
        payload["upload_urls"] = upload_urls
    return payload


def _build_local_upload_init_payload(cls, upload_session) -> dict:
    return cls._build_upload_session_payload(upload_session, upload_urls=[])


async def _create_multipart_upload(
    cls, bucket: str, object_name: str, content_type: str
) -> str:
    ensure_minio_bucket, _, minio_instance, _, _ = _get_minio_helpers()

    def _create() -> str:
        ensure_minio_bucket(bucket)
        return minio_instance.client._create_multipart_upload(
            bucket_name=bucket,
            object_name=object_name,
            headers={"Content-Type": content_type or "application/octet-stream"},
        )

    return await run_sync(_create)


async def _generate_multipart_upload_urls(
    cls,
    bucket: str,
    object_name: str,
    upload_id: str,
    part_numbers: list[int],
) -> list[dict]:
    _, _, minio_instance, _, _ = _get_minio_helpers()

    def _generate() -> list[dict]:
        upload_urls = []
        for part_number in part_numbers:
            url = minio_instance.client.get_presigned_url(
                "PUT",
                bucket,
                object_name,
                expires=timedelta(days=7),
                extra_query_params={
                    "uploadId": upload_id,
                    "partNumber": str(part_number),
                },
            )
            upload_urls.append(
                {
                    "part_number": part_number,
                    "url": cls._strip_presigned_url_host(url),
                    "expires_at": cls._multipart_upload_expires_at(),
                }
            )
        return upload_urls

    return await run_sync(_generate)


async def _list_multipart_uploaded_parts(
    cls, bucket: str, object_name: str, upload_id: str
) -> list[dict]:
    _, _, minio_instance, _, _ = _get_minio_helpers()

    def _list_parts() -> list[dict]:
        uploaded_parts = []
        marker = None

        while True:
            result = minio_instance.client._list_parts(
                bucket_name=bucket,
                object_name=object_name,
                upload_id=upload_id,
                part_number_marker=marker,
            )
            uploaded_parts.extend(
                {
                    "part_number": part.part_number,
                    "size": part.size,
                    "etag": part.etag,
                }
                for part in result.parts
            )
            if not result.is_truncated:
                break
            marker = result.next_part_number_marker

        return uploaded_parts

    return await run_sync(_list_parts)


async def _complete_multipart_upload(
    cls,
    bucket: str,
    object_name: str,
    upload_id: str,
    parts: list[dict],
    total_parts: int,
) -> None:
    _, _, minio_instance, _, _ = _get_minio_helpers()
    normalized_parts = cls._normalize_complete_parts(parts, total_parts)

    def _complete() -> None:
        minio_instance.client._complete_multipart_upload(
            bucket_name=bucket,
            object_name=object_name,
            upload_id=upload_id,
            parts=normalized_parts,
        )

    await run_sync(_complete)


async def _abort_multipart_upload(
    cls, bucket: str, object_name: str, upload_id: str
) -> None:
    _, _, minio_instance, _, S3Error = _get_minio_helpers()

    def _abort() -> None:
        try:
            minio_instance.client._abort_multipart_upload(
                bucket_name=bucket,
                object_name=object_name,
                upload_id=upload_id,
            )
        except S3Error as exc:
            if exc.code in {"NoSuchUpload", "NoSuchKey", "NoSuchBucket"}:
                return
            raise

    await run_sync(_abort)


async def _require_upload_session(cls, upload_session_id: int):
    async with SessionLocal() as session:
        upload_session = await ReconstructionVideoUploadSession.get_by_id(
            session, upload_session_id
        )

    if upload_session is None:
        raise ReconstructionBusinessError(
            f"上传会话不存在: upload_session_id={upload_session_id}"
        )
    if upload_session.status != "initiated":
        raise ReconstructionBusinessError(
            f"上传会话不可继续操作: upload_session_id={upload_session_id}"
        )

    return upload_session


def _format_source_video_item(cls, item: ItemsType, message: str | None = None) -> dict:
    return {
        "item_id": item.id,
        "item_name": item.item_name,
        "item_code": item.item_code,
        "height": item.height,
        "length": item.long,
        "width": item.width,
        "weight": item.weight,
        "video_path": cls._public_asset_url(item.source_video_path),
        "filename": item.source_video_filename,
        "size": item.source_video_size,
        "content_type": item.source_video_content_type,
        "source_video_updated_at": item.source_video_updated_at.isoformat()
        if item.source_video_updated_at
        else None,
        "message": message,
    }


async def _upload_multipart_part_bytes(
    cls,
    bucket: str,
    object_name: str,
    upload_id: str,
    part_number: int,
    data: bytes,
) -> str:
    _, _, minio_instance, _, _ = _get_minio_helpers()

    def _upload() -> str:
        etag = minio_instance.client._upload_part(
            bucket_name=bucket,
            object_name=object_name,
            data=data,
            headers=None,
            upload_id=upload_id,
            part_number=part_number,
        )
        return str(etag).strip().strip('"')

    return await run_sync(_upload)


async def _upload_part(
    cls,
    bucket: str,
    object_name: str,
    upload_id: str,
    part_number: int,
    data: bytes,
) -> str:
    return await cls._upload_multipart_part_bytes(
        bucket=bucket,
        object_name=object_name,
        upload_id=upload_id,
        part_number=part_number,
        data=data,
    )


async def _init_remote_source_video_upload(
    cls,
    item_id: int,
    file_name: str,
    file_size: int,
    content_type: str,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
) -> dict:
    return await upload_service._init_remote_source_video_upload(
        cls,
        item_id=item_id,
        file_name=file_name,
        file_size=file_size,
        content_type=content_type,
        height=height,
        length=length,
        width=width,
        weight=weight,
        runtime=_runtime_context(),
    )


async def _init_local_source_video_upload(
    cls,
    item_id: int,
    file_name: str,
    file_size: int,
    content_type: str,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
) -> dict:
    return await upload_service._init_local_source_video_upload(
        cls,
        item_id=item_id,
        file_name=file_name,
        file_size=file_size,
        content_type=content_type,
        height=height,
        length=length,
        width=width,
        weight=weight,
        runtime=_runtime_context(),
    )


async def _upload_source_video_file(cls, item_id: int, file) -> dict:
    return await source_video_service._upload_source_video_file(
        cls,
        item_id=item_id,
        file=file,
        runtime=_runtime_context(),
    )


async def upload_source_video(
    cls,
    item_id: int,
    file,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
) -> dict:
    return await source_video_service.upload_source_video(
        cls,
        item_id=item_id,
        file=file,
        height=height,
        length=length,
        width=width,
        weight=weight,
        runtime=_runtime_context(),
    )


async def upload_source_video_local_part(
    cls,
    upload_session_id: int,
    part_number: int,
    file,
) -> dict:
    return await upload_service.upload_source_video_local_part(
        cls,
        upload_session_id=upload_session_id,
        part_number=part_number,
        file=file,
        runtime=_runtime_context(),
    )


async def upload_source_video_remote_part(
    cls,
    upload_session_id: int,
    part_number: int,
    file,
) -> dict:
    return await upload_service.upload_source_video_remote_part(
        cls,
        upload_session_id=upload_session_id,
        part_number=part_number,
        file=file,
        runtime=_runtime_context(),
    )


async def upload_source_video_part(
    cls,
    upload_session_id: int,
    part_number: int,
    file,
) -> dict:
    return await upload_service.upload_source_video_part(
        cls,
        upload_session_id=upload_session_id,
        part_number=part_number,
        file=file,
        runtime=_runtime_context(),
    )


async def init_source_video_multipart_upload(
    cls,
    item_id: int,
    file_name: str,
    file_size: int,
    content_type: str,
    storage_mode: str = "remote",
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
) -> dict:
    return await upload_service.init_source_video_multipart_upload(
        cls,
        item_id=item_id,
        file_name=file_name,
        file_size=file_size,
        content_type=content_type,
        storage_mode=storage_mode,
        height=height,
        length=length,
        width=width,
        weight=weight,
        runtime=_runtime_context(),
    )


async def get_source_video_upload_progress(cls, upload_session_id: int) -> dict:
    return await upload_service.get_source_video_upload_progress(
        cls,
        upload_session_id=upload_session_id,
        runtime=_runtime_context(),
    )


async def get_source_video_upload_urls(
    cls, upload_session_id: int, part_numbers: list[int]
) -> dict:
    return await upload_service.get_source_video_upload_urls(
        cls,
        upload_session_id=upload_session_id,
        part_numbers=part_numbers,
        runtime=_runtime_context(),
    )


async def complete_source_video_multipart_upload(cls, upload_session_id: int) -> dict:
    return await upload_service.complete_source_video_multipart_upload(
        cls,
        upload_session_id=upload_session_id,
        runtime=_runtime_context(),
    )


async def abort_source_video_multipart_upload(cls, upload_session_id: int) -> dict:
    return await upload_service.abort_source_video_multipart_upload(
        cls,
        upload_session_id=upload_session_id,
        runtime=_runtime_context(),
    )


async def _complete_local_source_video_upload(cls, upload_session) -> dict:
    return await upload_service._complete_local_source_video_upload(
        cls,
        upload_session=upload_session,
        runtime=_runtime_context(),
    )


async def _abort_local_source_video_upload(cls, upload_session) -> dict:
    return await upload_service._abort_local_source_video_upload(
        cls,
        upload_session=upload_session,
        runtime=_runtime_context(),
    )


async def _minio_health_check(cls) -> bool:
    return await upload_service._minio_health_check(
        cls,
        runtime=_runtime_context(),
    )


async def _sync_local_session_to_remote(cls, upload_session, session) -> bool:
    return await upload_service._sync_local_session_to_remote(
        cls,
        upload_session=upload_session,
        session=session,
        runtime=_runtime_context(),
    )


async def check_minio_and_sync_local_uploads(cls) -> dict:
    return await upload_service.check_minio_and_sync_local_uploads(
        cls,
        runtime=_runtime_context(),
    )


async def list_source_videos(cls, page: int = 1, page_size: int = 100) -> dict:
    return await source_video_service.list_source_videos(
        cls,
        page=page,
        page_size=page_size,
        runtime=_runtime_context(),
    )


async def get_source_video(cls, item_id: int) -> dict:
    return await source_video_service.get_source_video(
        cls,
        item_id=item_id,
        runtime=_runtime_context(),
    )


async def update_source_video(
    cls,
    item_id: int,
    file=None,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
) -> dict:
    return await source_video_service.update_source_video(
        cls,
        item_id=item_id,
        file=file,
        height=height,
        length=length,
        width=width,
        weight=weight,
        runtime=_runtime_context(),
    )


async def delete_source_video(cls, item_id: int) -> dict:
    return await source_video_service.delete_source_video(
        cls,
        item_id=item_id,
        runtime=_runtime_context(),
    )
