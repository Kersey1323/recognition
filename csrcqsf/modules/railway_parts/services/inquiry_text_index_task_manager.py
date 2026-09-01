"""询码语义索引的持久化先进先出任务管理器。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4

from csrcqsf.core.logging_config import logger
from csrcqsf.modules.railway_parts.repositories.inquiry_text_index_repository import (
    InquiryTextIndexTaskRepository,
)
from csrcqsf.modules.railway_parts.services.inquiry_semantic_index_service import (
    get_inquiry_semantic_index_service,
)


RETRYABLE_STATUSES = {"failed", "cancelled", "interrupted"}
PROGRESS_FIELDS = (
    "progress",
    "total_items",
    "processed_items",
    "indexed_count",
    "skipped_count",
    "fail_count",
    "deleted_count",
    "current_inquiry_id",
)


def _decorate(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    snapshot = dict(record)
    for field in (
        "heartbeat_at",
        "started_at",
        "completed_at",
        "time_created",
        "time_updated",
    ):
        if isinstance(snapshot.get(field), datetime):
            snapshot[field] = snapshot[field].isoformat()
    return snapshot


class InquiryTextIndexTaskManager:
    """串行执行语义索引任务，避免全量切换与增量写入互相覆盖。"""
    def __init__(self, *, repository=None, service=None):
        self.repository = repository or InquiryTextIndexTaskRepository()
        self.service = service
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._active_execution: asyncio.Task | None = None
        self._active_task_id: str | None = None

    async def enqueue_incremental(
        self,
        history_ids: list[int],
        *,
        source_sync_task_id: str | None = None,
        source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = list(dict.fromkeys(int(history_id) for history_id in history_ids))
        return await self._enqueue(
            task_scope="incremental",
            history_ids=normalized,
            source_sync_task_id=source_sync_task_id,
            source=source,
        )

    async def enqueue_full(self, *, source: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._enqueue(
            task_scope="full",
            history_ids=[],
            source_sync_task_id=None,
            source=source,
        )

    async def _enqueue(
        self,
        *,
        task_scope: str,
        history_ids: list[int],
        source_sync_task_id: str | None,
        source: dict[str, Any] | None,
    ) -> dict[str, Any]:
        task_id = str(uuid4())
        source = source or {}
        record = await self.repository.create(
            task_id=task_id,
            root_task_id=source.get("root_task_id") or task_id,
            retry_from_task_id=source.get("task_id"),
            source_sync_task_id=source_sync_task_id,
            task_scope=task_scope,
            history_ids_json=history_ids,
            status="pending",
        )
        # 任务先持久化再唤醒 worker，避免进程切换时出现无法找回的内存任务。
        self._wake.set()
        return _decorate(record)

    async def start_worker(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._worker = asyncio.create_task(
            self._worker_loop(),
            name="inquiry-text-index-worker",
        )
        self._wake.set()

    async def stop_worker(self) -> None:
        if self._active_execution is not None and not self._active_execution.done():
            self._active_execution.cancel()
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None
        self._active_execution = None
        self._active_task_id = None

    async def _worker_loop(self) -> None:
        # 每次唤醒持续领取最早任务，队列清空后再休眠等待新任务。
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while record := await self.repository.claim_next_pending():
                    self._active_task_id = record["task_id"]
                    self._active_execution = asyncio.create_task(
                        self._execute(record),
                        name=f"inquiry-text-index-{record['task_id']}",
                    )
                    await self._active_execution
                    self._active_execution = None
                    self._active_task_id = None
        except asyncio.CancelledError:
            raise

    async def _execute(self, record: dict[str, Any]) -> None:
        task_id = record["task_id"]
        if self.service is None:
            # Milvus 仅在 worker 真正执行任务时初始化，未配置或未启用语义索引的
            # 主服务启动过程不会因模块导入而建立默认地址连接。
            self.service = get_inquiry_semantic_index_service()

        async def persist_progress(progress: dict[str, Any]) -> None:
            values = {
                field: progress[field]
                for field in PROGRESS_FIELDS
                if field in progress
            }
            values["heartbeat_at"] = datetime.now()
            await self.repository.update(task_id, **values)
            failures = list(progress.get("new_failure_details") or [])
            if failures:
                await self.repository.append_failures(task_id, failures)

        try:
            if record["task_scope"] == "full":
                result = await self.service.run_full(
                    task_id,
                    progress_callback=persist_progress,
                )
            else:
                result = await self.service.run_incremental(
                    list(record.get("history_ids_json") or []),
                    progress_callback=persist_progress,
                )
            if not result.get("failures_persisted_incrementally"):
                await self.repository.replace_failures(
                    task_id,
                    list(result.get("failure_details") or []),
                )
            fail_count = int(result.get("fail_count", 0) or 0)
            # 语义样本失败会影响召回完整性，因此存在失败明细即标记任务失败。
            values = {
                field: result[field]
                for field in PROGRESS_FIELDS
                if field in result
            }
            values.update(
                status="failed" if fail_count else "success",
                progress=100,
                current_inquiry_id=None,
                heartbeat_at=datetime.now(),
                completed_at=datetime.now(),
                error_message=(
                    f"{fail_count} 条询码语义索引失败，请查看失败明细"
                    if fail_count
                    else None
                ),
            )
            await self.repository.transition(task_id, ("running",), **values)
        except asyncio.CancelledError:
            current = await self.repository.get(task_id) or {}
            target = "cancelled" if current.get("status") == "cancelling" else "interrupted"
            await self.repository.transition(
                task_id,
                ("running", "cancelling"),
                status=target,
                current_inquiry_id=None,
                heartbeat_at=datetime.now(),
                completed_at=datetime.now(),
                error_message=(
                    None if target == "cancelled" else "服务停止，询码语义索引任务被中断"
                ),
            )
            if target == "interrupted":
                raise
        except Exception as exc:
            logger.exception("询码语义索引任务执行失败: task_id=%s", task_id)
            await self.repository.transition(
                task_id,
                ("running",),
                status="failed",
                current_inquiry_id=None,
                heartbeat_at=datetime.now(),
                completed_at=datetime.now(),
                error_message=str(exc) or repr(exc),
            )

    async def get(self, task_id: str) -> dict[str, Any] | None:
        return _decorate(await self.repository.get(task_id))

    async def list(self, **filters) -> tuple[list[dict[str, Any]], int]:
        records, total = await self.repository.list(**filters)
        return [_decorate(record) for record in records], total

    async def list_failures(
        self,
        task_id: str,
        *,
        page: int,
        per_page: int,
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.repository.list_failures(
            task_id,
            page=page,
            per_page=per_page,
        )

    async def cancel(
        self,
        task_id: str,
        cancel_reason: str | None = None,
    ) -> dict[str, Any]:
        # pending 可直接终止；running 先转 cancelling，再由执行协程落最终状态。
        record = await self.repository.get(task_id)
        if record is None:
            raise KeyError(task_id)
        if record["status"] == "pending":
            return _decorate(
                await self.repository.transition(
                    task_id,
                    ("pending",),
                    status="cancelled",
                    cancel_reason=cancel_reason,
                    heartbeat_at=datetime.now(),
                    completed_at=datetime.now(),
                )
            )
        if record["status"] not in {"running", "cancelling"}:
            raise RuntimeError(f"终态询码语义索引任务不可取消: status={record['status']}")
        updated = await self.repository.transition(
            task_id,
            ("running",),
            status="cancelling",
            cancel_reason=cancel_reason,
            heartbeat_at=datetime.now(),
        )
        if self._active_task_id == task_id and self._active_execution is not None:
            self._active_execution.cancel()
        return _decorate(updated or record)

    async def retry(self, task_id: str) -> dict[str, Any]:
        source = await self.repository.get(task_id)
        if source is None:
            raise KeyError(task_id)
        if source["status"] not in RETRYABLE_STATUSES:
            raise RuntimeError(f"当前状态不可重试: status={source['status']}")
        lineage = {"task_id": task_id, "root_task_id": source["root_task_id"]}
        if source["task_scope"] == "full":
            return await self.enqueue_full(source=lineage)
        return await self.enqueue_incremental(
            list(source.get("history_ids_json") or []),
            source_sync_task_id=source.get("source_sync_task_id"),
            source=lineage,
        )


inquiry_text_index_task_manager = InquiryTextIndexTaskManager()
