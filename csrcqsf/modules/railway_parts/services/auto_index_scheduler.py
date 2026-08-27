"""Periodic scheduling for unindexed part images."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from csrcqsf.core.logging_config import logger
from csrcqsf.core.settings import index_auto_scan_interval_seconds
from csrcqsf.modules.railway_parts.repositories.auto_index_repository import (
    AutoIndexRepository,
)
from csrcqsf.modules.railway_parts.services.index_rebuild_task_manager import (
    IndexRebuildTaskManager,
    index_rebuild_task_manager,
)


IndexRunner = Callable[..., Awaitable[dict[str, Any]]]


class AutoIndexScheduler:
    def __init__(
        self,
        *,
        repository=None,
        manager: IndexRebuildTaskManager | None = None,
        scan_interval_seconds: float | None = None,
    ) -> None:
        self._repository = repository or AutoIndexRepository()
        self._manager = manager or index_rebuild_task_manager
        self._scan_interval_seconds = float(
            scan_interval_seconds
            if scan_interval_seconds is not None
            else index_auto_scan_interval_seconds
        )
        if self._scan_interval_seconds <= 0:
            raise ValueError("自动索引扫描间隔必须大于0")
        self._wake_event: asyncio.Event | None = None
        self._runner: IndexRunner | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def wake(self) -> None:
        if self._wake_event is not None:
            self._wake_event.set()

    async def start(self, runner: IndexRunner) -> None:
        self._runner = runner
        if self.is_running:
            self.wake()
            return
        self._stopping = False
        self._wake_event = asyncio.Event()
        self._manager.set_capacity_listener(self.wake)
        self._task = asyncio.create_task(
            self._run_loop(),
            name="self-collected-image-auto-index",
        )
        self.wake()

    async def stop(self) -> None:
        task = self._task
        self._manager.set_capacity_listener(None)
        if task is None:
            return
        self._stopping = True
        self.wake()
        try:
            await task
        finally:
            self._task = None
            self._runner = None
            self._wake_event = None

    async def scan_once(self) -> int:
        runner = self._runner
        if runner is None:
            raise RuntimeError("自动索引扫描器尚未绑定索引执行器")

        available_slots = self._manager.available_single_slots
        if available_slots <= 0:
            return 0
        item_ids = await self._repository.list_candidate_item_ids(
            limit=available_slots,
            excluded_item_ids=self._manager.active_single_item_ids,
        )

        started_count = 0
        for item_id in item_ids:
            task = await self._manager.try_start_single(
                runner,
                item_id=int(item_id),
            )
            if task is None:
                # A manual request may consume capacity after candidate lookup.
                # The next completion or timer tick will rescan the remaining rows.
                break
            started_count += 1
        if started_count:
            logger.info("待索引图片自动索引已提交 {} 个配件任务", started_count)
        return started_count

    async def _run_loop(self) -> None:
        wake_event = self._wake_event
        if wake_event is None:
            return
        while not self._stopping:
            try:
                await asyncio.wait_for(
                    wake_event.wait(),
                    timeout=self._scan_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
            wake_event.clear()
            if self._stopping:
                break

            try:
                await self.scan_once()
            except Exception:
                # 单次候选查询失败不能终止后续定时扫描。
                logger.exception("待索引图片自动索引扫描失败")


auto_index_scheduler = AutoIndexScheduler()
