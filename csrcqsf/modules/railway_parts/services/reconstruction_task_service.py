"""Reconstruction task, status, and result service implementations."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import uuid4

from csrcqsf.modules.railway_parts.services import reconstruction_result_service, reconstruction_task_detail_service

# These names are injected by bind_runtime_dependencies() at import-install time.
# Keep module-level placeholders so IDEs and static analyzers can resolve them.
run_sync: Any = None
get_id: Any = None
logger: Any = None
SessionLocal: Any = None
ReconstructionBusinessError: Any = None
ReconstructionServiceClientError: Any = None
ReconstructionRecord: Any = None
ReconstructionStatus: Any = None
Items: Any = None
reconstruction_server_env_configured: Any = None
minio_reconstruction_file_bucket: Any = None
map_celery_state_to_reconstruction_status: Any = None
get_reconstruction_task_failure_message: Any = None
_get_minio_helpers: Any = None

ReconstructionRecordType = Any
_REMOTE_RECOVERY_STATES = frozenset({"RECOVERY_QUEUED", "RECOVERING"})


def bind_runtime_dependencies(reconstruction_service_module: ModuleType | None = None) -> None:
    if reconstruction_service_module is None:
        from csrcqsf.modules.railway_parts.services import (
            reconstruction_service as reconstruction_service_module,
        )

    globals().update(
        {
            "datetime": reconstruction_service_module.datetime,
            "os": reconstruction_service_module.os,
            "re": reconstruction_service_module.re,
            "Path": reconstruction_service_module.Path,
            "uuid4": reconstruction_service_module.uuid4,
            "run_sync": reconstruction_service_module.run_sync,
            "get_id": reconstruction_service_module.get_id,
            "logger": reconstruction_service_module.logger,
            "SessionLocal": reconstruction_service_module.SessionLocal,
            "ReconstructionBusinessError": reconstruction_service_module.ReconstructionBusinessError,
            "ReconstructionServiceClientError": reconstruction_service_module.ReconstructionServiceClientError,
            "ReconstructionRecord": reconstruction_service_module.ReconstructionRecord,
            "ReconstructionStatus": reconstruction_service_module.ReconstructionStatus,
            "Items": reconstruction_service_module.Items,
            "reconstruction_server_env_configured": reconstruction_service_module.reconstruction_server_env_configured,
            "minio_reconstruction_file_bucket": reconstruction_service_module.minio_reconstruction_file_bucket,
            "map_celery_state_to_reconstruction_status": reconstruction_service_module.map_celery_state_to_reconstruction_status,
            "get_reconstruction_task_failure_message": reconstruction_service_module.get_reconstruction_task_failure_message,
            "_get_minio_helpers": reconstruction_service_module._get_minio_helpers,
        }
    )
def _runtime_context():
    return SimpleNamespace(**globals())


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
    remote_state = str(remote_status.get("status") or "PENDING").upper()
    is_recovery_state = remote_state in _REMOTE_RECOVERY_STATES
    remote_mapped_status = map_celery_state_to_reconstruction_status(
        remote_state
    )
    terminal_snapshot = cls._build_terminal_snapshot_from_record(record)
    if not is_recovery_state and terminal_snapshot is not None and remote_mapped_status in (
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

    recovery_terminal_state_cleared = False
    if is_recovery_state:
        # 明确的人工恢复状态可以重开终态；普通 PENDING/PROGRESS 仍不能让历史终态倒退。
        recovery_terminal_state_cleared = any(
            getattr(record, field, None) is not None
            for field in ("error_message", "completed_at", "elapsed_sec")
        )
        record.error_message = None
        record.completed_at = None
        record.elapsed_sec = None

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
        completed_at = getattr(record, "completed_at", None) or datetime.now()
    elif status in (ReconstructionStatus.FAILED, ReconstructionStatus.CANCELLED):
        completed_at = getattr(record, "completed_at", None) or datetime.now()

    db_changed = result_changed or recovery_terminal_state_cleared or cls._needs_status_update(
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
    record: ReconstructionRecordType,
    item_name_map: dict[int, str] | None = None,
) -> dict:
    response_snapshot = cls._build_terminal_snapshot_from_record(record)
    effective_status = (response_snapshot or {}).get("status", record.status)
    return {
        "task_id": record.task_id,
        "item_id": record.item_id,
        "item_name": (item_name_map or {}).get(record.item_id),
        "task_type": getattr(record, "task_type", None),
        "status": effective_status,
        "progress": (response_snapshot or {}).get("progress", record.progress),
        "current_stage": (response_snapshot or {}).get("current_stage", record.current_stage),
        "scene_name": getattr(record, "scene_name", None),
        "error_message": (response_snapshot or {}).get("error_message", record.error_message),
        "ply_url": cls._public_asset_url(record.ply_url),
        "glb_url": cls._public_asset_url(record.glb_url),
        "is_ply_del": reconstruction_task_detail_service.is_task_result_deleted(
            record, effective_status, ReconstructionStatus.SUCCESS),
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

def _build_result_object_name(cls, item_id: int, task_id: str, runtime=None) -> str:
    return reconstruction_result_service._build_result_object_name(
        cls,
        item_id=item_id,
        task_id=task_id,
    )

def _format_reconstruction_result_path(cls, object_name: str, runtime=None) -> str:
    return reconstruction_result_service._format_reconstruction_result_path(
        cls,
        object_name=object_name,
        runtime=runtime or _runtime_context(),
    )

def _safe_result_filename(filename: str | None, runtime=None) -> str:
    return reconstruction_result_service._safe_result_filename(
        None,
        filename=filename,
        runtime=runtime or _runtime_context(),
    )

def _resolve_record_ply_path(cls, record, runtime=None) -> str | None:
    return reconstruction_result_service._resolve_record_ply_path(
        cls,
        record=record,
        runtime=runtime or _runtime_context(),
    )

async def _upload_reconstruction_result_file(
    cls,
    item_id: int,
    task_id: str,
    ply_path: str,
    runtime=None,
) -> str | None:
    return await reconstruction_result_service._upload_reconstruction_result_file(
        cls,
        item_id=item_id,
        task_id=task_id,
        ply_path=ply_path,
        runtime=runtime or _runtime_context(),
    )

async def _upload_manual_reconstruction_result_file(cls, item_id: int, file, runtime=None) -> dict:
    return await reconstruction_result_service._upload_manual_reconstruction_result_file(
        cls,
        item_id=item_id,
        file=file,
        runtime=runtime or _runtime_context(),
    )

async def _persist_success_result(
    cls,
    session,
    record: ReconstructionRecordType,
    task_result: dict,
    runtime=None,
) -> bool:
    return await reconstruction_result_service._persist_success_result(
        cls,
        session=session,
        record=record,
        task_result=task_result,
        runtime=runtime or _runtime_context(),
    )

async def persist_task_result_by_task_id(cls, task_id: str, task_result: dict, runtime=None) -> bool:
    return await reconstruction_result_service.persist_task_result_by_task_id(
        cls,
        task_id=task_id,
        task_result=task_result,
        runtime=runtime or _runtime_context(),
    )

async def ensure_item_result_persisted(cls, item_id: int, runtime=None) -> bool:
    return await reconstruction_result_service.ensure_item_result_persisted(
        cls,
        item_id=item_id,
        runtime=runtime or _runtime_context(),
    )

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
                completed_at=datetime.now(),
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
    iterations: int,
) -> dict:
    """
    提交视频重建任务
    
    Args:
        item_id: 配件ID
        iterations: 训练迭代次数
        
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
                completed_at=datetime.now(),
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

        result_deleted = reconstruction_task_detail_service.is_task_result_deleted(record, record.status, ReconstructionStatus.SUCCESS)
        if reconstruction_server_env_configured() and not result_deleted:
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
            "ply_url": cls._public_asset_url(record.ply_url),
            "glb_url": cls._public_asset_url(record.glb_url),
            "is_ply_del": result_deleted,
            "total_frames": record.total_frames,
            "filtered_frames": record.filtered_frames,
            "colmap_points": record.colmap_points,
            "time_created": record.time_created.isoformat() if record.time_created else None,
            "time_updated": cls._response_time_updated(record),
        }
async def upload_reconstruction_result(cls, item_id: int, file, runtime=None) -> dict:
    return await reconstruction_result_service.upload_reconstruction_result(
        cls,
        item_id=item_id,
        file=file,
        runtime=runtime or _runtime_context(),
    )

async def delete_reconstruction_result(cls, task_id: str, runtime=None) -> dict:
    return await reconstruction_result_service.delete_reconstruction_result(
        cls,
        task_id=task_id,
        runtime=runtime or _runtime_context(),
    )

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
            completed_at=datetime.now(),
        )
        await session.commit()
    
    logger.info(f"任务已取消: task_id={task_id}")
    
    return {"message": f"任务 {task_id} 已取消"}
