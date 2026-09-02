"""Viewer360 持久化后台队列、取消、Retry 和发布生命周期。"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from pathlib import Path
import shutil
import time
from typing import Any
from uuid import uuid4

import anyio

from csrcqsf.core.settings import (
    viewer360_enabled,
    viewer360_max_concurrent_tasks,
    viewer360_work_retention_days,
)
from csrcqsf.modules.railway_parts.repositories.viewer360_repository import (
    Viewer360Repository,
)
from csrcqsf.modules.railway_parts.services.viewer360_models import (
    Viewer360Cancelled,
    Viewer360Config,
)
from csrcqsf.modules.railway_parts.services.viewer360_pipeline import (
    Viewer360Pipeline,
    Viewer360PipelineError,
)
from csrcqsf.modules.railway_parts.services.viewer360_storage_service import (
    Viewer360StorageService,
)


logger = logging.getLogger(__name__)


class Viewer360NotFoundError(LookupError):
    pass


class Viewer360ConflictError(RuntimeError):
    def __init__(self, message: str, *, task_id: str | None = None) -> None:
        super().__init__(message)
        self.task_id = task_id


def _serialize_task(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    payload = dict(record)
    if payload.get("item_id") is not None:
        payload["item_id"] = str(payload["item_id"])
    for field in (
        "source_video_updated_at",
        "result_deleted_at",
        "heartbeat_at",
        "started_at",
        "completed_at",
        "time_created",
        "time_updated",
    ):
        if isinstance(payload.get(field), datetime):
            payload[field] = payload[field].isoformat()
    manifest = payload.get("manifest_object")
    payload["manifest_url"] = (
        f"/{payload.get('output_bucket')}/{manifest}" if manifest else None
    )
    rows = [dict(row) for row in (payload.get("row_states_json") or [])]
    frame_count = int(payload.get("amount_x") or 0)
    bucket = payload.get("output_bucket")
    if manifest and bucket and frame_count > 0 and not payload.get("result_deleted_at"):
        result_base_url = f"{bucket}/{manifest.rsplit('/', 1)[0]}"
        for row in rows:
            row_index = int(row["row_index"])
            image_base_url = (
                f"{result_base_url}/images/row_{row_index:02d}"
            )
            # 前端按 1...frame_count 生成四位补零帧号即可直接加载该角度图片。
            row.update(
                image_base_url=image_base_url,
                frame_count=frame_count,
                frame_url_template=f"{image_base_url}/frame_{{frame_no}}.webp",
            )
    payload["rows"] = rows
    return payload


def _default_pipeline() -> Viewer360Pipeline:
    from csrcqsf.core import settings

    config = Viewer360Config(
        work_root=Path(settings.viewer360_work_dir),
        rotation_seconds=settings.viewer360_rotation_seconds,
        transition_seconds=settings.viewer360_transition_seconds,
        row_count=settings.viewer360_row_count,
        row_directions=settings.viewer360_row_directions,
        fps=settings.viewer360_fps,
        image_size=settings.viewer360_image_size,
        webp_quality=settings.viewer360_webp_quality,
        center_p95_ratio=settings.viewer360_center_p95_ratio,
        ffmpeg_threads=settings.viewer360_ffmpeg_threads,
        task_timeout_seconds=settings.viewer360_task_timeout_seconds,
    )
    return Viewer360Pipeline(
        config,
        model_timeout_seconds=settings.viewer360_model_timeout_seconds,
    )


class Viewer360TaskManager:
    def __init__(
        self,
        *,
        repository=None,
        pipeline: Viewer360Pipeline | None = None,
        storage: Viewer360StorageService | None = None,
        max_concurrency: int = 1,
        enabled: bool = True,
        work_retention_days: int = 7,
    ) -> None:
        self.repository = repository or Viewer360Repository()
        self._pipeline = pipeline
        self.storage = storage or getattr(pipeline, "storage", None) or Viewer360StorageService()
        self.max_concurrency = max(1, int(max_concurrency))
        self.enabled = bool(enabled)
        self.work_retention_days = max(1, int(work_retention_days))
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task[Any]] = []
        self._submit_lock = asyncio.Lock()

    @property
    def pipeline(self) -> Viewer360Pipeline:
        if self._pipeline is None:
            self._pipeline = _default_pipeline()
            self.storage = self._pipeline.storage
        return self._pipeline

    async def start_workers(self) -> None:
        if not self.enabled or self._workers:
            return
        await self._cleanup_expired_work_dirs()
        self._workers = [
            asyncio.create_task(
                self._worker(index),
                name=f"viewer360-worker-{index + 1}",
            )
            for index in range(self.max_concurrency)
        ]

    def _work_root(self) -> Path:
        configured = getattr(getattr(self._pipeline, "config", None), "work_root", None)
        if configured is not None:
            return Path(configured)
        from csrcqsf.core.settings import viewer360_work_dir

        return Path(viewer360_work_dir)

    async def _cleanup_expired_work_dirs(self) -> None:
        work_root = self._work_root()
        cutoff = time.time() - self.work_retention_days * 86400

        def cleanup() -> None:
            if not work_root.is_dir():
                return
            for child in work_root.iterdir():
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child)

        await anyio.to_thread.run_sync(cleanup)

    async def _cleanup_task_work_dir(self, task_id: str) -> None:
        task_dir = self._work_root() / task_id
        await anyio.to_thread.run_sync(
            lambda: shutil.rmtree(task_dir) if task_dir.exists() else None
        )

    async def stop_workers(self) -> None:
        workers, self._workers = self._workers, []
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

    async def _worker(self, _index: int) -> None:
        while True:
            task_id = await self._queue.get()
            try:
                await self.run_task(task_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Viewer360 worker exited task unexpectedly: task_id=%s", task_id)
            finally:
                self._queue.task_done()

    async def submit(self, *, item_id: int, rebuild_existing: bool) -> dict[str, Any]:
        if not self.enabled:
            raise Viewer360ConflictError("Viewer360 功能未启用")
        async with self._submit_lock:
            source = await self.repository.get_item_source(item_id)
            if source is None:
                raise Viewer360NotFoundError(f"配件不存在: item_id={item_id}")
            if not source.get("source_video_object"):
                raise Viewer360ConflictError(f"配件尚未绑定源视频: item_id={item_id}")
            active = await self.repository.find_active_by_item(item_id)
            if active is not None:
                raise Viewer360ConflictError(
                    f"配件已有 Viewer360 任务正在执行: item_id={item_id}",
                    task_id=str(active["task_id"]),
                )
            current = await self.repository.get_current(item_id)
            if current is not None and not rebuild_existing:
                record = await self.repository.get_task(str(current["task_id"])) or dict(current)
                record.setdefault("status", "success")
                record["reused_existing"] = True
                return _serialize_task(record)
            # 仅在确实需要创建新任务时探测源对象，已有结果复用不依赖源视频在线。
            await self.storage.ensure_source_readable(source["source_video_object"])
            record = await self._create_task(
                item_id=item_id,
                source=source,
                rebuild_existing=rebuild_existing,
                retry_mode="none",
                retry_rows=None,
                retry_reason=None,
                root_task_id=None,
                retry_from_task_id=None,
            )
            self._queue.put_nowait(str(record["task_id"]))
            return _serialize_task(record)

    async def _create_task(
        self,
        *,
        item_id: int,
        source: dict[str, Any],
        rebuild_existing: bool,
        retry_mode: str,
        retry_rows: list[int] | None,
        retry_reason: str | None,
        root_task_id: str | None,
        retry_from_task_id: str | None,
    ) -> dict[str, Any]:
        task_id = str(uuid4())
        pipeline_config = getattr(self._pipeline, "config", None)
        if pipeline_config is not None:
            row_count = int(pipeline_config.row_count)
        else:
            try:
                from csrcqsf.core.settings import viewer360_row_count

                row_count = viewer360_row_count
            except ImportError:
                row_count = 4
        record = await self.repository.create_task(
            task_id=task_id,
            root_task_id=root_task_id or task_id,
            retry_from_task_id=retry_from_task_id,
            item_id=item_id,
            source_video_object=source["source_video_object"],
            source_video_updated_at=source.get("source_video_updated_at"),
            rebuild_existing=rebuild_existing,
            retry_mode=retry_mode,
            retry_rows_json=retry_rows,
            retry_reason=retry_reason,
            status="pending",
            current_stage="preparing",
            progress=0,
            row_count=row_count,
            total_frames=0,
            processed_frames=0,
            reused_row_count=0,
            row_states_json=[
                {"row_index": index, "status": "pending"}
                for index in range(1, row_count + 1)
            ],
            output_bucket=self.storage.result_bucket,
            output_prefix=self.storage.result_prefix(item_id, task_id),
            heartbeat_at=datetime.now(),
        )
        record["reused_existing"] = False
        return record

    async def run_task(self, task_id: str) -> None:
        now = datetime.now()
        started = await self.repository.transition_task(
            task_id,
            ("pending",),
            status="running",
            started_at=now,
            heartbeat_at=now,
        )
        if started is None:
            return
        source_task = None
        retry_mode = started.get("retry_mode") or "none"
        if started.get("retry_from_task_id"):
            source_task = await self.repository.get_task(str(started["retry_from_task_id"]))
        elif retry_mode in {"resume", "resegment_rows"}:
            # Viewer360 重试复用原任务 ID，当前记录本身同时保存断点指纹和已发布结果。
            source_task = dict(started)

        async def progress_callback(values: dict[str, Any]) -> None:
            current = await self.repository.get_task(task_id) or {}
            values = dict(values)
            values["progress"] = max(
                int(current.get("progress", 0) or 0),
                int(values.get("progress", 0) or 0),
            )
            await self.repository.update_task(task_id, **values, heartbeat_at=datetime.now())

        async def is_cancelled() -> bool:
            current = await self.repository.get_task(task_id)
            return current is None or current.get("status") == "cancelling"

        try:
            timeout_seconds = int(
                getattr(getattr(self.pipeline, "config", None), "task_timeout_seconds", 1800)
            )
            result = await asyncio.wait_for(
                self.pipeline.run(
                    started,
                    source_task=source_task,
                    progress_callback=progress_callback,
                    is_cancelled=is_cancelled,
                ),
                timeout=timeout_seconds,
            )
            latest = await self.repository.get_task(task_id) or {}
            if latest.get("status") == "cancelling":
                # 指定角度重做沿用原 OSS 路径，取消任务不能删除仍由前端使用的旧结果。
                if retry_mode != "resegment_rows":
                    await self.storage.delete_result(
                        item_id=int(started["item_id"]),
                        task_id=task_id,
                    )
                await self.repository.transition_task(
                    task_id,
                    ("cancelling",),
                    status="cancelled",
                    completed_at=datetime.now(),
                    heartbeat_at=datetime.now(),
                )
                return
            await self.repository.publish_success(
                task_id,
                item_id=int(started["item_id"]),
                manifest_object=result.manifest_object,
                amount_x=result.amount_x,
                amount_y=result.amount_y,
                fingerprint=result.fingerprint,
                pipeline_metadata_json={
                    "target_center": list(result.target_center),
                    "pipeline_version": 1,
                },
                total_frames=result.total_frames,
                processed_frames=result.total_frames,
                row_states_json=result.row_states,
            )
            # 数据库已经原子切换到新版本后，本地中间文件才可以安全删除。
            try:
                await self._cleanup_task_work_dir(task_id)
            except Exception:
                logger.warning(
                    "Viewer360 成功任务本地目录清理失败: task_id=%s",
                    task_id,
                    exc_info=True,
                )
        except Viewer360Cancelled:
            await self.repository.transition_task(
                task_id,
                ("pending", "running", "cancelling"),
                status="cancelled",
                completed_at=datetime.now(),
                heartbeat_at=datetime.now(),
            )
        except asyncio.CancelledError:
            # 服务关闭丢失执行上下文属于可恢复中断，不等同于用户主动取消。
            await self.repository.transition_task(
                task_id,
                ("pending", "running", "cancelling"),
                status="interrupted",
                error_message="服务关闭，Viewer360 任务执行上下文已中断",
                completed_at=datetime.now(),
                heartbeat_at=datetime.now(),
            )
            raise
        except Exception as exc:
            latest = await self.repository.get_task(task_id) or {}
            if latest.get("status") == "cancelling":
                await self.repository.transition_task(
                    task_id,
                    ("cancelling",),
                    status="cancelled",
                    completed_at=datetime.now(),
                    heartbeat_at=datetime.now(),
                )
                return
            stage = exc.stage if isinstance(exc, Viewer360PipelineError) else "pipeline"
            row_index = exc.row_index if isinstance(exc, Viewer360PipelineError) else None
            await self.repository.add_failure(
                task_id=task_id,
                row_index=row_index,
                frame_index=None,
                stage=stage,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            await self.repository.transition_task(
                task_id,
                ("pending", "running"),
                status="failed",
                error_message=str(exc),
                completed_at=datetime.now(),
                heartbeat_at=datetime.now(),
            )

    async def retry(
        self,
        task_id: str,
        *,
        retry_mode: str,
        row_indexes: list[int] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise Viewer360ConflictError("Viewer360 功能未启用")
        async with self._submit_lock:
            source = await self.repository.get_task(task_id)
            if source is None:
                raise Viewer360NotFoundError(f"Viewer360 任务不存在: task_id={task_id}")
            active = await self.repository.find_active_by_item(int(source["item_id"]))
            if active is not None:
                raise Viewer360ConflictError(
                    "同一配件已有 Viewer360 任务正在执行",
                    task_id=str(active["task_id"]),
                )
            if retry_mode == "resume":
                if source["status"] not in {"failed", "cancelled", "interrupted"}:
                    raise Viewer360ConflictError(
                        f"当前任务状态不允许恢复: status={source['status']}"
                    )
                rows = None
            elif retry_mode == "resegment_rows":
                if source["status"] != "success" or source.get("result_deleted_at") is not None:
                    raise Viewer360ConflictError("只有未删除的成功结果可以按角度重新分割")
                rows = sorted(set(int(value) for value in (row_indexes or [])))
                row_count = int(source.get("row_count") or source.get("amount_y") or 0)
                if not rows or any(value < 1 or value > row_count for value in rows):
                    raise ValueError(f"row_indexes must be within 1...{row_count}")
            else:
                raise ValueError("retry_mode must be resume or resegment_rows")
            await self.storage.ensure_source_readable(source["source_video_object"])
            row_count = int(source.get("row_count") or source.get("amount_y") or 0)
            selected_rows = set(rows or range(1, row_count + 1))
            # 前端始终跟踪同一条任务记录；这里只重置执行态，保留分割断点、
            # 对齐中心和已发布 OSS 信息，供 resume 或指定角度重做复用。
            retried = await self.repository.reset_task_for_retry(
                task_id,
                (str(source["status"]),),
                root_task_id=task_id,
                retry_from_task_id=None,
                rebuild_existing=True,
                retry_mode=retry_mode,
                retry_rows_json=rows,
                retry_reason=reason,
                status="pending",
                current_stage="preparing",
                progress=0,
                total_frames=0,
                processed_frames=0,
                reused_row_count=row_count - len(selected_rows),
                row_states_json=[
                    {
                        "row_index": index,
                        "status": "pending" if index in selected_rows else "reused",
                    }
                    for index in range(1, row_count + 1)
                ],
                error_message=None,
                cancel_reason=None,
                heartbeat_at=datetime.now(),
                started_at=None,
                completed_at=None,
            )
            if retried is None:
                raise Viewer360ConflictError("任务状态已变化，请刷新后重试")
            retried["reused_existing"] = False
            self._queue.put_nowait(task_id)
            return _serialize_task(retried)

    async def cancel(self, task_id: str, reason: str | None = None) -> dict[str, Any]:
        record = await self.repository.get_task(task_id)
        if record is None:
            raise Viewer360NotFoundError(f"Viewer360 任务不存在: task_id={task_id}")
        if record["status"] == "pending":
            return _serialize_task(await self.repository.transition_task(
                task_id,
                ("pending",),
                status="cancelled",
                cancel_reason=reason,
                completed_at=datetime.now(),
                heartbeat_at=datetime.now(),
            ))
        if record["status"] == "running":
            return _serialize_task(await self.repository.transition_task(
                task_id,
                ("running",),
                status="cancelling",
                cancel_reason=reason,
                heartbeat_at=datetime.now(),
            ))
        if record["status"] in {"cancelling", "cancelled"}:
            return _serialize_task(record)
        raise Viewer360ConflictError(f"终态 Viewer360 任务不可取消: status={record['status']}")

    async def get(self, task_id: str) -> dict[str, Any] | None:
        return _serialize_task(await self.repository.get_task(task_id))

    async def list(
        self,
        *,
        page: int,
        per_page: int,
        status: str,
        item_id: int | None,
    ) -> tuple[list[dict[str, Any]], int]:
        records, total = await self.repository.list_tasks(
            page=page,
            per_page=per_page,
            status=status,
            item_id=item_id,
        )
        return [_serialize_task(record) for record in records], total

    async def list_failures(
        self,
        task_id: str,
        *,
        page: int,
        per_page: int,
    ) -> tuple[list[dict[str, Any]], int]:
        records, total = await self.repository.list_failures(
            task_id,
            page=page,
            per_page=per_page,
        )
        for record in records:
            if isinstance(record.get("time_created"), datetime):
                record["time_created"] = record["time_created"].isoformat()
        return records, total

    async def get_current_result(self, item_id: int) -> dict[str, Any]:
        current = await self.repository.get_current(item_id)
        if current is None:
            return {
                "item_id": str(item_id),
                "task_id": None,
                "has_viewer360": False,
                "manifest_url": None,
                "amount_x": None,
                "amount_y": None,
                "time_updated": None,
            }
        updated = current.get("time_updated")
        return {
            "item_id": str(item_id),
            "task_id": str(current["task_id"]),
            "has_viewer360": True,
            "manifest_url": self.storage.public_url(current["manifest_object"]),
            "amount_x": current["amount_x"],
            "amount_y": current["amount_y"],
            "time_updated": updated.isoformat() if isinstance(updated, datetime) else updated,
        }

    async def delete_result(self, task_id: str) -> dict[str, Any]:
        record = await self.repository.get_task(task_id)
        if record is None:
            raise Viewer360NotFoundError(f"Viewer360 任务不存在: task_id={task_id}")
        if record["status"] in {"pending", "running", "cancelling"}:
            raise Viewer360ConflictError("活动 Viewer360 任务不能删除结果，请先取消")
        if record.get("result_deleted_at") is None:
            await self.storage.delete_result(
                item_id=int(record["item_id"]),
                task_id=task_id,
            )
            record = await self.repository.mark_result_deleted(task_id) or record
        return _serialize_task(record)


viewer360_task_manager = Viewer360TaskManager(
    max_concurrency=viewer360_max_concurrent_tasks,
    enabled=viewer360_enabled,
    work_retention_days=viewer360_work_retention_days,
)
