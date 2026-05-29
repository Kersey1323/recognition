"""Reconstruction source-video upload, multipart, and sync service implementations."""
from __future__ import annotations

import math
import os
import re
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4


def bind_runtime_dependencies() -> None:
    from csrcqsf.modules.railway_parts.services import reconstruction_service

    globals().update(
        {
            "datetime": reconstruction_service.datetime,
            "timedelta": reconstruction_service.timedelta,
            "math": reconstruction_service.math,
            "os": reconstruction_service.os,
            "re": reconstruction_service.re,
            "urlsplit": reconstruction_service.urlsplit,
            "urlunsplit": reconstruction_service.urlunsplit,
            "Path": reconstruction_service.Path,
            "uuid4": reconstruction_service.uuid4,
            "run_sync": reconstruction_service.run_sync,
            "get_id": reconstruction_service.get_id,
            "logger": reconstruction_service.logger,
            "Part": reconstruction_service.Part,
            "SessionLocal": reconstruction_service.SessionLocal,
            "Items": reconstruction_service.Items,
            "ReconstructionVideoUploadSession": reconstruction_service.ReconstructionVideoUploadSession,
            "ReconstructionBusinessError": reconstruction_service.ReconstructionBusinessError,
            "minio_env_configured": reconstruction_service.minio_env_configured,
            "minio_reconstruction_video_bucket": reconstruction_service.minio_reconstruction_video_bucket,
            "_get_minio_helpers": reconstruction_service._get_minio_helpers,
        }
    )


def _safe_filename(filename: str | None) -> str:
    raw_name = Path(filename or "source_video.mp4").name
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    return safe_name or "source_video.mp4"

def _choose_multipart_part_size(file_size: int) -> int:
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

def _normalize_complete_parts(cls, parts: list[dict], total_parts: int) -> list[Part]:
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

def _build_upload_session_payload(cls, upload_session, upload_urls: list[dict] | None = None) -> dict:
    payload = {
        "upload_session_id": upload_session.id,
        "item_id": upload_session.item_id,
        "upload_id": upload_session.upload_id,
        "bucket": upload_session.bucket,
        "object_name": upload_session.object_name,
        "video_path": upload_session.video_path,
        "part_size": upload_session.part_size,
        "total_parts": upload_session.total_parts,
    }
    if upload_urls is not None:
        payload["upload_urls"] = upload_urls
    return payload

def _build_local_upload_init_payload(cls, upload_session) -> dict:
    return cls._build_upload_session_payload(upload_session, upload_urls=[])

async def _create_multipart_upload(cls, bucket: str, object_name: str, content_type: str) -> str:
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

async def _list_multipart_uploaded_parts(cls, bucket: str, object_name: str, upload_id: str) -> list[dict]:
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

async def _abort_multipart_upload(cls, bucket: str, object_name: str, upload_id: str) -> None:
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
        upload_session = await ReconstructionVideoUploadSession.get_by_id(session, upload_session_id)

    if upload_session is None:
        raise ReconstructionBusinessError(f"上传会话不存在: upload_session_id={upload_session_id}")
    if upload_session.status != "initiated":
        raise ReconstructionBusinessError(f"上传会话不可继续操作: upload_session_id={upload_session_id}")

    return upload_session

def _format_source_video_item(cls, item: Items, message: str | None = None) -> dict:
    return {
        "item_id": item.id,
        "item_name": item.item_name,
        "item_code": item.item_code,
        "height": item.height,
        "length": item.long,
        "width": item.width,
        "weight": item.weight,
        "video_path": item.source_video_path,
        "filename": item.source_video_filename,
        "size": item.source_video_size,
        "content_type": item.source_video_content_type,
        "source_video_updated_at": item.source_video_updated_at.isoformat() if item.source_video_updated_at else None,
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
    object_name = cls._build_source_video_multipart_object_name(item_id=item_id, file_name=file_name)
    video_path = f"{minio_reconstruction_video_bucket}/{object_name}"
    safe_name = cls._safe_filename(file_name)
    part_size = cls._choose_multipart_part_size(file_size)
    total_parts = max(1, math.ceil(file_size / part_size))

    async with SessionLocal() as session:
        active_session = await ReconstructionVideoUploadSession.get_active_by_item_id(session, item_id)
        if active_session is not None:
            raise ReconstructionBusinessError(
                f"该配件已存在未完成的上传会话: upload_session_id={active_session.id}"
            )

        upload_id = await cls._create_multipart_upload(
            bucket=minio_reconstruction_video_bucket,
            object_name=object_name,
            content_type=content_type,
        )

        try:
            upload_session = await ReconstructionVideoUploadSession.create_session(
                session,
                ReconstructionVideoUploadSession(
                    item_id=item_id,
                    bucket=minio_reconstruction_video_bucket,
                    object_name=object_name,
                    video_path=video_path,
                    upload_id=upload_id,
                    file_name=safe_name,
                    file_size=file_size,
                    content_type=content_type or "application/octet-stream",
                    part_size=part_size,
                    total_parts=total_parts,
                    height=height,
                    length=length,
                    width=width,
                    weight=weight,
                    status="initiated",
                    storage_mode="remote",
                    local_status="initiated",
                    remote_status="pending",
                    expires_at=datetime.utcnow() + timedelta(days=7),
                ),
            )
            upload_urls = await cls._generate_multipart_upload_urls(
                bucket=minio_reconstruction_video_bucket,
                object_name=object_name,
                upload_id=upload_id,
                part_numbers=list(range(1, total_parts + 1)),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await cls._abort_multipart_upload(
                bucket=minio_reconstruction_video_bucket,
                object_name=object_name,
                upload_id=upload_id,
            )
            raise

    return cls._build_upload_session_payload(upload_session, upload_urls=upload_urls)

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
    object_name = cls._build_source_video_multipart_object_name(item_id=item_id, file_name=file_name)
    video_path = f"{minio_reconstruction_video_bucket}/{object_name}"
    safe_name = cls._safe_filename(file_name)
    part_size = cls._choose_multipart_part_size(file_size)
    total_parts = max(1, math.ceil(file_size / part_size))
    storage = cls._get_local_upload_storage()

    async with SessionLocal() as session:
        active_session = await ReconstructionVideoUploadSession.get_active_by_item_id(session, item_id)
        if active_session is not None:
            raise ReconstructionBusinessError(
                f"该配件已存在未完成的上传会话: upload_session_id={active_session.id}"
            )

        upload_session = await ReconstructionVideoUploadSession.create_session(
            session,
            ReconstructionVideoUploadSession(
                item_id=item_id,
                bucket=minio_reconstruction_video_bucket,
                object_name=object_name,
                video_path=video_path,
                upload_id=str(get_id()),
                file_name=safe_name,
                file_size=file_size,
                content_type=content_type or "application/octet-stream",
                part_size=part_size,
                total_parts=total_parts,
                height=height,
                length=length,
                width=width,
                weight=weight,
                status="initiated",
                storage_mode="local",
                local_status="initiated",
                remote_status="pending",
                remote_object_name=object_name,
                remote_video_path=video_path,
                expires_at=datetime.utcnow() + timedelta(days=7),
            ),
        )

        session_dir = storage.ensure_session_dirs(upload_session.id)
        storage.save_meta(
            session_dir,
            {
                "upload_session_id": upload_session.id,
                "file_name": safe_name,
                "file_size": file_size,
                "part_size": part_size,
                "total_parts": total_parts,
                "uploaded_parts": [],
                "storage_mode": "local",
                "local_status": "initiated",
                "remote_status": "pending",
                "last_sync_error": None,
            },
        )
        upload_session.local_dir = str(session_dir)
        await session.flush()
        await session.commit()

    return cls._build_local_upload_init_payload(upload_session)

async def _upload_source_video_file(cls, item_id: int, file) -> dict:
    ensure_minio_bucket, _, minio_instance, _, _ = _get_minio_helpers()
    ensure_minio_bucket(minio_reconstruction_video_bucket)
    safe_name = cls._safe_filename(file.filename)
    date_dir = datetime.now().strftime("%Y%m%d")
    object_name = f"raw-videos/{item_id}/{date_dir}/{get_id()}_{safe_name}"
    content_type = file.content_type or "application/octet-stream"

    def _upload() -> int:
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)
        minio_instance.client.put_object(
            minio_reconstruction_video_bucket,
            object_name,
            file.file,
            length=size,
            content_type=content_type,
        )
        return size

    size = await run_sync(_upload)
    await file.close()
    return {
        "video_path": f"{minio_reconstruction_video_bucket}/{object_name}",
        "filename": safe_name,
        "size": size,
        "content_type": content_type,
    }

async def upload_source_video(
    cls,
    item_id: int,
    file,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
) -> dict:
    """
    上传三维重构原始视频到独立 MinIO bucket。

    返回当前配件绑定的原始视频资产信息。
    """
    item = await cls._require_item_exists(item_id)
    if item.source_video_path:
        raise ReconstructionBusinessError(f"配件已存在原始视频，请使用更新接口替换: item_id={item_id}")

    uploaded = await cls._upload_source_video_file(item_id, file)
    async with SessionLocal() as session:
        try:
            await Items.update_source_video(
                session=session,
                item_id=item_id,
                video_path=uploaded["video_path"],
                filename=uploaded["filename"],
                size=uploaded["size"],
                content_type=uploaded["content_type"],
                height=height,
                length=length,
                width=width,
                weight=weight,
                updated_at=datetime.now(),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await cls._delete_minio_object(uploaded["video_path"])
            raise

        item = await Items.get_item_by_id(session, item_id)

    return cls._format_source_video_item(item, message="原始视频上传成功")

async def upload_source_video_local_part(
    cls,
    upload_session_id: int,
    part_number: int,
    file,
) -> dict:
    upload_session = await cls._require_upload_session(upload_session_id)
    if upload_session.storage_mode != "local":
        raise ReconstructionBusinessError("当前上传会话不是本地分片模式")
    if part_number < 1 or part_number > int(upload_session.total_parts):
        raise ReconstructionBusinessError(f"分片编号超出范围: {part_number}")

    data = await file.read()
    await file.close()
    if not data:
        raise ReconstructionBusinessError("上传分片内容不能为空")
    expected_part_size = cls._expected_local_part_size(upload_session, part_number)
    if len(data) != expected_part_size:
        logger.warning(
            "本地上传分片大小与预期不一致: upload_session_id=%s, part_number=%s, expected=%s, actual=%s",
            upload_session_id,
            part_number,
            expected_part_size,
            len(data),
        )

    storage = cls._get_local_upload_storage()
    session_dir = Path(upload_session.local_dir) if upload_session.local_dir else storage.ensure_session_dirs(upload_session.id)
    storage.ensure_session_dirs(upload_session.id)
    storage.write_part(session_dir, part_number, data)

    async with SessionLocal() as session:
        await ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            local_status="uploading",
            local_dir=str(session_dir),
        )
        await session.commit()

    return {
        "upload_session_id": upload_session.id,
        "part_number": part_number,
        "size": len(data),
        "message": "分片上传成功",
    }

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
    item = await cls._require_item_exists(item_id)
    if item.source_video_path:
        raise ReconstructionBusinessError(f"配件已存在原始视频，请使用更新接口替换: item_id={item_id}")
    normalized_storage_mode = (storage_mode or "remote").strip().lower()
    if normalized_storage_mode == "local":
        return await cls._init_local_source_video_upload(
            item_id=item_id,
            file_name=file_name,
            file_size=file_size,
            content_type=content_type,
            height=height,
            length=length,
            width=width,
            weight=weight,
        )
    return await cls._init_remote_source_video_upload(
        item_id=item_id,
        file_name=file_name,
        file_size=file_size,
        content_type=content_type,
        height=height,
        length=length,
        width=width,
        weight=weight,
    )

async def get_source_video_upload_progress(cls, upload_session_id: int) -> dict:
    upload_session = await cls._require_upload_session(upload_session_id)
    if upload_session.storage_mode == "local":
        storage = cls._get_local_upload_storage()
        session_dir = Path(upload_session.local_dir) if upload_session.local_dir else storage.get_session_dir(upload_session.id)
        if not session_dir.exists():
            raise ReconstructionBusinessError(f"本地上传会话目录不存在: upload_session_id={upload_session.id}")
        meta = storage.load_meta(session_dir)
        uploaded_parts = []
        for part_number in meta.get("uploaded_parts", []):
            part_path = session_dir / "parts" / f"part-{int(part_number):05d}"
            uploaded_parts.append(
                {
                    "part_number": int(part_number),
                    "size": part_path.stat().st_size if part_path.exists() else None,
                    "etag": "",
                }
            )
        payload = cls._build_upload_session_payload(upload_session)
        payload["uploaded_parts"] = uploaded_parts
        return payload

    uploaded_parts = await cls._list_multipart_uploaded_parts(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
    )
    payload = cls._build_upload_session_payload(upload_session)
    payload["uploaded_parts"] = uploaded_parts
    return payload

async def get_source_video_upload_urls(cls, upload_session_id: int, part_numbers: list[int]) -> dict:
    upload_session = await cls._require_upload_session(upload_session_id)
    normalized_part_numbers = cls._validate_part_numbers(part_numbers, upload_session.total_parts)
    if upload_session.storage_mode == "local":
        return {
            "upload_session_id": upload_session.id,
            "upload_urls": [
                {
                    "part_number": part_number,
                    "url": "/railway/parts/v2/reconstruct/video/upload/part",
                    "expires_at": None,
                }
                for part_number in normalized_part_numbers
            ],
        }
    upload_urls = await cls._generate_multipart_upload_urls(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
        part_numbers=normalized_part_numbers,
    )
    return {
        "upload_session_id": upload_session.id,
        "upload_urls": upload_urls,
    }

async def complete_source_video_multipart_upload(cls, upload_session_id: int) -> dict:
    upload_session = await cls._require_upload_session(upload_session_id)
    if upload_session.storage_mode == "local":
        return await cls._complete_local_source_video_upload(upload_session)

    uploaded_parts = await cls._list_multipart_uploaded_parts(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
    )
    await cls._complete_multipart_upload(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
        parts=uploaded_parts,
        total_parts=upload_session.total_parts,
    )

    async with SessionLocal() as session:
        try:
            current_session = await ReconstructionVideoUploadSession.get_by_id(session, upload_session_id)
            if current_session is None:
                raise ReconstructionBusinessError(f"上传会话不存在: upload_session_id={upload_session_id}")

            now = datetime.now()
            await Items.update_source_video(
                session=session,
                item_id=current_session.item_id,
                video_path=current_session.video_path,
                filename=current_session.file_name,
                size=current_session.file_size,
                content_type=current_session.content_type,
                height=current_session.height,
                length=current_session.length,
                width=current_session.width,
                weight=current_session.weight,
                updated_at=now,
            )
            await ReconstructionVideoUploadSession.mark_completed(
                session=session,
                session_id=current_session.id,
                completed_at=now,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await cls._delete_minio_object(upload_session.video_path)
            raise

        item = await Items.get_item_by_id(session, upload_session.item_id)

    return cls._format_source_video_item(item, message="原始视频上传成功")

async def abort_source_video_multipart_upload(cls, upload_session_id: int) -> dict:
    upload_session = await cls._require_upload_session(upload_session_id)
    if upload_session.storage_mode == "local":
        return await cls._abort_local_source_video_upload(upload_session)

    await cls._abort_multipart_upload(
        bucket=upload_session.bucket,
        object_name=upload_session.object_name,
        upload_id=upload_session.upload_id,
    )

    async with SessionLocal() as session:
        await ReconstructionVideoUploadSession.mark_aborted(session, upload_session_id)
        await session.commit()

    return {
        "item_id": upload_session.item_id,
        "message": "原始视频分片上传已取消",
    }

async def _complete_local_source_video_upload(cls, upload_session) -> dict:
    storage = cls._get_local_upload_storage()
    session_dir = Path(upload_session.local_dir) if upload_session.local_dir else storage.get_session_dir(upload_session.id)
    if not session_dir.exists():
        raise ReconstructionBusinessError(f"本地上传会话目录不存在: upload_session_id={upload_session.id}")

    meta = storage.load_meta(session_dir)
    uploaded_parts = {int(part_number) for part_number in meta.get("uploaded_parts", [])}
    expected_parts = set(range(1, int(upload_session.total_parts) + 1))
    missing_parts = sorted(expected_parts - uploaded_parts)
    if missing_parts:
        raise ReconstructionBusinessError(f"仍有分片未上传: {missing_parts}")

    merged_path = storage.merge_parts(
        session_dir=session_dir,
        total_parts=int(upload_session.total_parts),
        output_file_name=upload_session.file_name,
    )
    meta["local_status"] = "completed"
    meta["remote_status"] = "pending"
    storage.save_meta(session_dir, meta)

    async with SessionLocal() as session:
        await ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            status="completed",
            local_status="completed",
            remote_status="pending",
            merged_file_path=str(merged_path),
            local_dir=str(session_dir),
            completed_at=datetime.now(),
        )
        await session.commit()
        item = await Items.get_item_by_id(session, upload_session.item_id)

    return cls._format_source_video_item(item, message="本地分片合并完成，等待 MinIO 同步")

async def _abort_local_source_video_upload(cls, upload_session) -> dict:
    storage = cls._get_local_upload_storage()
    session_dir = Path(upload_session.local_dir) if upload_session.local_dir else storage.get_session_dir(upload_session.id)
    storage.delete_session(session_dir)

    async with SessionLocal() as session:
        await ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            status="aborted",
            local_status="aborted",
        )
        await session.commit()

    return {
        "item_id": upload_session.item_id,
        "message": "本地分片上传已取消",
    }

async def _minio_health_check(cls) -> bool:
    ensure_minio_bucket, _, _, _, _ = _get_minio_helpers()

    def _check() -> bool:
        ensure_minio_bucket(minio_reconstruction_video_bucket)
        return True

    try:
        return await run_sync(_check)
    except Exception:
        return False

async def _sync_local_session_to_remote(cls, upload_session, session) -> bool:
    merged_file_path = getattr(upload_session, "merged_file_path", None)
    if not merged_file_path or not Path(merged_file_path).exists():
        await ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            remote_status="failed",
            last_sync_error="merged file missing",
            sync_attempts=int(getattr(upload_session, "sync_attempts", 0) or 0) + 1,
        )
        return False

    remote_object_name = getattr(upload_session, "remote_object_name", None) or upload_session.object_name
    remote_video_path = getattr(upload_session, "remote_video_path", None) or upload_session.video_path
    remote_upload_id = getattr(upload_session, "remote_upload_id", None)
    if not remote_upload_id:
        remote_upload_id = await cls._create_multipart_upload(
            bucket=upload_session.bucket,
            object_name=remote_object_name,
            content_type=upload_session.content_type or "application/octet-stream",
        )
        await ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            remote_status="syncing",
            remote_upload_id=remote_upload_id,
        )

    try:
        reader = LocalFilePartReader(merged_file_path, int(upload_session.part_size))
        uploaded_parts = await cls._list_multipart_uploaded_parts(
            bucket=upload_session.bucket,
            object_name=remote_object_name,
            upload_id=remote_upload_id,
        )
        uploaded_part_numbers = {int(part["part_number"]) for part in uploaded_parts}
        part_etags = {int(part["part_number"]): str(part["etag"]).strip().strip('"') for part in uploaded_parts}

        for part in reader.list_parts():
            if part.part_number in uploaded_part_numbers:
                continue
            etag = await cls._upload_multipart_part_bytes(
                bucket=upload_session.bucket,
                object_name=remote_object_name,
                upload_id=remote_upload_id,
                part_number=part.part_number,
                data=reader.read_part(part),
            )
            part_etags[part.part_number] = etag

        await cls._complete_multipart_upload(
            bucket=upload_session.bucket,
            object_name=remote_object_name,
            upload_id=remote_upload_id,
            parts=[
                {"part_number": part_number, "etag": etag}
                for part_number, etag in sorted(part_etags.items())
            ],
            total_parts=int(upload_session.total_parts),
        )

        now = datetime.now()
        await Items.update_source_video(
            session=session,
            item_id=upload_session.item_id,
            video_path=remote_video_path,
            filename=upload_session.file_name,
            size=upload_session.file_size,
            content_type=upload_session.content_type,
            height=upload_session.height,
            length=upload_session.length,
            width=upload_session.width,
            weight=upload_session.weight,
            updated_at=now,
        )
        await ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            remote_status="completed",
            remote_upload_id=remote_upload_id,
            remote_object_name=remote_object_name,
            remote_video_path=remote_video_path,
            synced_at=now,
            last_sync_error=None,
        )
        return True
    except Exception as exc:
        await ReconstructionVideoUploadSession.update_sync_state(
            session,
            upload_session.id,
            remote_status="failed",
            remote_upload_id=remote_upload_id,
            last_sync_error=str(exc),
            sync_attempts=int(getattr(upload_session, "sync_attempts", 0) or 0) + 1,
        )
        return False

async def check_minio_and_sync_local_uploads(cls) -> dict:
    if not minio_env_configured():
        return {
            "available": False,
            "message": "未显式配置 MinIO 环境变量",
            "total_pending": 0,
            "synced_count": 0,
            "failed_count": 0,
        }

    if not await cls._minio_health_check():
        return {
            "available": False,
            "message": "MinIO 不可用",
            "total_pending": 0,
            "synced_count": 0,
            "failed_count": 0,
        }

    synced_count = 0
    failed_count = 0
    async with SessionLocal() as session:
        pending_sessions = await ReconstructionVideoUploadSession.list_local_sessions_pending_remote_sync(session)
        for upload_session in pending_sessions:
            ok = await cls._sync_local_session_to_remote(upload_session, session)
            if ok:
                synced_count += 1
            else:
                failed_count += 1
        await session.commit()

    return {
        "available": True,
        "message": "MinIO 可用，同步完成",
        "total_pending": synced_count + failed_count,
        "synced_count": synced_count,
        "failed_count": failed_count,
    }

async def list_source_videos(cls, page: int = 1, page_size: int = 100) -> dict:
    limit, offset = cls._page_to_limit_offset(page=page, page_size=page_size)
    async with SessionLocal() as session:
        records, total = await Items.list_source_videos(
            session=session,
            limit=limit,
            offset=offset,
        )
        return {
            "total": total,
            "page": page,
            "pageSize": page_size,
            "records": [cls._format_source_video_item(item) for item in records],
        }

async def get_source_video(cls, item_id: int) -> dict:
    item = await cls._require_item_exists(item_id)
    if not item.source_video_path:
        raise ReconstructionBusinessError(f"配件未绑定原始视频: item_id={item_id}")
    return cls._format_source_video_item(item, message="原始视频查询成功")

async def update_source_video(
    cls,
    item_id: int,
    file=None,
    height: float | None = None,
    length: float | None = None,
    width: float | None = None,
    weight: float | None = None,
) -> dict:
    item = await cls._require_item_exists(item_id)
    old_video_path = item.source_video_path
    if not old_video_path and file is None:
        raise ReconstructionBusinessError(f"配件未绑定原始视频: item_id={item_id}")

    uploaded = None
    if file is not None:
        uploaded = await cls._upload_source_video_file(item_id, file)

    async with SessionLocal() as session:
        try:
            if uploaded is not None:
                await Items.update_source_video(
                    session=session,
                    item_id=item_id,
                    video_path=uploaded["video_path"],
                    filename=uploaded["filename"],
                    size=uploaded["size"],
                    content_type=uploaded["content_type"],
                    height=height,
                    length=length,
                    width=width,
                    weight=weight,
                    updated_at=datetime.now(),
                )
            else:
                await Items.update_measurements(
                    session=session,
                    item_id=item_id,
                    height=height,
                    length=length,
                    width=width,
                    weight=weight,
                )
            await session.commit()
        except Exception:
            await session.rollback()
            if uploaded is not None:
                await cls._delete_minio_object(uploaded["video_path"])
            raise

        item = await Items.get_item_by_id(session, item_id)

    if uploaded is not None and old_video_path:
        try:
            await cls._delete_minio_object(old_video_path)
        except Exception as exc:
            logger.error(f"旧原始视频删除失败: item_id={item_id}, path={old_video_path}, err={exc}")

    return cls._format_source_video_item(item, message="原始视频更新成功")

async def delete_source_video(cls, item_id: int) -> dict:
    item = await cls._require_item_exists(item_id)
    old_video_path = item.source_video_path
    if not old_video_path:
        raise ReconstructionBusinessError(f"配件未绑定原始视频: item_id={item_id}")

    deleted = await cls._delete_minio_object(old_video_path)
    async with SessionLocal() as session:
        await Items.clear_source_video(session=session, item_id=item_id)
        await session.commit()

    message = "原始视频删除成功" if deleted else "原始视频对象不存在，元数据已清理"
    return {
        "item_id": item_id,
        "message": message,
    }
