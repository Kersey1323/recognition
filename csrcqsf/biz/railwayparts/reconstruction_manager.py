"""
三维重构管理器 - 业务逻辑层
直接调用 Celery 任务，支持 Flower 监控
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from anyio.to_thread import run_sync
from bfrcommon.snowflake import get_id
from celery.result import AsyncResult
from minio.error import S3Error
from globals_vars import logger
from csrcqsf.data.minio import ensure_minio_bucket, looks_like_minio_path, minio_instance, parse_minio_path
from csrcqsf.data.pg import SessionLocal
from csrcqsf.models.reconstruction import ReconstructionRecord, ReconstructionStatus
from csrcqsf.models.item import Items
from csrcqsf.settings import (
    minio_reconstruction_file_bucket,
    minio_reconstruction_video_bucket,
    sam3_model_path,
)

# 导入 Celery app 和 tasks - 使用延迟导入避免启动时的循环依赖
_celery_app = None
_train_reconstruction = None
_video_reconstruction = None

def _get_celery_modules():
    """延迟导入 Celery 模块"""
    global _celery_app, _train_reconstruction, _video_reconstruction
    
    if _celery_app is None:
        reconstruction_server_path = Path(__file__).parent / "reconstruction_server"
        if str(reconstruction_server_path) not in sys.path:
            sys.path.insert(0, str(reconstruction_server_path))
        
        from celery_app import celery_app
        from tasks import train_reconstruction, video_reconstruction
        
        _celery_app = celery_app
        _train_reconstruction = train_reconstruction
        _video_reconstruction = video_reconstruction
    
    return _celery_app, _train_reconstruction, _video_reconstruction

# 路径配置
BASE_DIR = Path(__file__).parent / "reconstruction_server"
DATA_DIR = BASE_DIR / "data"


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
    def _resolve_terminal_completed_at(cls, celery_result, fallback=None):
        return _normalize_datetime(getattr(celery_result, "date_done", None)) or fallback or datetime.utcnow()

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
        if record.status in (
            ReconstructionStatus.SUCCESS,
            ReconstructionStatus.FAILED,
            ReconstructionStatus.CANCELLED,
        ) and getattr(record, "completed_at", None):
            return record.completed_at.isoformat()
        return record.time_updated.isoformat() if record.time_updated else None

    @classmethod
    async def _refresh_record_from_celery_result(cls, *, session, record, result) -> bool:
        new_status = map_celery_state_to_reconstruction_status(result.state)
        progress = record.progress
        stage = record.current_stage
        error = record.error_message
        result_changed = False
        db_changed = False

        if result.state == "PROGRESS":
            info = result.info or {}
            stage = info.get("stage", stage)
            progress = info.get("progress", progress)
            db_changed = cls._needs_status_update(
                record,
                status=new_status,
                progress=progress,
                current_stage=stage,
                error_message=error,
            )
            if db_changed:
                await ReconstructionRecord.update_status(
                    session=session,
                    task_id=record.task_id,
                    status=new_status,
                    progress=progress,
                    current_stage=stage,
                    error_message=error,
                )
                cls._apply_record_status_snapshot(
                    record,
                    status=new_status,
                    progress=progress,
                    current_stage=stage,
                    error_message=error,
                )
            return db_changed

        if result.state == "SUCCESS":
            task_result = result.result or {}
            completed_at = cls._resolve_terminal_completed_at(result, getattr(record, "completed_at", None))
            elapsed_sec = task_result.get("elapsed_sec", getattr(record, "elapsed_sec", None))
            task_error = get_reconstruction_task_failure_message(task_result)
            if task_error is not None:
                new_status = ReconstructionStatus.FAILED
                stage = "失败"
                error = task_error
                db_changed = cls._needs_status_update(
                    record,
                    status=new_status,
                    progress=progress,
                    current_stage=stage,
                    error_message=error,
                    completed_at=completed_at,
                    elapsed_sec=elapsed_sec,
                )
                if db_changed:
                    await cls._update_terminal_status(
                        session=session,
                        task_id=record.task_id,
                        status=new_status,
                        progress=progress,
                        current_stage=stage,
                        error_message=error,
                        completed_at=completed_at,
                        elapsed_sec=elapsed_sec,
                        record=record,
                    )
                return db_changed

            progress = 100
            stage = "完成"
            error = None
            result_changed = await cls._persist_success_result(
                session=session,
                record=record,
                task_result=task_result,
            )
            db_changed = result_changed or cls._needs_status_update(
                record,
                status=ReconstructionStatus.SUCCESS,
                progress=progress,
                current_stage=stage,
                error_message=error,
                completed_at=completed_at,
                elapsed_sec=elapsed_sec,
            )
            if db_changed:
                await cls._update_terminal_status(
                    session=session,
                    task_id=record.task_id,
                    status=ReconstructionStatus.SUCCESS,
                    progress=progress,
                    current_stage=stage,
                    error_message=error,
                    completed_at=completed_at,
                    elapsed_sec=elapsed_sec,
                    record=record,
                )
            return db_changed or result_changed

        if result.state == "FAILURE":
            new_status = ReconstructionStatus.FAILED
            stage = "失败"
            error = str(result.info)
            completed_at = cls._resolve_terminal_completed_at(result, getattr(record, "completed_at", None))
            elapsed_sec = getattr(record, "elapsed_sec", None)
            db_changed = cls._needs_status_update(
                record,
                status=new_status,
                progress=progress,
                current_stage=stage,
                error_message=error,
                completed_at=completed_at,
                elapsed_sec=elapsed_sec,
            )
            if db_changed:
                await cls._update_terminal_status(
                    session=session,
                    task_id=record.task_id,
                    status=new_status,
                    progress=progress,
                    current_stage=stage,
                    error_message=error,
                    completed_at=completed_at,
                    elapsed_sec=elapsed_sec,
                    record=record,
                )
            return db_changed

        db_changed = cls._needs_status_update(
            record,
            status=new_status,
            progress=progress,
            current_stage=stage,
            error_message=error,
        )
        if db_changed:
            await ReconstructionRecord.update_status(
                session=session,
                task_id=record.task_id,
                status=new_status,
                progress=progress,
                current_stage=stage,
                error_message=error,
            )
            cls._apply_record_status_snapshot(
                record,
                status=new_status,
                progress=progress,
                current_stage=stage,
                error_message=error,
            )
        return db_changed

    @classmethod
    async def _refresh_records_from_celery(cls, session, records) -> None:
        if not records:
            return
        celery_app, _, _ = _get_celery_modules()
        for record in records:
            needs_refresh = (
                record.status not in (
                    ReconstructionStatus.SUCCESS,
                    ReconstructionStatus.FAILED,
                    ReconstructionStatus.CANCELLED,
                )
                or (record.status == ReconstructionStatus.SUCCESS and (record.progress != 100 or record.current_stage != "完成"))
                or (
                    record.status in (
                        ReconstructionStatus.SUCCESS,
                        ReconstructionStatus.FAILED,
                        ReconstructionStatus.CANCELLED,
                    ) and not getattr(record, "completed_at", None)
                )
            )
            if not needs_refresh:
                continue
            result = AsyncResult(record.task_id, app=celery_app)
            await cls._refresh_record_from_celery_result(session=session, record=record, result=result)

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
        return {
            "task_id": record.task_id,
            "item_id": record.item_id,
            "item_name": (item_name_map or {}).get(record.item_id),
            "task_type": getattr(record, "task_type", None),
            "status": record.status,
            "progress": record.progress,
            "current_stage": record.current_stage,
            "scene_name": getattr(record, "scene_name", None),
            "error_message": record.error_message,
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
    async def _upload_source_video_file(cls, item_id: int, file) -> dict:
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

        # 获取 Celery 模块
        _, train_reconstruction, _ = _get_celery_modules()
        
        # 检查场景是否存在
        scene_dir = DATA_DIR / scene
        if not scene_dir.exists():
            raise ValueError(f"场景 '{scene}' 不存在: {scene_dir}")
        
        # 生成输出名称
        if not output_name:
            output_name = f"{scene}_{int(os.urandom(4).hex(), 16):08x}"
        
        # 提交 Celery 任务
        task = train_reconstruction.apply_async(
            args=[scene, iterations, output_name]
        )
        task_id = task.id
        
        # 创建数据库记录
        async with SessionLocal() as session:
            await ReconstructionRecord.create_record(
                session=session,
                item_id=item_id,
                task_id=task_id,
                task_type="train",
                scene_name=scene,
                iterations=iterations
            )
            await session.commit()
        
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

        # 获取 Celery 模块
        _, _, video_reconstruction = _get_celery_modules()
        
        # 本地路径直接检查；MinIO 对象路径由 Celery worker 下载后再检查。
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
            await session.commit()

        try:
            video_reconstruction.apply_async(
                kwargs={
                    "video_path": video_path,
                    "name": run_name,
                    "iterations": iterations,
                    "output_name": run_name,
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
                },
                task_id=task_id,
            )
        except Exception as exc:
            async with SessionLocal() as session:
                await ReconstructionRecord.update_status(
                    session=session,
                    task_id=task_id,
                    status=ReconstructionStatus.FAILED,
                    progress=0,
                    current_stage="投递失败",
                    error_message=str(exc),
                )
                await session.commit()
            raise
        
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
        获取任务状态（从 Celery）
        
        Args:
            task_id: 任务ID
            
        Returns:
            dict: 任务状态信息
        """
        # 获取 Celery 模块
        celery_app, _, _ = _get_celery_modules()
        
        # 从 Celery 获取任务状态
        result = AsyncResult(task_id, app=celery_app)
        
        # 从数据库获取记录
        async with SessionLocal() as session:
            record = await ReconstructionRecord.get_by_task_id(session, task_id)
            
            if not record:
                # 如果数据库中没有记录，只返回 Celery 状态
                response = {
                    "task_id": task_id,
                    "status": map_celery_state_to_reconstruction_status(result.state),
                    "result": None,
                    "error": None,
                    "stage": None,
                    "progress": 0,
                }
                
                if result.state == "PENDING":
                    response["stage"] = "等待中"
                elif result.state == "STARTED":
                    response["stage"] = "已开始"
                elif result.state == "PROGRESS":
                    info = result.info or {}
                    response["stage"] = info.get("stage", "处理中")
                    response["progress"] = info.get("progress", 0)
                elif result.state == "SUCCESS":
                    response["result"] = result.result
                    task_error = get_reconstruction_task_failure_message(result.result)
                    if task_error is not None:
                        response["status"] = ReconstructionStatus.FAILED
                        response["stage"] = "失败"
                        response["error"] = task_error
                    else:
                        response["stage"] = "完成"
                        response["progress"] = 100
                elif result.state == "FAILURE":
                    response["stage"] = "失败"
                    response["error"] = str(result.info)
                
                return response
            
            changed = await cls._refresh_record_from_celery_result(
                session=session,
                record=record,
                result=result,
            )
            if changed:
                await session.commit()
            
            # 返回完整信息
            return {
                "task_id": task_id,
                "item_id": record.item_id,
                "status": record.status,
                "progress": record.progress,
                "current_stage": record.current_stage,
                "error_message": record.error_message,
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
            await cls._refresh_records_from_celery(session, records)
            item_name_map = await cls._get_item_name_map(
                session=session,
                item_ids=list({record.item_id for record in records if getattr(record, "item_id", None) is not None}),
            )
            await session.commit()
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
            await cls._refresh_records_from_celery(session, records)
            item_name_map = await cls._get_item_name_map(
                session=session,
                item_ids=list({record.item_id for record in records if getattr(record, "item_id", None) is not None}),
            )
            await session.commit()
            return {
                "total": total,
                "page": page,
                "pageSize": page_size,
                "records": [cls._serialize_task_record(record, item_name_map=item_name_map) for record in records]
            }
    
    @classmethod
    def list_scenes(cls) -> list[str]:
        """
        列出可用场景
        
        Returns:
            list[str]: 场景名称列表
        """
        if not DATA_DIR.exists():
            return []
        return sorted(
            d.name for d in DATA_DIR.iterdir()
            if d.is_dir() and (d / "sparse").exists()
        )
    
    @classmethod
    async def cancel_task(cls, task_id: str) -> dict:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            dict: 取消结果
        """
        # 获取 Celery 模块
        celery_app, _, _ = _get_celery_modules()
        
        result = AsyncResult(task_id, app=celery_app)
        result.revoke(terminate=True)
        
        # 更新数据库状态
        async with SessionLocal() as session:
            await ReconstructionRecord.update_status(
                session=session,
                task_id=task_id,
                status=ReconstructionStatus.FAILED,
                error_message="任务已取消"
            )
            await session.commit()
        
        logger.info(f"任务已取消: task_id={task_id}")
        
        return {"message": f"任务 {task_id} 已取消"}
