"""
三维重构管理器 - 业务逻辑层
主业务只负责重构任务元数据管理，并通过远端 reconstruction_server 执行任务
"""
import math
import os
import re
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from anyio.to_thread import run_sync
from bfrcommon.snowflake import get_id
from globals_vars import logger
from minio.datatypes import Part
from csrcqsf.data.pg import SessionLocal
from csrcqsf.biz.railwayparts.reconstruction_client import (
    ReconstructionServiceClient,
    ReconstructionServiceClientError,
)
from csrcqsf.biz.railwayparts.local_upload_storage import LocalUploadStorage
from csrcqsf.models.reconstruction import ReconstructionRecord, ReconstructionStatus
from csrcqsf.models.item import Items
from csrcqsf.models.reconstruction_upload import ReconstructionVideoUploadSession
from csrcqsf.biz.railwayparts.local_file_part_reader import LocalFilePartReader
from csrcqsf.settings import (
    minio_env_configured,
    minio_reconstruction_file_bucket,
    minio_reconstruction_video_bucket,
    reconstruction_server_env_configured,
    sam3_model_path,
)


def _get_minio_helpers():
    from csrcqsf.data.minio import (
        ensure_minio_bucket,
        looks_like_minio_path,
        minio_instance,
        parse_minio_path,
    )
    from minio.error import S3Error

    return ensure_minio_bucket, looks_like_minio_path, minio_instance, parse_minio_path, S3Error


class ReconstructionBusinessError(Exception):
    """三维重构相关业务异常，统一交给响应中间件包装为 200/fail。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


def map_celery_state_to_reconstruction_status(state: str) -> str:
    """把 Celery 状态统一映射到对外暴露的业务状态。"""
    status_map = {
        "PENDING": ReconstructionStatus.PENDING,
        "STARTED": ReconstructionStatus.TRAINING,
        "PROGRESS": ReconstructionStatus.TRAINING,
        "SUCCESS": ReconstructionStatus.SUCCESS,
        "FAILURE": ReconstructionStatus.FAILED,
        "REVOKED": ReconstructionStatus.CANCELLED,
    }
    return status_map.get(state, state)


def get_reconstruction_task_failure_message(task_result) -> str | None:
    """识别 Celery 成功返回中的业务失败结果。"""
    if not isinstance(task_result, dict):
        return None

    status = str(task_result.get("status") or "").strip().lower()
    if status != ReconstructionStatus.FAILED.value:
        return None

    error = task_result.get("error") or task_result.get("message")
    return str(error) if error else "重建任务失败"


def _normalize_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    return None


class ReconstructionManager:
    """三维重构管理器"""

    @classmethod
    def _get_reconstruction_client(cls) -> ReconstructionServiceClient:
        return ReconstructionServiceClient()

    @classmethod
    def _get_local_upload_storage(cls) -> LocalUploadStorage:
        state_dir = Path(
            os.getenv(
                "STATE_DIR",
                str(Path(__file__).resolve().parents[3] / "state"),
            )
        )
        return LocalUploadStorage(state_dir / "reconstruction_uploads")

    @classmethod
    def _is_terminal_status(cls, status: str | None) -> bool:
        return status in (
            ReconstructionStatus.SUCCESS,
            ReconstructionStatus.FAILED,
            ReconstructionStatus.CANCELLED,
        )

    @classmethod
    def _normalize_remote_status_snapshot(cls, remote_status: dict) -> dict:
        mapped_status = map_celery_state_to_reconstruction_status(
            str(remote_status.get("status") or "PENDING")
        )
        progress = int(remote_status.get("progress") or 0)
        current_stage = remote_status.get("current_stage")
        error_message = remote_status.get("error_message")

        if mapped_status == ReconstructionStatus.SUCCESS:
            progress = 100
            current_stage = current_stage or "完成"
            error_message = None
        elif mapped_status == ReconstructionStatus.FAILED:
            current_stage = current_stage or "失败"
        elif mapped_status == ReconstructionStatus.CANCELLED:
            current_stage = current_stage or "已取消"
            error_message = error_message or "任务已取消"
        elif mapped_status == ReconstructionStatus.PENDING:
            current_stage = current_stage or "等待中"
        elif mapped_status == ReconstructionStatus.TRAINING:
            current_stage = current_stage or "处理中"

        return {
            "status": mapped_status,
            "progress": progress,
            "current_stage": current_stage,
            "error_message": error_message,
            "ply_path": remote_status.get("ply_path"),
            "elapsed_sec": remote_status.get("elapsed_sec"),
            "output_dir": remote_status.get("output_dir"),
        }

    @classmethod
    def _infer_terminal_status_from_record(cls, record) -> str | None:
        if record is None:
            return None

        status = getattr(record, "status", None)
        if cls._is_terminal_status(status):
            return status

        completed_at = getattr(record, "completed_at", None)
        current_stage = getattr(record, "current_stage", None)
        error_message = getattr(record, "error_message", None)

        if completed_at is None:
            return None

        if current_stage == "完成":
            return ReconstructionStatus.SUCCESS
        if current_stage == "失败":
            return ReconstructionStatus.FAILED
        if error_message:
            return ReconstructionStatus.FAILED
        return None

    @classmethod
    def _build_terminal_snapshot_from_record(cls, record, status: str | None = None) -> dict | None:
        terminal_status = status or cls._infer_terminal_status_from_record(record)
        if terminal_status is None:
            return None

        progress = getattr(record, "progress", None)
        current_stage = getattr(record, "current_stage", None)
        error_message = getattr(record, "error_message", None)

        if terminal_status == ReconstructionStatus.SUCCESS:
            progress = 100
            current_stage = "完成"
            error_message = None
        elif terminal_status == ReconstructionStatus.FAILED:
            current_stage = "失败"
        elif terminal_status == ReconstructionStatus.CANCELLED:
            current_stage = current_stage or "已取消"
            error_message = error_message or "任务已取消"

        return {
            "status": terminal_status,
            "progress": progress,
            "current_stage": current_stage,
            "error_message": error_message,
            "completed_at": getattr(record, "completed_at", None),
            "elapsed_sec": getattr(record, "elapsed_sec", None),
        }

    @classmethod
    def _apply_record_status_snapshot(
        cls,
        record,
        *,
        status: str,
        progress: int | None,
        current_stage: str | None,
        error_message: str | None,
        completed_at=None,
        elapsed_sec: float | None = None,
    ) -> None:
        if record is None:
            return
        record.status = status
        if progress is not None:
            record.progress = progress
        if current_stage is not None:
            record.current_stage = current_stage
        if error_message is not None or status in (
            ReconstructionStatus.SUCCESS,
            ReconstructionStatus.FAILED,
            ReconstructionStatus.CANCELLED,
        ):
            record.error_message = error_message
        if completed_at is not None:
            record.completed_at = completed_at
        if elapsed_sec is not None:
            record.elapsed_sec = elapsed_sec

    @classmethod
    def _needs_status_update(
        cls,
        record,
        *,
        status: str,
        progress: int | None,
        current_stage: str | None,
        error_message: str | None,
        completed_at=None,
        elapsed_sec: float | None = None,
    ) -> bool:
        if record is None:
            return True
        return (
            status != getattr(record, "status", None)
            or progress != getattr(record, "progress", None)
            or current_stage != getattr(record, "current_stage", None)
            or error_message != getattr(record, "error_message", None)
            or (completed_at is not None and completed_at != getattr(record, "completed_at", None))
            or (elapsed_sec is not None and elapsed_sec != getattr(record, "elapsed_sec", None))
        )

    @classmethod
    async def _update_terminal_status(
        cls,
        *,
        session,
        task_id: str,
        status: str,
        progress: int,
        current_stage: str,
        error_message: str | None,
        completed_at,
        elapsed_sec: float | None,
        record=None,
    ):
        await ReconstructionRecord.update_status(
            session=session,
            task_id=task_id,
            status=status,
            progress=progress,
            current_stage=current_stage,
            error_message=error_message,
            completed_at=completed_at,
            elapsed_sec=elapsed_sec,
        )
        cls._apply_record_status_snapshot(
            record,
            status=status,
            progress=progress,
            current_stage=current_stage,
            error_message=error_message,
            completed_at=completed_at,
            elapsed_sec=elapsed_sec,
        )

    @classmethod
    def _response_time_updated(cls, record) -> str | None:
        response_status = cls._infer_terminal_status_from_record(record) or getattr(record, "status", None)
        if cls._is_terminal_status(response_status) and getattr(record, "completed_at", None):
            return record.completed_at.isoformat()
        return record.time_updated.isoformat() if record.time_updated else None

    @classmethod
    async def _apply_remote_status_to_record(cls, *, session, record, remote_status: dict) -> bool:
        remote_mapped_status = map_celery_state_to_reconstruction_status(
            str(remote_status.get("status") or "PENDING")
        )
        terminal_snapshot = cls._build_terminal_snapshot_from_record(record)
        if terminal_snapshot is not None and remote_mapped_status in (
            ReconstructionStatus.PENDING,
            ReconstructionStatus.TRAINING,
        ):
            db_changed = cls._needs_status_update(record, **terminal_snapshot)
            if db_changed:
                await cls._update_terminal_status(
                    session=session,
                    task_id=record.task_id,
                    record=record,
                    **terminal_snapshot,
                )
            return db_changed

        snapshot = cls._normalize_remote_status_snapshot(remote_status)
        status = snapshot["status"]
        progress = snapshot["progress"]
        current_stage = snapshot["current_stage"]
        error_message = snapshot["error_message"]
        elapsed_sec = snapshot["elapsed_sec"]
        result_changed = False
        completed_at = None

        if status == ReconstructionStatus.SUCCESS:
            result_changed = await cls._persist_success_result(
                session=session,
                record=record,
                task_result={
                    "ply_path": snapshot["ply_path"],
                    "output_dir": snapshot["output_dir"],
                    "elapsed_sec": elapsed_sec,
                },
            )
            completed_at = getattr(record, "completed_at", None) or datetime.utcnow()
        elif status in (ReconstructionStatus.FAILED, ReconstructionStatus.CANCELLED):
            completed_at = getattr(record, "completed_at", None) or datetime.utcnow()

        db_changed = result_changed or cls._needs_status_update(
            record,
            status=status,
            progress=progress,
            current_stage=current_stage,
            error_message=error_message,
            completed_at=completed_at,
            elapsed_sec=elapsed_sec,
        )
        if not db_changed:
            return result_changed

        if completed_at is not None:
            await cls._update_terminal_status(
                session=session,
                task_id=record.task_id,
                status=status,
                progress=progress,
                current_stage=current_stage,
                error_message=error_message,
                completed_at=completed_at,
                elapsed_sec=elapsed_sec,
                record=record,
            )
            return True

        await ReconstructionRecord.update_status(
            session=session,
            task_id=record.task_id,
            status=status,
            progress=progress,
            current_stage=current_stage,
            error_message=error_message,
            elapsed_sec=elapsed_sec,
        )
        cls._apply_record_status_snapshot(
            record,
            status=status,
            progress=progress,
            current_stage=current_stage,
            error_message=error_message,
            elapsed_sec=elapsed_sec,
        )
        return True

    @classmethod
    async def _get_item_name_map(cls, session, item_ids: list[int]) -> dict[int, str]:
        item_name_map: dict[int, str] = {}
        if not item_ids:
            return item_name_map

        async for item in Items.get_item_by_id_list(session, item_ids):
            item_name_map[item.id] = item.item_name
        return item_name_map

    @classmethod
    def _serialize_task_record(
        cls,
        record: ReconstructionRecord,
        item_name_map: dict[int, str] | None = None,
    ) -> dict:
        response_snapshot = cls._build_terminal_snapshot_from_record(record)
        return {
            "task_id": record.task_id,
            "item_id": record.item_id,
            "item_name": (item_name_map or {}).get(record.item_id),
            "task_type": getattr(record, "task_type", None),
            "status": (response_snapshot or {}).get("status", record.status),
            "progress": (response_snapshot or {}).get("progress", record.progress),
            "current_stage": (response_snapshot or {}).get("current_stage", record.current_stage),
            "scene_name": getattr(record, "scene_name", None),
            "error_message": (response_snapshot or {}).get("error_message", record.error_message),
            "ply_url": record.ply_url,
            "glb_url": record.glb_url,
            "total_frames": record.total_frames,
            "filtered_frames": record.filtered_frames,
            "colmap_points": record.colmap_points,
            "time_created": record.time_created.isoformat() if record.time_created else None,
            "time_updated": cls._response_time_updated(record),
        }

    @classmethod
    async def statistics(cls) -> dict:
        async with SessionLocal() as session:
            summary = await ReconstructionRecord.summarize_tasks(session)

        success_base = summary["success_tasks"] + summary["failed_tasks"]
        success_rate = (summary["success_tasks"] / success_base) if success_base else 0
        return {
            **summary,
            "success_rate": success_rate,
        }

    @classmethod
    async def _require_item_exists(cls, item_id: int):
        """确保配件存在，避免重建记录写入时触发外键异常。"""
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session, item_id)

        if item is None:
            raise ReconstructionBusinessError(f"配件不存在: item_id={item_id}")

        return item

    @classmethod
    def _resolve_video_task_inputs(cls, item: Items) -> tuple[str, str]:
        """从配件元数据解析视频重构所需的内部输入。"""
        if not item.source_video_path:
            raise ReconstructionBusinessError(f"配件未绑定原始视频: item_id={item.id}")
        return item.source_video_path, item.item_name

    @staticmethod
    def _build_video_run_name(item_name: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        safe_name = re.sub(r"[\\\\/:*?\"<>|]+", "_", (item_name or "reconstruction")).strip()
        safe_name = safe_name or "reconstruction"
        return f"{timestamp}_{safe_name}"

    @staticmethod
    def _page_to_limit_offset(page: int, page_size: int) -> tuple[int, int]:
        current_page = max(page, 1)
        return page_size, (current_page - 1) * page_size

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        raw_name = Path(filename or "source_video.mp4").name
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
        return safe_name or "source_video.mp4"

    @staticmethod
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

    @classmethod
    def _build_source_video_multipart_object_name(cls, item_id: int, file_name: str) -> str:
        safe_name = cls._safe_filename(file_name)
        date_dir = datetime.now().strftime("%Y%m%d")
        return f"raw-videos/{item_id}/{date_dir}/{get_id()}_{safe_name}"

    @staticmethod
    def _multipart_upload_expires_at() -> str:
        return (datetime.utcnow() + timedelta(days=7)).isoformat()

    @staticmethod
    def _strip_presigned_url_host(url: str) -> str:
        parsed = urlsplit(url)
        return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))

    @classmethod
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

    @classmethod
    def _validate_part_numbers(cls, part_numbers: list[int], total_parts: int) -> list[int]:
        normalized_part_numbers = sorted({int(part_number) for part_number in part_numbers})
        if not normalized_part_numbers:
            raise ReconstructionBusinessError("part_numbers不能为空")
        for part_number in normalized_part_numbers:
            if part_number < 1 or part_number > total_parts:
                raise ReconstructionBusinessError(f"分片编号超出范围: {part_number}")
        return normalized_part_numbers

    @classmethod
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

    @classmethod
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

    @classmethod
    def _build_local_upload_init_payload(cls, upload_session) -> dict:
        return cls._build_upload_session_payload(upload_session, upload_urls=[])

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
    async def _require_upload_session(cls, upload_session_id: int):
        async with SessionLocal() as session:
            upload_session = await ReconstructionVideoUploadSession.get_by_id(session, upload_session_id)

        if upload_session is None:
            raise ReconstructionBusinessError(f"上传会话不存在: upload_session_id={upload_session_id}")
        if upload_session.status != "initiated":
            raise ReconstructionBusinessError(f"上传会话不可继续操作: upload_session_id={upload_session_id}")

        return upload_session

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
    async def _delete_minio_object(
        cls,
        minio_path: str | None,
        default_bucket: str | None = minio_reconstruction_video_bucket,
    ) -> bool:
        if not minio_path:
            return False

        _, _, minio_instance, parse_minio_path, S3Error = _get_minio_helpers()
        bucket, object_name = parse_minio_path(
            minio_path,
            default_bucket=default_bucket,
        )

        def _delete() -> bool:
            try:
                minio_instance.client.remove_object(bucket, object_name)
                return True
            except S3Error as exc:
                if exc.code in {"NoSuchKey", "NoSuchBucket"}:
                    logger.warning(f"MinIO对象不存在，跳过删除: {minio_path}, code={exc.code}")
                    return False
                raise

        return await run_sync(_delete)

    @classmethod
    def _build_result_object_name(cls, item_id: int, task_id: str) -> str:
        return f"results/{item_id}/{task_id}/point_cloud.ply"

    @classmethod
    def _format_reconstruction_result_path(cls, object_name: str) -> str:
        return f"{minio_reconstruction_file_bucket}/{object_name}"

    @staticmethod
    def _safe_result_filename(filename: str | None) -> str:
        raw_name = Path(filename or "point_cloud.ply").name
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
        return safe_name or "point_cloud.ply"

    @classmethod
    def _resolve_record_ply_path(cls, record) -> str | None:
        _, looks_like_minio_path, _, _, _ = _get_minio_helpers()
        if record.ply_url and not looks_like_minio_path(
            record.ply_url,
            default_bucket=minio_reconstruction_file_bucket,
        ):
            return record.ply_url

        if record.output_path:
            return str(
                Path(record.output_path)
                / "point_cloud"
                / f"iteration_{record.iterations}"
                / "point_cloud.ply"
            )

        return None

    @classmethod
    def _resolve_sam3_model_path(
        cls,
        is_sam3: bool,
        configured_path: str | None = None,
    ) -> str:
        if not is_sam3:
            return ""

        model_path = configured_path if configured_path is not None else sam3_model_path
        if model_path is None or str(model_path).strip() == "":
            raise ReconstructionBusinessError("启用SAM3时必须配置 SAM3_MODEL_PATH")

        if not Path(model_path).exists():
            raise ReconstructionBusinessError(f"SAM3_MODEL_PATH不存在: {model_path}")

        return str(model_path)

    @classmethod
    async def _upload_reconstruction_result_file(
        cls,
        item_id: int,
        task_id: str,
        ply_path: str,
    ) -> str | None:
        if not ply_path:
            return None

        if not os.path.exists(ply_path):
            logger.warning(f"重构结果文件不存在，跳过上传: task_id={task_id}, path={ply_path}")
            return None

        ensure_minio_bucket, _, minio_instance, _, _ = _get_minio_helpers()
        ensure_minio_bucket(minio_reconstruction_file_bucket)
        object_name = cls._build_result_object_name(item_id=item_id, task_id=task_id)

        def _upload() -> None:
            minio_instance.client.fput_object(
                minio_reconstruction_file_bucket,
                object_name,
                ply_path,
                content_type="application/octet-stream",
            )

        await run_sync(_upload)
        return cls._format_reconstruction_result_path(object_name)

    @classmethod
    async def _upload_manual_reconstruction_result_file(cls, item_id: int, file) -> dict:
        ensure_minio_bucket, _, minio_instance, _, _ = _get_minio_helpers()
        ensure_minio_bucket(minio_reconstruction_file_bucket)
        safe_name = cls._safe_result_filename(file.filename)
        object_name = f"results/manual/{item_id}/{get_id()}_{safe_name}"
        content_type = file.content_type or "application/octet-stream"

        def _upload() -> int:
            file.file.seek(0, os.SEEK_END)
            size = file.file.tell()
            file.file.seek(0)
            minio_instance.client.put_object(
                minio_reconstruction_file_bucket,
                object_name,
                file.file,
                length=size,
                content_type=content_type,
            )
            return size

        size = await run_sync(_upload)
        await file.close()
        return {
            "ply_url": cls._format_reconstruction_result_path(object_name),
            "filename": safe_name,
            "size": size,
            "content_type": content_type,
        }

    @classmethod
    async def _persist_success_result(
        cls,
        session,
        record: ReconstructionRecord,
        task_result: dict,
    ) -> bool:
        ply_path = task_result.get("ply_path")
        if task_result.get("output_dir") and not record.output_path:
            await ReconstructionRecord.update_result(
                session=session,
                task_id=record.task_id,
                output_path=task_result.get("output_dir"),
            )
        if not ply_path:
            return False

        _, looks_like_minio_path, _, _, _ = _get_minio_helpers()
        if looks_like_minio_path(
            ply_path,
            default_bucket=minio_reconstruction_file_bucket,
        ):
            changed = False
            await ReconstructionRecord.update_result(
                session=session,
                task_id=record.task_id,
                output_path=task_result.get("output_dir"),
                ply_url=ply_path,
            )
            if record.ply_url != ply_path:
                record.ply_url = ply_path
                changed = True
            item = await Items.get_item_by_id(session, record.item_id)
            if item is not None and item.obj_url != ply_path:
                await Items.update_obj_url(
                    session=session,
                    item_id=record.item_id,
                    obj_url=ply_path,
                )
                changed = True
            return changed

        if record.ply_url and looks_like_minio_path(
            record.ply_url,
            default_bucket=minio_reconstruction_file_bucket,
        ):
            item = await Items.get_item_by_id(session, record.item_id)
            if item is not None and not item.obj_url:
                await Items.update_obj_url(
                    session=session,
                    item_id=record.item_id,
                    obj_url=record.ply_url,
                )
                return True
            return False

        result_path = await cls._upload_reconstruction_result_file(
            item_id=record.item_id,
            task_id=record.task_id,
            ply_path=ply_path,
        )
        if result_path is None:
            return False

        await ReconstructionRecord.update_result(
            session=session,
            task_id=record.task_id,
            output_path=task_result.get("output_dir"),
            ply_url=result_path,
        )
        await Items.update_obj_url(
            session=session,
            item_id=record.item_id,
            obj_url=result_path,
        )
        record.ply_url = result_path
        return True

    @classmethod
    async def persist_task_result_by_task_id(cls, task_id: str, task_result: dict) -> bool:
        async with SessionLocal() as session:
            record = await ReconstructionRecord.get_by_task_id(session, task_id)
            if not record:
                logger.warning(f"重构结果持久化时未找到任务记录: task_id={task_id}")
                return False

            completed_at = datetime.utcnow()
            elapsed_sec = task_result.get("elapsed_sec")
            task_error = get_reconstruction_task_failure_message(task_result)
            if task_error is not None:
                await ReconstructionRecord.update_status(
                    session=session,
                    task_id=task_id,
                    status=ReconstructionStatus.FAILED,
                    progress=record.progress,
                    current_stage="失败",
                    error_message=task_error,
                    completed_at=completed_at,
                    elapsed_sec=elapsed_sec,
                )
                await session.commit()
                return False

            changed = await cls._persist_success_result(
                session=session,
                record=record,
                task_result=task_result,
            )

            await ReconstructionRecord.update_status(
                session=session,
                task_id=task_id,
                status=ReconstructionStatus.SUCCESS,
                progress=100,
                current_stage="完成",
                error_message=None,
                completed_at=completed_at,
                elapsed_sec=elapsed_sec,
            )
            await session.commit()
            return changed

    @classmethod
    async def ensure_item_result_persisted(cls, item_id: int) -> bool:
        async with SessionLocal() as session:
            item = await Items.get_item_by_id(session, item_id)
            if item is None or item.obj_url:
                return False

            records = await ReconstructionRecord.get_by_item_id(session, item_id)
            for record in records:
                if record.status != ReconstructionStatus.SUCCESS:
                    continue

                changed = await cls._persist_success_result(
                    session=session,
                    record=record,
                    task_result={
                        "ply_path": cls._resolve_record_ply_path(record),
                        "output_dir": record.output_path,
                    },
                )
                if changed:
                    await session.commit()
                    return True

            return False

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
    async def _minio_health_check(cls) -> bool:
        ensure_minio_bucket, _, _, _, _ = _get_minio_helpers()

        def _check() -> bool:
            ensure_minio_bucket(minio_reconstruction_video_bucket)
            return True

        try:
            return await run_sync(_check)
        except Exception:
            return False

    @classmethod
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

    @classmethod
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

    @classmethod
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

    @classmethod
    async def get_source_video(cls, item_id: int) -> dict:
        item = await cls._require_item_exists(item_id)
        if not item.source_video_path:
            raise ReconstructionBusinessError(f"配件未绑定原始视频: item_id={item_id}")
        return cls._format_source_video_item(item, message="原始视频查询成功")

    @classmethod
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

    @classmethod
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
    
    @classmethod
    async def submit_train_task(
        cls,
        item_id: int,
        scene: str,
        iterations: int = 30000,
        output_name: str = None
    ) -> dict:
        """
        提交训练任务（从已有场景数据）
        
        Args:
            item_id: 配件ID
            scene: 场景名称
            iterations: 训练迭代次数
            output_name: 输出名称
            
        Returns:
            dict: 包含 task_id 的响应
        """
        await cls._require_item_exists(item_id)
        client = cls._get_reconstruction_client()
        task_id = str(uuid4())

        async with SessionLocal() as session:
            await ReconstructionRecord.create_record(
                session=session,
                item_id=item_id,
                task_id=task_id,
                task_type="train",
                scene_name=scene,
                iterations=iterations
            )
            await ReconstructionRecord.update_status(
                session=session,
                task_id=task_id,
                status=ReconstructionStatus.PENDING,
                progress=0,
                current_stage="已提交",
                error_message=None,
            )
            await session.commit()

        try:
            await client.submit_train_task(
                {
                    "task_id": task_id,
                    "item_id": str(item_id),
                    "scene": scene,
                    "iterations": iterations,
                    "output_name": output_name,
                }
            )
        except ReconstructionServiceClientError as exc:
            async with SessionLocal() as session:
                await ReconstructionRecord.update_status(
                    session=session,
                    task_id=task_id,
                    status=ReconstructionStatus.FAILED,
                    progress=0,
                    current_stage="投递失败",
                    error_message=str(exc),
                    completed_at=datetime.utcnow(),
                )
                await session.commit()
            raise ReconstructionBusinessError(str(exc)) from exc

        logger.info(f"训练任务已提交: task_id={task_id}, item_id={item_id}, scene={scene}")

        return {
            "task_id": task_id,
            "item_id": item_id,
            "mode": "train",
            "message": "训练任务已提交"
        }
    
    @classmethod
    async def submit_video_task(
        cls,
        item_id: int,
        iterations: int = 30000,
        fps: float = 3,
        image_size: int = 1600,
        blur_threshold: float = 0,
        dedup_threshold: int = 25,
        min_frames: int = 30,
        is_sam3: bool = False,
        text_prompt: str = "object",
        mask_dilate: int = 15,
        camera: str = "OPENCV",
        no_gpu: bool = True,
        skip_extract: bool = False,
        skip_filter: bool = False,
        skip_colmap: bool = False,
        skip_sam3: bool = False,
    ) -> dict:
        """
        提交视频重建任务
        
        Args:
            item_id: 配件ID
            iterations: 训练迭代次数
            其他参数见 video_reconstruction task
            
        Returns:
            dict: 包含 task_id 的响应
        """
        item = await cls._require_item_exists(item_id)
        video_path, name = cls._resolve_video_task_inputs(item)
        client = cls._get_reconstruction_client()
        
        # 本地路径直接检查；MinIO 对象路径由 Celery worker 下载后再检查。
        _, looks_like_minio_path, _, _, _ = _get_minio_helpers()
        if not looks_like_minio_path(video_path) and not os.path.exists(video_path):
            raise ValueError(f"视频文件不存在: {video_path}")

        run_name = cls._build_video_run_name(name)

        sam3_model = cls._resolve_sam3_model_path(is_sam3=is_sam3)
        task_id = str(uuid4())
        
        # 先创建数据库记录，避免 worker 很快完成时查不到 task_id。
        async with SessionLocal() as session:
            await ReconstructionRecord.create_record(
                session=session,
                item_id=item_id,
                task_id=task_id,
                task_type="video",
                scene_name=run_name,
                video_path=video_path,
                iterations=iterations
            )
            await ReconstructionRecord.update_status(
                session=session,
                task_id=task_id,
                status=ReconstructionStatus.PENDING,
                progress=0,
                current_stage="已提交",
                error_message=None,
            )
            await session.commit()

        try:
            await client.submit_video_task(
                {
                    "task_id": task_id,
                    "item_id": str(item_id),
                    "video_path": video_path,
                    "name": run_name,
                    "iterations": iterations,
                    "fps": fps,
                    "image_size": image_size,
                    "blur_threshold": blur_threshold,
                    "dedup_threshold": dedup_threshold,
                    "min_frames": min_frames,
                    "sam3_model": sam3_model,
                    "text_prompt": text_prompt,
                    "mask_dilate": mask_dilate,
                    "camera": camera,
                    "no_gpu": no_gpu,
                    "skip_extract": skip_extract,
                    "skip_filter": skip_filter,
                    "skip_colmap": skip_colmap,
                    "skip_sam3": skip_sam3,
                    "output_name": run_name,
                }
            )
        except ReconstructionServiceClientError as exc:
            async with SessionLocal() as session:
                await ReconstructionRecord.update_status(
                    session=session,
                    task_id=task_id,
                    status=ReconstructionStatus.FAILED,
                    progress=0,
                    current_stage="投递失败",
                    error_message=str(exc),
                    completed_at=datetime.utcnow(),
                )
                await session.commit()
            raise ReconstructionBusinessError(str(exc)) from exc
        
        logger.info(f"视频重建任务已提交: task_id={task_id}, item_id={item_id}, video={video_path}")
        
        return {
            "task_id": task_id,
            "item_id": item_id,
            "mode": "video",
            "message": "视频重建任务已提交"
        }
    
    @classmethod
    async def get_task_status(cls, task_id: str) -> dict:
        """
        获取任务状态（从远端 reconstruction_server）
        
        Args:
            task_id: 任务ID
            
        Returns:
            dict: 任务状态信息
        """
        async with SessionLocal() as session:
            record = await ReconstructionRecord.get_by_task_id(session, task_id)
            if not record:
                raise ReconstructionBusinessError(f"重构任务不存在: task_id={task_id}")

            if reconstruction_server_env_configured():
                remote_status = None
                try:
                    remote_status = await cls._get_reconstruction_client().get_task_status(task_id)
                except ReconstructionServiceClientError as exc:
                    logger.warning(f"查询远端重构任务状态失败，回退本地快照: task_id={task_id}, err={exc}")

                if remote_status is not None:
                    changed = await cls._apply_remote_status_to_record(
                        session=session,
                        record=record,
                        remote_status=remote_status,
                    )
                    if changed:
                        await session.commit()

            response_snapshot = cls._build_terminal_snapshot_from_record(record)
            
            # 返回完整信息
            return {
                "task_id": task_id,
                "item_id": record.item_id,
                "status": (response_snapshot or {}).get("status", record.status),
                "progress": (response_snapshot or {}).get("progress", record.progress),
                "current_stage": (response_snapshot or {}).get("current_stage", record.current_stage),
                "error_message": (response_snapshot or {}).get("error_message", record.error_message),
                "ply_url": record.ply_url,
                "glb_url": record.glb_url,
                "total_frames": record.total_frames,
                "filtered_frames": record.filtered_frames,
                "colmap_points": record.colmap_points,
                "time_created": record.time_created.isoformat() if record.time_created else None,
                "time_updated": cls._response_time_updated(record),
            }

    @classmethod
    async def upload_reconstruction_result(cls, item_id: int, file) -> dict:
        item = await cls._require_item_exists(item_id)
        if item.obj_url:
            raise ReconstructionBusinessError("已经存在重构模型，请先删除后再上传")
        if not str(file.filename or "").lower().endswith(".ply"):
            raise ReconstructionBusinessError("仅支持上传 .ply 文件")

        uploaded = await cls._upload_manual_reconstruction_result_file(item_id, file)

        async with SessionLocal() as session:
            try:
                await Items.update_obj_url(
                    session=session,
                    item_id=item_id,
                    obj_url=uploaded["ply_url"],
                )
                await session.commit()
            except Exception:
                await session.rollback()
                await cls._delete_minio_object(
                    uploaded["ply_url"],
                    default_bucket=minio_reconstruction_file_bucket,
                )
                raise

        return {
            "item_id": item_id,
            "ply_url": uploaded["ply_url"],
            "filename": uploaded["filename"],
            "size": uploaded["size"],
            "content_type": uploaded["content_type"],
            "message": "重构模型上传成功",
        }

    @classmethod
    async def delete_reconstruction_result(cls, item_id: int) -> dict:
        item = await cls._require_item_exists(item_id)
        result_path = item.obj_url
        if not result_path:
            raise ReconstructionBusinessError(f"配件未绑定三维重构结果: item_id={item_id}")

        _, looks_like_minio_path, _, _, _ = _get_minio_helpers()
        is_minio_result = looks_like_minio_path(
            result_path,
            default_bucket=minio_reconstruction_file_bucket,
        )
        deleted = False
        if is_minio_result:
            deleted = await cls._delete_minio_object(
                result_path,
                default_bucket=minio_reconstruction_file_bucket,
            )
        else:
            logger.info(f"当前重构结果不是MinIO路径，仅清理数据库引用: item_id={item_id}, path={result_path}")

        async with SessionLocal() as session:
            await Items.update_obj_url(session=session, item_id=item_id, obj_url=None)
            await ReconstructionRecord.clear_current_result_by_url(
                session=session,
                item_id=item_id,
                result_url=result_path,
            )
            await session.commit()

        if is_minio_result:
            message = "三维重构结果删除成功" if deleted else "三维重构结果对象不存在，元数据已清理"
        else:
            message = "旧本地重构结果引用已清理"

        return {
            "item_id": item_id,
            "result_path": result_path,
            "message": message,
        }
    
    @classmethod
    async def list_item_tasks(cls, item_id: int) -> list[dict]:
        """
        列出配件的所有重构任务
        
        Args:
            item_id: 配件ID
            
        Returns:
            list[dict]: 任务列表
        """
        async with SessionLocal() as session:
            records = await ReconstructionRecord.get_by_item_id(session, item_id)
            item_name_map = await cls._get_item_name_map(
                session=session,
                item_ids=list({record.item_id for record in records if getattr(record, "item_id", None) is not None}),
            )
            return [cls._serialize_task_record(record, item_name_map=item_name_map) for record in records]
    
    @classmethod
    async def list_all_tasks(
        cls,
        status: str = None,
        page: int = 1,
        page_size: int = 100
    ) -> dict:
        """
        列出所有重构任务（支持分页和状态筛选）
        
        Args:
            status: 任务状态筛选（可选）
            page: 页码
            page_size: 每页数量
            
        Returns:
            dict: 包含任务列表和总数
        """
        limit, offset = cls._page_to_limit_offset(page=page, page_size=page_size)
        async with SessionLocal() as session:
            records, total = await ReconstructionRecord.get_all_tasks(
                session=session,
                status=status,
                limit=limit,
                offset=offset
            )
            item_name_map = await cls._get_item_name_map(
                session=session,
                item_ids=list({record.item_id for record in records if getattr(record, "item_id", None) is not None}),
            )
            return {
                "total": total,
                "page": page,
                "pageSize": page_size,
                "records": [cls._serialize_task_record(record, item_name_map=item_name_map) for record in records]
            }
    
    @classmethod
    async def list_scenes(cls) -> list[str]:
        """
        列出可用场景
        
        Returns:
            list[str]: 场景名称列表
        """
        try:
            payload = await cls._get_reconstruction_client().list_scenes()
        except ReconstructionServiceClientError as exc:
            raise ReconstructionBusinessError(str(exc)) from exc
        return list(payload.get("scenes") or [])
    
    @classmethod
    async def cancel_task(cls, task_id: str) -> dict:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            dict: 取消结果
        """
        try:
            await cls._get_reconstruction_client().cancel_task(task_id)
        except ReconstructionServiceClientError as exc:
            raise ReconstructionBusinessError(str(exc)) from exc
        
        async with SessionLocal() as session:
            await ReconstructionRecord.update_status(
                session=session,
                task_id=task_id,
                status=ReconstructionStatus.CANCELLED,
                current_stage="已取消",
                error_message="任务已取消",
                completed_at=datetime.utcnow(),
            )
            await session.commit()
        
        logger.info(f"任务已取消: task_id={task_id}")
        
        return {"message": f"任务 {task_id} 已取消"}
