"""SGO synchronization task lifecycle management."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any, Awaitable, Callable
from uuid import uuid4


logger = logging.getLogger(__name__)
SgoSyncRunner = Callable[..., Awaitable[dict[str, Any]]]


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


class SgoSyncTaskManager:
    """Keep one SGO synchronization alive and expose process-local progress."""

    def __init__(self, max_history: int = 100) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._running_tasks: set[asyncio.Task[Any]] = set()
        self._max_history = max_history

    def start(
        self,
        task_type: str,
        runner: SgoSyncRunner,
        **runner_kwargs: Any,
    ) -> dict[str, Any]:
        active = next(
            (
                state
                for state in self._tasks.values()
                if state["status"] in {"pending", "running"}
            ),
            None,
        )
        if active is not None:
            raise RuntimeError(f"已有 SGO 同步任务正在执行: task_id={active['task_id']}")

        self._trim_history()
        task_id = str(uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        self._tasks[task_id] = {
            "task_id": task_id,
            "task_type": task_type,
            "status": "pending",
            "progress": 0,
            "total_items": 0,
            "processed_items": 0,
            "success_count": 0,
            "fail_count": 0,
            "created_count": 0,
            "skipped_count": 0,
            "synced_image_count": 0,
            "current_item_id": None,
            "estimated_remaining_seconds": None,
            "estimated_remaining": None,
            "failed_item_ids": [],
            "error_message": None,
            "time_created": now,
            "time_updated": now,
        }
        task = asyncio.create_task(
            self._run(task_id, runner, runner_kwargs),
            name=f"sgo-{task_type}-sync-{task_id}",
        )
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)
        return dict(self._tasks[task_id])

    def get(self, task_id: str) -> dict[str, Any] | None:
        state = self._tasks.get(task_id)
        return dict(state) if state is not None else None

    def _update_progress(self, task_id: str, progress: dict[str, Any]) -> None:
        state = self._tasks[task_id]
        for field in (
            "progress",
            "total_items",
            "processed_items",
            "success_count",
            "fail_count",
            "created_count",
            "skipped_count",
            "synced_image_count",
            "estimated_remaining_seconds",
            "failed_item_ids",
        ):
            if field in progress:
                state[field] = progress[field]
        if "current_item_id" in progress:
            value = progress["current_item_id"]
            state["current_item_id"] = str(value) if value is not None else None
        state["estimated_remaining"] = _format_remaining(
            state["estimated_remaining_seconds"]
        )
        state["time_updated"] = datetime.now().isoformat(timespec="seconds")

    async def _run(
        self,
        task_id: str,
        runner: SgoSyncRunner,
        runner_kwargs: dict[str, Any],
    ) -> None:
        state = self._tasks[task_id]
        state.update(
            status="running",
            time_updated=datetime.now().isoformat(timespec="seconds"),
        )
        try:
            result = await runner(
                **runner_kwargs,
                progress_callback=lambda progress: self._update_progress(task_id, progress),
            )
        except asyncio.CancelledError:
            state.update(
                status="cancelled",
                error_message="服务停止，SGO 同步任务已取消",
                estimated_remaining_seconds=None,
                estimated_remaining=None,
                time_updated=datetime.now().isoformat(timespec="seconds"),
            )
            raise
        except Exception as exc:
            logger.exception("SGO synchronization failed: task_id=%s", task_id)
            state.update(
                status="failed",
                error_message=str(exc),
                estimated_remaining_seconds=None,
                estimated_remaining=None,
                time_updated=datetime.now().isoformat(timespec="seconds"),
            )
        else:
            for field in (
                "total_items",
                "processed_items",
                "success_count",
                "fail_count",
                "created_count",
                "skipped_count",
                "synced_image_count",
                "failed_item_ids",
            ):
                if field in result:
                    state[field] = result[field]
            state.update(
                status="success",
                progress=100,
                current_item_id=None,
                estimated_remaining_seconds=0,
                estimated_remaining="已完成",
                time_updated=datetime.now().isoformat(timespec="seconds"),
            )

    def _trim_history(self) -> None:
        completed_ids = [
            task_id
            for task_id, state in self._tasks.items()
            if state["status"] not in {"pending", "running"}
        ]
        overflow = len(self._tasks) - self._max_history + 1
        for task_id in completed_ids[:max(0, overflow)]:
            self._tasks.pop(task_id, None)


sgo_sync_task_manager = SgoSyncTaskManager()
