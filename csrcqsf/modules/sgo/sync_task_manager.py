"""Persistent lifecycle management for SGO synchronization tasks."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import logging
from typing import Any, Awaitable, Callable
from uuid import uuid4

from csrcqsf.modules.sgo.sync_task_repository import SgoSyncTaskRepository


logger = logging.getLogger(__name__)
SgoSyncRunner = Callable[..., Awaitable[dict[str, Any]]]
RunnerResolver = Callable[[str], SgoSyncRunner]
ACTIVE_STATUSES = ("pending", "running", "cancelling")
RETRYABLE_STATUSES = {"failed", "cancelled", "interrupted"}
DETAIL_FAILURE_LIMIT = 20
PROGRESS_FIELDS = (
    "progress",
    "total_items",
    "processed_items",
    "success_count",
    "fail_count",
    "created_count",
    "skipped_count",
    "synced_image_count",
    "estimated_remaining_seconds",
)


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


def _default_runner_resolver(task_type: str) -> SgoSyncRunner:
    from csrcqsf.modules.sgo.services import SGOBiz

    runners = {
        "parts": SGOBiz.sync_parts_items,
        "images": SGOBiz.sync_images,
        "inquiry-history": SGOBiz.sync_inquiry_history,
    }
    try:
        return runners[task_type]
    except KeyError as exc:
        raise ValueError(f"不支持的 SGO 同步任务类型: {task_type}") from exc


class SgoSyncTaskManager:
    """Run one in-process SGO task while persisting its complete lifecycle."""

    def __init__(
        self,
        repository=None,
        runner_resolver: RunnerResolver | None = None,
    ) -> None:
        self._repository = repository or SgoSyncTaskRepository()
        self._runner_resolver = runner_resolver or _default_runner_resolver
        self._active: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        task_type: str,
        runner: SgoSyncRunner,
        **runner_kwargs: Any,
    ) -> dict[str, Any]:
        return await self._start(
            task_type=task_type,
            runner=runner,
            runner_kwargs=runner_kwargs,
        )

    async def _start(
        self,
        *,
        task_type: str,
        runner: SgoSyncRunner,
        runner_kwargs: dict[str, Any],
        source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            active_task_id = next(iter(self._active), None)
            if active_task_id is not None:
                raise RuntimeError(
                    f"已有 SGO 同步任务正在执行: task_id={active_task_id}"
                )
            if await self._repository.has_active():
                raise RuntimeError("数据库中存在未结束的 SGO 同步任务")

            task_id = str(uuid4())
            source = source or {}
            record = await self._repository.create(
                task_id=task_id,
                root_task_id=source.get("root_task_id") or task_id,
                retry_from_task_id=source.get("task_id"),
                task_type=task_type,
                task_params_json=deepcopy(runner_kwargs),
                status="pending",
            )
            task = asyncio.create_task(
                self._run(task_id, runner, deepcopy(runner_kwargs)),
                name=f"sgo-{task_type}-sync-{task_id}",
            )
            self._active[task_id] = task
            task.add_done_callback(
                lambda completed_task: asyncio.create_task(
                    self._cleanup_finished_task(task_id, completed_task)
                )
            )
            return _decorate(record)

    async def _cleanup_finished_task(
        self,
        task_id: str,
        task: asyncio.Task[Any],
    ) -> None:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("SGO task cleanup observed an unexpected error: task_id=%s", task_id)

        # 提交后立即取消时，协程可能尚未进入 _run，需在完成回调中补齐终态。
        record = await self._repository.get(task_id)
        if record is not None and record["status"] == "cancelling":
            await self._mark_cancelled(task_id)
        async with self._lock:
            if self._active.get(task_id) is task:
                self._active.pop(task_id, None)

    async def _run(
        self,
        task_id: str,
        runner: SgoSyncRunner,
        runner_kwargs: dict[str, Any],
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
            self._active.pop(task_id, None)
            return

        async def persist_progress(progress: dict[str, Any]) -> None:
            values = {
                field: progress[field]
                for field in PROGRESS_FIELDS
                if field in progress
            }
            if "current_item_id" in progress:
                current = progress["current_item_id"]
                values["current_item_id"] = str(current) if current is not None else None
            values["heartbeat_at"] = datetime.now()
            await self._repository.update(task_id, **values)
            if "new_failure_details" in progress:
                await self._repository.append_failures(
                    task_id,
                    list(progress["new_failure_details"]),
                )
            if "failure_details" in progress:
                await self._repository.replace_failures(
                    task_id,
                    list(progress["failure_details"]),
                )

        try:
            result = await runner(
                **runner_kwargs,
                progress_callback=persist_progress,
            )
            failures = list(result.get("failure_details") or [])
            if not result.get("failures_persisted_incrementally"):
                await self._repository.replace_failures(task_id, failures)
            fail_count = int(result.get("fail_count", 0) or 0)
            processed_items = int(result.get("processed_items", 0) or 0)
            all_failed = (
                fail_count > 0
                and processed_items > 0
                and fail_count >= processed_items
            )
            error_message = self._build_error_message(
                fail_count=fail_count,
                all_failed=all_failed,
                failures=failures,
            )
            values = {
                field: result[field]
                for field in PROGRESS_FIELDS
                if field in result
            }
            values.update(
                status="failed" if all_failed else "success",
                progress=100,
                current_item_id=None,
                completed_at=datetime.now(),
                heartbeat_at=datetime.now(),
                estimated_remaining_seconds=0,
                error_message=error_message,
            )
            completed = await self._repository.transition(
                task_id,
                ("running",),
                **values,
            )
            if completed is None:
                current = await self._repository.get(task_id) or {}
                if current.get("status") == "cancelling":
                    await self._mark_cancelled(task_id)
        except asyncio.CancelledError:
            await self._mark_cancelled(task_id)
            raise
        except Exception as exc:
            logger.exception("SGO synchronization failed: task_id=%s", task_id)
            await self._repository.transition(
                task_id,
                ("pending", "running"),
                status="failed",
                current_item_id=None,
                completed_at=datetime.now(),
                heartbeat_at=datetime.now(),
                error_message=str(exc) or repr(exc),
                estimated_remaining_seconds=None,
            )
        finally:
            async with self._lock:
                self._active.pop(task_id, None)

    @staticmethod
    def _build_error_message(
        *,
        fail_count: int,
        all_failed: bool,
        failures: list[dict],
    ) -> str | None:
        if not fail_count:
            return None
        first_error = ""
        if failures:
            first = failures[0]
            first_error = (
                f"；首个错误 [{first['stage']}] "
                f"{first['error_type']}: {first['error_message']}"
            )
        prefix = "全部 " if all_failed else ""
        return f"{prefix}{fail_count} 个配件同步失败{first_error}"

    async def _mark_cancelled(self, task_id: str) -> None:
        await self._repository.transition(
            task_id,
            ("pending", "running", "cancelling"),
            status="cancelled",
            current_item_id=None,
            completed_at=datetime.now(),
            heartbeat_at=datetime.now(),
            estimated_remaining_seconds=None,
        )

    async def get(self, task_id: str) -> dict[str, Any] | None:
        record = await self._repository.get(task_id)
        detail = _decorate(record)
        if detail is None:
            return None

        # 详情保留旧接口的失败字段，但只返回首批记录，完整明细由分页接口承载。
        failures = []
        if detail.get("fail_count"):
            failures, _ = await self._repository.list_failures(
                task_id,
                page=1,
                per_page=DETAIL_FAILURE_LIMIT,
            )
        detail["failure_details"] = failures
        detail["failed_item_ids"] = [failure["item_id"] for failure in failures]
        return detail

    async def list(self, **filters) -> tuple[list[dict[str, Any]], int]:
        records, total = await self._repository.list(**filters)
        return [_decorate(record) for record in records], total

    async def list_failures(
        self,
        task_id: str,
        *,
        page: int,
        per_page: int,
    ) -> tuple[list[dict[str, Any]], int]:
        return await self._repository.list_failures(
            task_id,
            page=page,
            per_page=per_page,
        )

    async def cancel(
        self,
        task_id: str,
        cancel_reason: str | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            record = await self._repository.get(task_id)
            if record is None:
                raise KeyError(task_id)
            if record["status"] in {"cancelling", "cancelled"}:
                return _decorate(record)
            if record["status"] not in {"pending", "running"}:
                raise RuntimeError(
                    f"终态 SGO 同步任务不可取消: status={record['status']}"
                )
            task = self._active.get(task_id)
            if task is None:
                interrupted = (
                    await self._repository.mark_missing_active_task_interrupted(task_id)
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
                return _decorate(latest)
            task.cancel()
            return _decorate(updated)

    async def retry(self, task_id: str) -> dict[str, Any]:
        source = await self._repository.get(task_id)
        if source is None:
            raise KeyError(task_id)
        if source["status"] not in RETRYABLE_STATUSES:
            raise RuntimeError(
                f"当前 SGO 同步任务状态不可重试: status={source['status']}"
            )
        runner = self._runner_resolver(source["task_type"])
        return await self._start(
            task_type=source["task_type"],
            runner=runner,
            runner_kwargs=deepcopy(source.get("task_params_json") or {}),
            source=source,
        )


sgo_sync_task_manager = SgoSyncTaskManager()
