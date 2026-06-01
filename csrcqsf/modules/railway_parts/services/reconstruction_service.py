"""
三维重构管理器 - 业务逻辑层
主业务只负责重构任务元数据管理，并通过远端 reconstruction_server 执行任务
"""
import sys
import math
import os
import re
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from anyio.to_thread import run_sync
from bfrcommon.snowflake import get_id
from globals_vars import logger

try:
    from minio.datatypes import Part
except Exception:  # pragma: no cover - test/runtime fallback when minio extras are unavailable
    @dataclass
    class Part:
        part_number: int
        etag: str
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.biz.railwayparts.reconstruction_client import (
    ReconstructionServiceClient,
    ReconstructionServiceClientError,
)
from csrcqsf.biz.railwayparts.local_upload_storage import LocalUploadStorage
from csrcqsf.models.reconstruction import ReconstructionRecord, ReconstructionStatus
from csrcqsf.models.item import Items
from csrcqsf.models.reconstruction_upload import ReconstructionVideoUploadSession
from csrcqsf.modules.railway_parts.services import reconstruction_video_service
from csrcqsf.modules.railway_parts.services import reconstruction_task_service
from csrcqsf.biz.railwayparts.local_file_part_reader import LocalFilePartReader
from csrcqsf.settings import (
    minio_env_configured,
    minio_reconstruction_file_bucket,
    minio_reconstruction_video_bucket,
    reconstruction_server_env_configured,
    sam3_model_path,
)

try:
    from csrcqsf.data.minio import (
        ensure_minio_bucket,
        looks_like_minio_path,
        minio_instance,
        parse_minio_path,
    )
    from minio.error import S3Error
except Exception:  # pragma: no cover - import-time fallback for test patching only
    ensure_minio_bucket = None
    looks_like_minio_path = None
    minio_instance = None
    parse_minio_path = None
    S3Error = Exception


def _get_minio_helpers():
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


def _bind_reconstruction_video_runtime():
    reconstruction_video_service.bind_runtime_dependencies(sys.modules[__name__])


def _bind_reconstruction_task_runtime():
    reconstruction_task_service.bind_runtime_dependencies(sys.modules[__name__])


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
                str(Path(__file__).resolve().parents[4] / "state"),
            )
        )
        return LocalUploadStorage(state_dir / "reconstruction_uploads")













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
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._safe_filename(
            filename=filename,
        )

    @staticmethod
    def _choose_multipart_part_size(file_size: int) -> int:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._choose_multipart_part_size(
            file_size=file_size,
        )

    @classmethod
    def _build_source_video_multipart_object_name(cls, item_id: int, file_name: str) -> str:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._build_source_video_multipart_object_name(
            cls,
            item_id=item_id,
            file_name=file_name,
        )

    @staticmethod
    def _multipart_upload_expires_at() -> str:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._multipart_upload_expires_at(
        )

    @staticmethod
    def _strip_presigned_url_host(url: str) -> str:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._strip_presigned_url_host(
            url=url,
        )

    @classmethod
    def _normalize_complete_parts(cls, parts: list[dict], total_parts: int) -> list[Part]:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._normalize_complete_parts(
            cls,
            parts=parts,
            total_parts=total_parts,
        )

    @classmethod
    def _validate_part_numbers(cls, part_numbers: list[int], total_parts: int) -> list[int]:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._validate_part_numbers(
            cls,
            part_numbers=part_numbers,
            total_parts=total_parts,
        )

    @classmethod
    def _expected_local_part_size(cls, upload_session, part_number: int) -> int:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._expected_local_part_size(
            cls,
            upload_session=upload_session,
            part_number=part_number,
        )

    @classmethod
    def _build_upload_session_payload(cls, upload_session, upload_urls: list[dict] | None = None) -> dict:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._build_upload_session_payload(
            cls,
            upload_session=upload_session,
            upload_urls=upload_urls,
        )

    @classmethod
    def _build_local_upload_init_payload(cls, upload_session) -> dict:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._build_local_upload_init_payload(
            cls,
            upload_session=upload_session,
        )

    @classmethod
    async def _create_multipart_upload(cls, bucket: str, object_name: str, content_type: str) -> str:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._create_multipart_upload(
            cls,
            bucket=bucket,
            object_name=object_name,
            content_type=content_type,
        )

    @classmethod
    async def _generate_multipart_upload_urls(
        cls,
        bucket: str,
        object_name: str,
        upload_id: str,
        part_numbers: list[int],
    ) -> list[dict]:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._generate_multipart_upload_urls(
            cls,
            bucket=bucket,
            object_name=object_name,
            upload_id=upload_id,
            part_numbers=part_numbers,
        )

    @classmethod
    async def _list_multipart_uploaded_parts(cls, bucket: str, object_name: str, upload_id: str) -> list[dict]:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._list_multipart_uploaded_parts(
            cls,
            bucket=bucket,
            object_name=object_name,
            upload_id=upload_id,
        )

    @classmethod
    async def _complete_multipart_upload(
        cls,
        bucket: str,
        object_name: str,
        upload_id: str,
        parts: list[dict],
        total_parts: int,
    ) -> None:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._complete_multipart_upload(
            cls,
            bucket=bucket,
            object_name=object_name,
            upload_id=upload_id,
            parts=parts,
            total_parts=total_parts,
        )

    @classmethod
    async def _abort_multipart_upload(cls, bucket: str, object_name: str, upload_id: str) -> None:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._abort_multipart_upload(
            cls,
            bucket=bucket,
            object_name=object_name,
            upload_id=upload_id,
        )

    @classmethod
    async def _require_upload_session(cls, upload_session_id: int):
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._require_upload_session(
            cls,
            upload_session_id=upload_session_id,
        )

    @classmethod
    def _format_source_video_item(cls, item: Items, message: str | None = None) -> dict:
        _bind_reconstruction_video_runtime()
        return reconstruction_video_service._format_source_video_item(
            cls,
            item=item,
            message=message,
        )

    @classmethod
    async def _upload_multipart_part_bytes(
        cls,
        bucket: str,
        object_name: str,
        upload_id: str,
        part_number: int,
        data: bytes,
    ) -> str:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._upload_multipart_part_bytes(
            cls,
            bucket=bucket,
            object_name=object_name,
            upload_id=upload_id,
            part_number=part_number,
            data=data,
        )

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
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._init_remote_source_video_upload(
            cls,
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
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._init_local_source_video_upload(
            cls,
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
    async def _upload_source_video_file(cls, item_id: int, file) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._upload_source_video_file(
            cls,
            item_id=item_id,
            file=file,
        )


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
    async def upload_source_video(
        cls,
        item_id: int,
        file,
        height: float | None = None,
        length: float | None = None,
        width: float | None = None,
        weight: float | None = None,
    ) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.upload_source_video(
            cls,
            item_id=item_id,
            file=file,
            height=height,
            length=length,
            width=width,
            weight=weight,
        )

    @classmethod
    async def upload_source_video_local_part(
        cls,
        upload_session_id: int,
        part_number: int,
        file,
    ) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.upload_source_video_local_part(
            cls,
            upload_session_id=upload_session_id,
            part_number=part_number,
            file=file,
        )

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
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.init_source_video_multipart_upload(
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
        )

    @classmethod
    async def get_source_video_upload_progress(cls, upload_session_id: int) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.get_source_video_upload_progress(
            cls,
            upload_session_id=upload_session_id,
        )

    @classmethod
    async def get_source_video_upload_urls(cls, upload_session_id: int, part_numbers: list[int]) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.get_source_video_upload_urls(
            cls,
            upload_session_id=upload_session_id,
            part_numbers=part_numbers,
        )

    @classmethod
    async def complete_source_video_multipart_upload(cls, upload_session_id: int) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.complete_source_video_multipart_upload(
            cls,
            upload_session_id=upload_session_id,
        )

    @classmethod
    async def abort_source_video_multipart_upload(cls, upload_session_id: int) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.abort_source_video_multipart_upload(
            cls,
            upload_session_id=upload_session_id,
        )

    @classmethod
    async def _complete_local_source_video_upload(cls, upload_session) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._complete_local_source_video_upload(
            cls,
            upload_session=upload_session,
        )

    @classmethod
    async def _abort_local_source_video_upload(cls, upload_session) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._abort_local_source_video_upload(
            cls,
            upload_session=upload_session,
        )

    @classmethod
    async def _minio_health_check(cls) -> bool:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._minio_health_check(
            cls,
        )

    @classmethod
    async def _sync_local_session_to_remote(cls, upload_session, session) -> bool:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service._sync_local_session_to_remote(
            cls,
            upload_session=upload_session,
            session=session,
        )

    @classmethod
    async def check_minio_and_sync_local_uploads(cls) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.check_minio_and_sync_local_uploads(
            cls,
        )

    @classmethod
    async def list_source_videos(cls, page: int = 1, page_size: int = 100) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.list_source_videos(
            cls,
            page=page,
            page_size=page_size,
        )

    @classmethod
    async def get_source_video(cls, item_id: int) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.get_source_video(
            cls,
            item_id=item_id,
        )

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
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.update_source_video(
            cls,
            item_id=item_id,
            file=file,
            height=height,
            length=length,
            width=width,
            weight=weight,
        )

    @classmethod
    async def delete_source_video(cls, item_id: int) -> dict:
        _bind_reconstruction_video_runtime()
        return await reconstruction_video_service.delete_source_video(
            cls,
            item_id=item_id,
        )

_TASK_SERVICE_CLASSMETHODS = (
    "_is_terminal_status",
    "_normalize_remote_status_snapshot",
    "_infer_terminal_status_from_record",
    "_build_terminal_snapshot_from_record",
    "_apply_record_status_snapshot",
    "_needs_status_update",
    "_response_time_updated",
    "_serialize_task_record",
    "statistics",
    "_build_result_object_name",
    "_format_reconstruction_result_path",
    "_resolve_record_ply_path",
    "_resolve_sam3_model_path",
    "_update_terminal_status",
    "_apply_remote_status_to_record",
    "_get_item_name_map",
    "_upload_reconstruction_result_file",
    "_upload_manual_reconstruction_result_file",
    "_persist_success_result",
    "persist_task_result_by_task_id",
    "ensure_item_result_persisted",
    "submit_train_task",
    "submit_video_task",
    "get_task_status",
    "upload_reconstruction_result",
    "delete_reconstruction_result",
    "list_item_tasks",
    "list_all_tasks",
    "list_scenes",
    "cancel_task",
)

_TASK_SERVICE_STATICMETHODS = (
    "_safe_result_filename",
)


def _make_reconstruction_task_classmethod(name: str, *, is_async: bool):
    if is_async:
        async def _wrapper(cls, *args, **kwargs):
            _bind_reconstruction_task_runtime()
            method = getattr(reconstruction_task_service, name)
            return await method(cls, *args, **kwargs)
    else:
        def _wrapper(cls, *args, **kwargs):
            _bind_reconstruction_task_runtime()
            method = getattr(reconstruction_task_service, name)
            return method(cls, *args, **kwargs)
    _wrapper.__name__ = name
    return classmethod(_wrapper)


def _make_reconstruction_task_staticmethod(name: str):
    def _wrapper(*args, **kwargs):
        _bind_reconstruction_task_runtime()
        method = getattr(reconstruction_task_service, name)
        return method(*args, **kwargs)
    _wrapper.__name__ = name
    return staticmethod(_wrapper)


def _install_reconstruction_task_service_methods() -> None:
    async_names = {
        "_update_terminal_status",
        "_apply_remote_status_to_record",
        "_get_item_name_map",
        "statistics",
        "_upload_reconstruction_result_file",
        "_upload_manual_reconstruction_result_file",
        "_persist_success_result",
        "persist_task_result_by_task_id",
        "ensure_item_result_persisted",
        "submit_train_task",
        "submit_video_task",
        "get_task_status",
        "upload_reconstruction_result",
        "delete_reconstruction_result",
        "list_item_tasks",
        "list_all_tasks",
        "list_scenes",
        "cancel_task",
    }
    for method_name in _TASK_SERVICE_CLASSMETHODS:
        setattr(
            ReconstructionManager,
            method_name,
            _make_reconstruction_task_classmethod(
                method_name,
                is_async=method_name in async_names,
            ),
        )
    for method_name in _TASK_SERVICE_STATICMETHODS:
        setattr(
            ReconstructionManager,
            method_name,
            _make_reconstruction_task_staticmethod(method_name),
        )


_install_reconstruction_task_service_methods()
