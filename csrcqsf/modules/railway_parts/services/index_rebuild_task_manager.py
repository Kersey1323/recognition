"""V2 图片索引任务的并发控制与持久化生命周期管理。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Awaitable, Callable
from uuid import uuid4

from csrcqsf.core.settings import index_single_task_max_concurrency
from csrcqsf.modules.railway_parts.repositories.index_rebuild_task_repository import (
    IndexRebuildTaskRepository,
)


logger = logging.getLogger(__name__)

IndexRebuildRunner = Callable[..., Awaitable[dict[str, Any]]]
RETRYABLE_STATUSES = {"interrupted", "failed", "cancelled"}


def _format_remaining(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds <= 0:
        return "已完成"
    hours, remainder = divmod(seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"约{hours}小时{minutes}分钟"
    if minutes:
        return f"约{minutes}分{remaining_seconds}秒"
    return f"约{remaining_seconds}秒"


def _decorate(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    snapshot = dict(record)
    snapshot["estimated_remaining"] = _format_remaining(
        snapshot.get("estimated_remaining_seconds")
    )
    for field in ("item_id", "current_item_id", "last_completed_item_id"):
        if snapshot.get(field) is not None:
            snapshot[field] = str(snapshot[field])
    for field in (
        "last_completed_item_created_at",
        "heartbeat_at",
        "started_at",
        "completed_at",
        "time_created",
        "time_updated",
    ):
        if isinstance(snapshot.get(field), datetime):
            snapshot[field] = snapshot[field].isoformat()
    return snapshot


@dataclass
class _ActiveTask:
    task: asyncio.Task[Any]
    task_scope: str
    item_id: int | None


class IndexRebuildTaskManager:
    """在进程内执行索引任务，并将前端可观察状态持续写入 MySQL。"""

    def __init__(
        self,
        repository=None,
        max_single_tasks: int | None = None,
    ) -> None:
        self._repository = repository or IndexRebuildTaskRepository()
        self._max_single_tasks = max_single_tasks or index_single_task_max_concurrency
        self._active: dict[str, _ActiveTask] = {}
        self._lock = asyncio.Lock()
        self._capacity_listener: Callable[[], None] | None = None

    @property
    def active_task_ids(self) -> tuple[str, ...]:
        return tuple(self._active.keys())

    @property
    def active_single_item_ids(self) -> tuple[int, ...]:
        return tuple(
            active.item_id
            for active in self._active.values()
            if active.task_scope == "single" and active.item_id is not None
        )

    @property
    def available_single_slots(self) -> int:
        active_values = tuple(self._active.values())
        if any(active.task_scope == "batch" for active in active_values):
            return 0
        running_single_count = sum(
            active.task_scope == "single" for active in active_values
        )
        return max(self._max_single_tasks - running_single_count, 0)

    def set_capacity_listener(self, listener: Callable[[], None] | None) -> None:
        self._capacity_listener = listener

    def _notify_capacity_available(self) -> None:
        listener = self._capacity_listener
        if listener is None:
            return
        try:
            listener()
        except Exception:
            logger.exception("V2 index task capacity listener failed")

    async def start(
        self,
        runner: IndexRebuildRunner,
        item_id: int | None,
        limit: int | None,
        rebuild_existing: bool,
    ) -> dict[str, Any]:
        return await self._start(
            runner=runner,
            item_id=item_id,
            record_limit=limit,
            execution_limit=limit,
            rebuild_existing=rebuild_existing,
        )

    async def try_start_single(
        self,
        runner: IndexRebuildRunner,
        *,
        item_id: int,
    ) -> dict[str, Any] | None:
        return await self._start(
            runner=runner,
            item_id=item_id,
            record_limit=1,
            execution_limit=1,
            rebuild_existing=False,
            return_none_when_unavailable=True,
        )

    async def _start(
        self,
        *,
        runner: IndexRebuildRunner,
        item_id: int | None,
        record_limit: int | None,
        execution_limit: int | None,
        rebuild_existing: bool,
        source: dict[str, Any] | None = None,
        return_none_when_unavailable: bool = False,
    ) -> dict[str, Any] | None:
        # 先在锁内检查容量并创建记录，避免并发请求同时越过任务上限。
        task_scope = "single" if item_id is not None else "batch"
        async with self._lock:
            try:
                self._check_capacity(task_scope, item_id)
            except RuntimeError:
                if return_none_when_unavailable:
                    return None
                raise
            task_id = str(uuid4())
            initial = source or {}
            record = await self._repository.create(
                task_id=task_id,
                root_task_id=initial.get("root_task_id") or task_id,
                retry_from_task_id=initial.get("task_id"),
                task_scope=task_scope,
                item_id=item_id,
                item_limit=record_limit,
                rebuild_existing=rebuild_existing,
                progress=int(initial.get("progress", 0) or 0),
                total_items=int(initial.get("total_items", 0) or 0),
                completed_item_count=int(initial.get("completed_item_count", 0) or 0),
                processed_items=int(initial.get("processed_items", 0) or 0),
                success_count=int(initial.get("success_count", 0) or 0),
                fail_count=int(initial.get("fail_count", 0) or 0),
                segmented_count=int(initial.get("segmented_count", 0) or 0),
                fallback_count=int(initial.get("fallback_count", 0) or 0),
                last_completed_item_id=initial.get("last_completed_item_id"),
                last_completed_item_created_at=initial.get(
                    "last_completed_item_created_at"
                ),
            )
            task = asyncio.create_task(
                self._run(
                    task_id=task_id,
                    runner=runner,
                    item_id=item_id,
                    limit=execution_limit,
                    rebuild_existing=rebuild_existing,
                    initial=initial,
                ),
                name=f"v2-index-rebuild-{task_id}",
            )
            self._active[task_id] = _ActiveTask(task, task_scope, item_id)
            task.add_done_callback(
                lambda completed_task, completed_task_id=task_id: self._on_task_done(
                    completed_task_id,
                    completed_task,
                )
            )
            return _decorate(record)

    def _on_task_done(
        self,
        task_id: str,
        completed_task: asyncio.Task[Any],
    ) -> None:
        if not completed_task.cancelled():
            error = completed_task.exception()
            if error is not None:
                logger.error(
                    "V2 index rebuild task lifecycle exited unexpectedly: task_id=%s",
                    task_id,
                    exc_info=(type(error), error, error.__traceback__),
                )
        asyncio.create_task(
            self._finalize_finished_task(task_id, completed_task),
            name=f"v2-index-rebuild-finalize-{task_id}",
        )

    async def _finalize_finished_task(
        self,
        task_id: str,
        completed_task: asyncio.Task[Any],
    ) -> None:
        if completed_task.cancelled():
            record = await self._repository.get(task_id)
            if record is not None and record.get("status") in {
                "pending",
                "running",
                "cancelling",
            }:
                # 协程首步前被取消时不会进入 _run，由完成回调补齐 cancelled 终态。
                now = datetime.now()
                await self._repository.transition(
                    task_id,
                    ("pending", "running", "cancelling"),
                    status="cancelled",
                    current_item_id=None,
                    completed_at=now,
                    heartbeat_at=now,
                    estimated_remaining_seconds=None,
                )
        removed = False
        async with self._lock:
            active = self._active.get(task_id)
            if active is not None and active.task is completed_task:
                self._active.pop(task_id, None)
                removed = True
        if removed:
            self._notify_capacity_available()

    def _check_capacity(self, task_scope: str, item_id: int | None) -> None:
        # 批量任务全局唯一；单配件任务允许并发，但同一配件不能重复执行。
        active_values = tuple(self._active.values())
        has_batch = any(active.task_scope == "batch" for active in active_values)
        if has_batch or (task_scope == "batch" and active_values):
            raise RuntimeError("批量索引任务与其他索引任务不能并行")
        if task_scope == "single":
            if any(active.item_id == item_id for active in active_values):
                raise RuntimeError(f"配件已有索引任务正在执行: item_id={item_id}")
            single_count = sum(
                active.task_scope == "single" for active in active_values
            )
            if single_count >= self._max_single_tasks:
                raise RuntimeError(
                    f"单配件索引任务已达到并发上限: {self._max_single_tasks}"
                )

    async def _run(
        self,
        *,
        task_id: str,
        runner: IndexRebuildRunner,
        item_id: int | None,
        limit: int | None,
        rebuild_existing: bool,
        initial: dict[str, Any],
    ) -> None:
        now = datetime.now()
        started = await self._repository.transition(
            task_id,
            ("pending",),
            status="running",
            started_at=now,
            heartbeat_at=now,
        )
        if started is None:
            return

        async def persist_progress(progress: dict[str, Any]) -> None:
            await self._repository.update(
                task_id,
                **progress,
                heartbeat_at=datetime.now(),
            )

        try:
            result = await runner(
                item_id=item_id,
                limit=limit,
                rebuild_existing=rebuild_existing,
                progress_callback=persist_progress,
                resume_after_created_at=initial.get("last_completed_item_created_at"),
                resume_after_item_id=initial.get("last_completed_item_id"),
                initial_completed_item_count=int(
                    initial.get("completed_item_count", 0) or 0
                ),
                initial_success_count=int(initial.get("success_count", 0) or 0),
                initial_fail_count=int(initial.get("fail_count", 0) or 0),
                initial_segmented_count=int(initial.get("segmented_count", 0) or 0),
                initial_fallback_count=int(initial.get("fallback_count", 0) or 0),
                total_items_override=int(initial.get("total_items", 0) or 0) or None,
            )
            current = await self._repository.get(task_id) or {}
            completed = await self._repository.transition(
                task_id,
                ("running",),
                status="success",
                progress=100,
                processed_items=int(current.get("total_items", 0) or 0),
                completed_item_count=int(current.get("total_items", 0) or 0),
                success_count=int(result.get("success_count", 0) or 0),
                fail_count=int(result.get("fail_count", 0) or 0),
                segmented_count=int(result.get("segmented_count", 0) or 0),
                fallback_count=int(result.get("fallback_count", 0) or 0),
                current_item_id=None,
                completed_at=datetime.now(),
                heartbeat_at=datetime.now(),
                estimated_remaining_seconds=0,
            )
            if completed is None:
                current = await self._repository.get(task_id) or {}
                if current.get("status") == "cancelling":
                    now = datetime.now()
                    await self._repository.transition(
                        task_id,
                        ("cancelling",),
                        status="cancelled",
                        current_item_id=None,
                        completed_at=now,
                        heartbeat_at=now,
                        estimated_remaining_seconds=None,
                    )
        except asyncio.CancelledError:
            now = datetime.now()
            await self._repository.transition(
                task_id,
                ("pending", "running", "cancelling"),
                status="cancelled",
                current_item_id=None,
                completed_at=now,
                heartbeat_at=now,
                estimated_remaining_seconds=None,
            )
            raise
        except Exception as exc:
            logger.exception("V2 index rebuild task failed: task_id=%s", task_id)
            now = datetime.now()
            failed = await self._repository.transition(
                task_id,
                ("pending", "running"),
                status="failed",
                current_item_id=None,
                completed_at=now,
                heartbeat_at=now,
                error_message=str(exc),
                estimated_remaining_seconds=None,
            )
            if failed is None:
                await self._repository.transition(
                    task_id,
                    ("cancelling",),
                    status="cancelled",
                    current_item_id=None,
                    completed_at=now,
                    heartbeat_at=now,
                    estimated_remaining_seconds=None,
                )
        finally:
            removed = False
            async with self._lock:
                removed = self._active.pop(task_id, None) is not None
            if removed:
                # 任一手工或自动单配件任务结束后立即唤醒扫描器补充空闲并发位。
                self._notify_capacity_available()

    async def get(self, task_id: str) -> dict[str, Any] | None:
        return _decorate(await self._repository.get(task_id))

    async def list(self, **filters) -> tuple[list[dict[str, Any]], int]:
        records, total = await self._repository.list(**filters)
        return [_decorate(record) for record in records], total

    async def cancel(
        self,
        task_id: str,
        cancel_reason: str | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            record = await self._repository.get(task_id)
            if record is None:
                raise KeyError(task_id)
            status = record["status"]
            if status in {"cancelling", "cancelled"}:
                return _decorate(record)
            if status not in {"pending", "running"}:
                raise RuntimeError(f"终态索引任务不可取消: status={status}")
            active = self._active.get(task_id)
            if active is None:
                interrupted = await self._repository.mark_missing_active_task_interrupted(
                    task_id
                )
                return _decorate(interrupted)
            updated = await self._repository.transition(
                task_id,
                ("pending", "running"),
                status="cancelling",
                cancel_reason=cancel_reason,
                heartbeat_at=datetime.now(),
            )
            if updated is None:
                latest = await self._repository.get(task_id)
                if latest is None:
                    raise KeyError(task_id)
                if latest["status"] in {"cancelling", "cancelled"}:
                    return _decorate(latest)
                raise RuntimeError(
                    f"终态索引任务不可取消: status={latest['status']}"
                )
            active.task.cancel()
            return _decorate(updated)

    async def retry(
        self,
        task_id: str,
        *,
        runner: IndexRebuildRunner,
    ) -> dict[str, Any]:
        # 重试创建新记录并保留原任务，批量任务沿用配件级检查点而非图片级断点。
        source = await self._repository.get(task_id)
        if source is None:
            raise KeyError(task_id)
        if source["status"] not in RETRYABLE_STATUSES:
            raise RuntimeError(f"当前索引任务不可重试: status={source['status']}")

        item_id = source.get("item_id")
        record_limit = source.get("item_limit")
        if item_id is not None:
            execution_limit = 1
        elif int(source.get("total_items", 0) or 0) == 0:
            execution_limit = record_limit
        else:
            execution_limit = max(
                int(source["total_items"] or 0)
                - int(source.get("completed_item_count", 0) or 0),
                0,
            )
        if execution_limit == 0:
            raise RuntimeError("索引任务没有剩余配件可重试")

        return await self._start(
            runner=runner,
            item_id=int(item_id) if item_id is not None else None,
            record_limit=execution_limit,
            execution_limit=execution_limit,
            rebuild_existing=bool(source.get("rebuild_existing", False)),
            source=source,
        )


index_rebuild_task_manager = IndexRebuildTaskManager()
