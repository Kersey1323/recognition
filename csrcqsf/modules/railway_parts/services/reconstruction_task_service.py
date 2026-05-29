"""Reconstruction task, status, and result service implementations."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def bind_runtime_dependencies() -> None:
    from csrcqsf.modules.railway_parts.services import reconstruction_service

    globals().update(
        {
            "datetime": reconstruction_service.datetime,
            "os": reconstruction_service.os,
            "re": reconstruction_service.re,
            "Path": reconstruction_service.Path,
            "uuid4": reconstruction_service.uuid4,
            "run_sync": reconstruction_service.run_sync,
            "get_id": reconstruction_service.get_id,
            "logger": reconstruction_service.logger,
            "SessionLocal": reconstruction_service.SessionLocal,
            "ReconstructionBusinessError": reconstruction_service.ReconstructionBusinessError,
            "ReconstructionServiceClientError": reconstruction_service.ReconstructionServiceClientError,
            "ReconstructionRecord": reconstruction_service.ReconstructionRecord,
            "ReconstructionStatus": reconstruction_service.ReconstructionStatus,
            "Items": reconstruction_service.Items,
            "reconstruction_server_env_configured": reconstruction_service.reconstruction_server_env_configured,
            "sam3_model_path": reconstruction_service.sam3_model_path,
            "minio_reconstruction_file_bucket": reconstruction_service.minio_reconstruction_file_bucket,
            "map_celery_state_to_reconstruction_status": reconstruction_service.map_celery_state_to_reconstruction_status,
            "get_reconstruction_task_failure_message": reconstruction_service.get_reconstruction_task_failure_message,
            "_get_minio_helpers": reconstruction_service._get_minio_helpers,
        }
    )


def _is_terminal_status(cls, status: str | None) -> bool:
    return status in (
        ReconstructionStatus.SUCCESS,
        ReconstructionStatus.FAILED,
        ReconstructionStatus.CANCELLED,
    )

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

def _response_time_updated(cls, record) -> str | None:
    response_status = cls._infer_terminal_status_from_record(record) or getattr(record, "status", None)
    if cls._is_terminal_status(response_status) and getattr(record, "completed_at", None):
        return record.completed_at.isoformat()
    return record.time_updated.isoformat() if record.time_updated else None

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

async def _get_item_name_map(cls, session, item_ids: list[int]) -> dict[int, str]:
    item_name_map: dict[int, str] = {}
    if not item_ids:
        return item_name_map

    async for item in Items.get_item_by_id_list(session, item_ids):
        item_name_map[item.id] = item.item_name
    return item_name_map

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

async def statistics(cls) -> dict:
    async with SessionLocal() as session:
        summary = await ReconstructionRecord.summarize_tasks(session)

    success_base = summary["success_tasks"] + summary["failed_tasks"]
    success_rate = (summary["success_tasks"] / success_base) if success_base else 0
    return {
        **summary,
        "success_rate": success_rate,
    }

def _build_result_object_name(cls, item_id: int, task_id: str) -> str:
    return f"results/{item_id}/{task_id}/point_cloud.ply"

def _format_reconstruction_result_path(cls, object_name: str) -> str:
    return f"{minio_reconstruction_file_bucket}/{object_name}"

def _safe_result_filename(filename: str | None) -> str:
    raw_name = Path(filename or "point_cloud.ply").name
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    return safe_name or "point_cloud.ply"

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
