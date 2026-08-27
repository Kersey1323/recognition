import asyncio
from datetime import datetime

import pytest

from csrcqsf.modules.railway_parts.services.index_rebuild_task_manager import (
    IndexRebuildTaskManager,
)


class FakeTaskRepository:
    def __init__(self):
        self.records = {}
        self.progress_updates = []
        self.transition_calls = []
        self.pause_success_update = False
        self.success_update_started = asyncio.Event()
        self.success_update_release = asyncio.Event()

    async def create(self, **values):
        now = datetime.now()
        record = {
            "task_id": values["task_id"],
            "root_task_id": values.get("root_task_id") or values["task_id"],
            "retry_from_task_id": values.get("retry_from_task_id"),
            "task_scope": values["task_scope"],
            "item_id": values.get("item_id"),
            "item_limit": values.get("item_limit"),
            "rebuild_existing": values.get("rebuild_existing", False),
            "status": "pending",
            "progress": values.get("progress", 0),
            "total_items": values.get("total_items", 0),
            "completed_item_count": values.get("completed_item_count", 0),
            "processed_items": values.get("processed_items", 0),
            "success_count": values.get("success_count", 0),
            "fail_count": values.get("fail_count", 0),
            "segmented_count": values.get("segmented_count", 0),
            "fallback_count": values.get("fallback_count", 0),
            "current_item_id": None,
            "last_completed_item_id": values.get("last_completed_item_id"),
            "last_completed_item_created_at": values.get(
                "last_completed_item_created_at"
            ),
            "estimated_remaining_seconds": None,
            "error_message": None,
            "cancel_reason": None,
            "time_created": now,
            "time_updated": now,
        }
        self.records[record["task_id"]] = record
        return dict(record)

    async def update(self, task_id, **values):
        if values.get("status") == "success" and self.pause_success_update:
            self.success_update_started.set()
            await self.success_update_release.wait()
        record = self.records[task_id]
        record.update(values)
        record["time_updated"] = datetime.now()
        if "progress" in values:
            self.progress_updates.append(dict(values))
        return dict(record)

    async def transition(self, task_id, from_statuses, **values):
        self.transition_calls.append(
            (task_id, tuple(from_statuses), dict(values))
        )
        record = self.records[task_id]
        if record["status"] not in set(from_statuses):
            return None
        return await self.update(task_id, **values)

    async def get(self, task_id):
        record = self.records.get(task_id)
        return dict(record) if record is not None else None

    async def list(self, **_filters):
        return [dict(record) for record in self.records.values()], len(self.records)


async def _wait_for_status(manager, task_id, expected):
    for _ in range(50):
        record = await manager.get(task_id)
        if record["status"] == expected:
            return record
        await asyncio.sleep(0)
    raise AssertionError(f"task {task_id} did not reach {expected}")


def test_index_rebuild_task_manager_persists_progress_and_completion():
    async def scenario():
        repository = FakeTaskRepository()
        manager = IndexRebuildTaskManager(repository=repository, max_single_tasks=16)

        async def runner(**kwargs):
            await kwargs["progress_callback"](
                {
                    "progress": 40,
                    "total_items": 10,
                    "completed_item_count": 4,
                    "processed_items": 4,
                    "success_count": 12,
                    "fail_count": 1,
                    "segmented_count": 10,
                    "fallback_count": 2,
                    "current_item_id": 101,
                    "estimated_remaining_seconds": 90,
                }
            )
            return {
                "success_count": 30,
                "fail_count": 2,
                "segmented_count": 25,
                "fallback_count": 5,
            }

        started = await manager.start(
            runner=runner,
            item_id=None,
            limit=10,
            rebuild_existing=False,
        )
        completed = await _wait_for_status(manager, started["task_id"], "success")

        assert isinstance(started["time_created"], str)
        assert repository.progress_updates[0]["completed_item_count"] == 4
        assert any(
            statuses == ("running",) and values.get("status") == "success"
            for _task_id, statuses, values in repository.transition_calls
        )
        assert completed["progress"] == 100
        assert completed["success_count"] == 30
        assert completed["segmented_count"] == 25

    asyncio.run(scenario())


def test_cancel_during_success_write_finishes_as_cancelled():
    async def scenario():
        repository = FakeTaskRepository()
        repository.pause_success_update = True
        manager = IndexRebuildTaskManager(repository=repository)

        async def runner(**_kwargs):
            return {}

        started = await manager.start(
            runner,
            item_id=101,
            limit=1,
            rebuild_existing=False,
        )
        await repository.success_update_started.wait()

        cancelling = await manager.cancel(started["task_id"], "用户取消")
        assert cancelling["status"] == "cancelling"

        cancelled = await _wait_for_status(manager, started["task_id"], "cancelled")
        assert cancelled["cancel_reason"] == "用户取消"

    asyncio.run(scenario())


def test_immediate_cancel_before_runner_starts_releases_slot():
    async def scenario():
        manager = IndexRebuildTaskManager(repository=FakeTaskRepository())

        async def runner(**_kwargs):
            await asyncio.Event().wait()

        started = await manager.start(
            runner,
            item_id=101,
            limit=1,
            rebuild_existing=False,
        )
        await manager.cancel(started["task_id"], "立即取消")

        cancelled = await _wait_for_status(manager, started["task_id"], "cancelled")
        for _ in range(50):
            if started["task_id"] not in manager.active_task_ids:
                break
            await asyncio.sleep(0)

        assert cancelled["cancel_reason"] == "立即取消"
        assert started["task_id"] not in manager.active_task_ids

    asyncio.run(scenario())


def test_index_rebuild_task_manager_allows_sixteen_distinct_single_tasks():
    async def scenario():
        repository = FakeTaskRepository()
        manager = IndexRebuildTaskManager(repository=repository, max_single_tasks=16)
        release = asyncio.Event()

        async def runner(**_kwargs):
            await release.wait()
            return {}

        tasks = [
            await manager.start(runner, item_id=item_id, limit=1, rebuild_existing=False)
            for item_id in range(1, 17)
        ]

        assert len(manager.active_task_ids) == 16
        release.set()
        for task in tasks:
            await _wait_for_status(manager, task["task_id"], "success")

    asyncio.run(scenario())


def test_index_rebuild_task_manager_rejects_seventeenth_single_task():
    async def scenario():
        manager = IndexRebuildTaskManager(
            repository=FakeTaskRepository(),
            max_single_tasks=16,
        )
        release = asyncio.Event()

        async def runner(**_kwargs):
            await release.wait()
            return {}

        for item_id in range(1, 17):
            await manager.start(runner, item_id=item_id, limit=1, rebuild_existing=False)

        with pytest.raises(RuntimeError, match="并发上限"):
            await manager.start(runner, item_id=17, limit=1, rebuild_existing=False)
        release.set()

    asyncio.run(scenario())


def test_try_start_single_uses_available_slot_without_persisting_waiting_task():
    async def scenario():
        repository = FakeTaskRepository()
        manager = IndexRebuildTaskManager(
            repository=repository,
            max_single_tasks=1,
        )
        release = asyncio.Event()

        async def runner(**_kwargs):
            await release.wait()
            return {}

        assert manager.available_single_slots == 1
        first = await manager.try_start_single(runner, item_id=101)

        assert first is not None
        assert manager.available_single_slots == 0
        assert manager.active_single_item_ids == (101,)
        assert await manager.try_start_single(runner, item_id=102) is None
        assert len(repository.records) == 1

        release.set()
        await _wait_for_status(manager, first["task_id"], "success")

    asyncio.run(scenario())


def test_task_completion_notifies_capacity_listener():
    async def scenario():
        manager = IndexRebuildTaskManager(repository=FakeTaskRepository())
        release = asyncio.Event()
        capacity_available = asyncio.Event()
        manager.set_capacity_listener(capacity_available.set)

        async def runner(**_kwargs):
            await release.wait()
            return {}

        started = await manager.start(
            runner,
            item_id=101,
            limit=1,
            rebuild_existing=False,
        )
        release.set()
        await _wait_for_status(manager, started["task_id"], "success")
        await asyncio.wait_for(capacity_available.wait(), timeout=1)

        assert manager.available_single_slots == 16

    asyncio.run(scenario())


def test_index_rebuild_task_manager_rejects_duplicate_active_item():
    async def scenario():
        manager = IndexRebuildTaskManager(repository=FakeTaskRepository())
        release = asyncio.Event()

        async def runner(**_kwargs):
            await release.wait()
            return {}

        await manager.start(runner, item_id=101, limit=1, rebuild_existing=False)
        with pytest.raises(RuntimeError, match="item_id=101"):
            await manager.start(runner, item_id=101, limit=1, rebuild_existing=True)
        release.set()

    asyncio.run(scenario())


def test_index_rebuild_task_manager_enforces_batch_exclusivity():
    async def scenario():
        manager = IndexRebuildTaskManager(repository=FakeTaskRepository())
        release = asyncio.Event()

        async def runner(**_kwargs):
            await release.wait()
            return {}

        single = await manager.start(runner, item_id=101, limit=1, rebuild_existing=False)
        with pytest.raises(RuntimeError, match="不能并行"):
            await manager.start(runner, item_id=None, limit=500, rebuild_existing=False)
        release.set()
        await _wait_for_status(manager, single["task_id"], "success")

        batch = await manager.start(runner, item_id=None, limit=500, rebuild_existing=False)
        with pytest.raises(RuntimeError, match="不能并行"):
            await manager.start(runner, item_id=102, limit=1, rebuild_existing=False)
        release.set()
        await _wait_for_status(manager, batch["task_id"], "success")

    asyncio.run(scenario())


def test_cancel_keeps_slot_until_runner_exits():
    async def scenario():
        manager = IndexRebuildTaskManager(repository=FakeTaskRepository())
        running = asyncio.Event()
        cleanup_release = asyncio.Event()

        async def runner(**_kwargs):
            running.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await cleanup_release.wait()
                raise

        started = await manager.start(runner, item_id=101, limit=1, rebuild_existing=False)
        await running.wait()
        cancelling = await manager.cancel(started["task_id"], "用户取消")

        assert cancelling["status"] == "cancelling"
        with pytest.raises(RuntimeError, match="item_id=101"):
            await manager.start(runner, item_id=101, limit=1, rebuild_existing=False)

        cleanup_release.set()
        cancelled = await _wait_for_status(manager, started["task_id"], "cancelled")
        assert cancelled["cancel_reason"] == "用户取消"

    asyncio.run(scenario())


def test_retry_copies_checkpoint_and_uses_remaining_limit():
    async def scenario():
        repository = FakeTaskRepository()
        source = await repository.create(
            task_id="source-task",
            root_task_id="root-task",
            retry_from_task_id=None,
            task_scope="batch",
            item_id=None,
            item_limit=10,
            rebuild_existing=True,
            progress=40,
            total_items=10,
            completed_item_count=4,
            processed_items=4,
            success_count=12,
            fail_count=1,
            segmented_count=9,
            fallback_count=3,
            last_completed_item_id=1004,
            last_completed_item_created_at=datetime(2026, 8, 1, 10, 0, 0),
        )
        await repository.update(source["task_id"], status="interrupted")
        manager = IndexRebuildTaskManager(repository=repository)
        received = {}

        async def runner(**kwargs):
            received.update(kwargs)
            return {
                "success_count": kwargs["initial_success_count"],
                "fail_count": kwargs["initial_fail_count"],
                "segmented_count": kwargs["initial_segmented_count"],
                "fallback_count": kwargs["initial_fallback_count"],
            }

        retried = await manager.retry("source-task", runner=runner)
        await _wait_for_status(manager, retried["task_id"], "success")

        assert retried["task_id"] != "source-task"
        assert retried["root_task_id"] == "root-task"
        assert retried["retry_from_task_id"] == "source-task"
        assert retried["item_limit"] == 6
        assert received["limit"] == 6
        assert received["initial_completed_item_count"] == 4
        assert received["total_items_override"] == 10
        assert received["resume_after_item_id"] == 1004

    asyncio.run(scenario())
