import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime

import pytest

from csrcqsf.modules.sgo.sync_task_manager import SgoSyncTaskManager


ACTIVE = {"pending", "running", "cancelling"}


class FakeSgoSyncTaskRepository:
    def __init__(self):
        self.records = {}
        self.failures = {}

    async def create(self, **values):
        now = datetime.now()
        record = {
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
            "heartbeat_at": None,
            "started_at": None,
            "completed_at": None,
            "error_message": None,
            "cancel_reason": None,
            "time_created": now,
            "time_updated": now,
            **values,
        }
        self.records[record["task_id"]] = record
        return deepcopy(record)

    async def get(self, task_id):
        record = self.records.get(task_id)
        return deepcopy(record) if record else None

    async def has_active(self):
        return any(record["status"] in ACTIVE for record in self.records.values())

    async def update(self, task_id, **values):
        record = self.records.get(task_id)
        if record is None:
            return None
        record.update(values, time_updated=datetime.now())
        return deepcopy(record)

    async def transition(self, task_id, from_statuses, **values):
        record = self.records.get(task_id)
        if record is None or record["status"] not in from_statuses:
            return None
        record.update(values, time_updated=datetime.now())
        return deepcopy(record)

    async def replace_failures(self, task_id, failures):
        self.failures[task_id] = deepcopy(failures)

    async def append_failures(self, task_id, failures):
        self.failures.setdefault(task_id, []).extend(deepcopy(failures))

    async def list(self, **_filters):
        records = sorted(
            self.records.values(),
            key=lambda item: item["time_created"],
            reverse=True,
        )
        return [deepcopy(item) for item in records], len(records)

    async def count_by_status(self, task_type):
        return dict(Counter(
            record["status"]
            for record in self.records.values()
            if record["task_type"] == task_type
        ))

    async def list_failures(
        self,
        task_id,
        *,
        page,
        per_page,
        stage=None,
        error_type=None,
        error_message=None,
        error_code=None,
    ):
        records = self.failures.get(task_id, [])
        if stage is not None:
            records = [record for record in records if record["stage"] == stage]
        if error_type is not None:
            records = [
                record for record in records if record["error_type"] == error_type
            ]
        if error_message is not None:
            records = [
                record
                for record in records
                if record["error_message"] == error_message
            ]
        if error_code is not None:
            records = [record for record in records if record.get("error_code") == error_code]
        start = (page - 1) * per_page
        return deepcopy(records[start : start + per_page]), len(records)

    async def summarize_failures(self, task_id):
        counts = Counter(
            (
                failure.get("error_code"),
            )
            for failure in self.failures.get(task_id, [])
        )
        return [
            {
                "error_code": error_code,
                "stage": next(row["stage"] for row in self.failures[task_id] if row.get("error_code") == error_code),
                "error_type": next(row["error_type"] for row in self.failures[task_id] if row.get("error_code") == error_code),
                "error_message": next(row["error_message"] for row in self.failures[task_id] if row.get("error_code") == error_code),
                "count": count,
            }
            for (error_code,), count in counts.items()
        ]

    async def mark_missing_active_task_interrupted(self, task_id):
        return await self.update(
            task_id,
            status="interrupted",
            current_item_id=None,
            error_message="活动任务在当前服务进程中不存在",
        )

    async def delete_tasks(self, task_ids):
        records = [self.records[task_id] for task_id in task_ids if task_id in self.records]
        active = sorted(record["task_id"] for record in records if record["status"] in ACTIVE)
        if active:
            raise RuntimeError(f"运行中的 SGO 同步任务不可删除: task_id={','.join(active)}")
        deleted_failure_count = sum(len(self.failures.get(task_id, [])) for task_id in task_ids)
        deleted_task_count = 0
        for task_id in task_ids:
            if self.records.pop(task_id, None) is not None:
                deleted_task_count += 1
            self.failures.pop(task_id, None)
        return {
            "requested_count": len(task_ids),
            "deleted_task_count": deleted_task_count,
            "deleted_failure_count": deleted_failure_count,
            "missing_task_ids": sorted(set(task_ids) - {record["task_id"] for record in records}),
        }


async def wait_terminal(manager, task_id):
    for _ in range(50):
        await asyncio.sleep(0)
        record = await manager.get(task_id)
        if record["status"] not in ACTIVE:
            return record
    raise AssertionError("任务未进入终态")


def test_sync_task_statistics_count_statuses_by_type():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        for index, status in enumerate(
            ["success", "success", "failed", "pending", "running", "cancelling", "cancelled", "interrupted"]
        ):
            await repository.create(task_id=f"parts-{index}", task_type="parts", status=status)
        await repository.create(task_id="images-1", task_type="images", status="success")

        assert await manager.statistics("parts") == {
            "task_success_rate": 25,
            "total_tasks": 8,
            "successful_tasks": 2,
            "failed_tasks": 1,
            "active_tasks": 3,
        }
        assert await manager.statistics("images") == {
            "task_success_rate": 100,
            "total_tasks": 1,
            "successful_tasks": 1,
            "failed_tasks": 0,
            "active_tasks": 0,
        }
        assert (await manager.statistics("inquiry-history"))["task_success_rate"] == 0

        for index in range(200):
            await repository.create(
                task_id=f"inquiry-{index}",
                task_type="inquiry-history",
                status="success" if index == 0 else "cancelled",
            )
        assert (await manager.statistics("inquiry-history"))["task_success_rate"] == 1

    asyncio.run(scenario())


def test_sgo_sync_task_manager_persists_progress_and_completion():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        progress_written = asyncio.Event()
        finish = asyncio.Event()

        async def runner(**kwargs):
            await kwargs["progress_callback"](
                {
                    "progress": 50,
                    "total_items": 2,
                    "processed_items": 1,
                    "success_count": 1,
                    "created_count": 1,
                    "current_item_id": "101",
                    "estimated_remaining_seconds": 9,
                }
            )
            progress_written.set()
            await finish.wait()
            return {
                "total_items": 2,
                "processed_items": 2,
                "success_count": 2,
                "fail_count": 0,
                "created_count": 2,
                "skipped_count": 0,
                "synced_image_count": 0,
                "updated_metadata_count": 3,
                "synced_supplier_count": 4,
                "deleted_supplier_count": 1,
                "unmatched_supplier_count": 2,
                "hierarchy_total_count": 10,
                "synced_hierarchy_count": 5,
                "deleted_hierarchy_count": 1,
                "unresolved_vehicle_count": 2,
                "invalid_hierarchy_count": 3,
                "failure_details": [],
            }

        started = await manager.start("parts", runner)
        await progress_written.wait()
        running = await manager.get(started["task_id"])
        assert running["progress"] == 50
        assert running["estimated_remaining"] == "约9秒"

        finish.set()
        completed = await wait_terminal(manager, started["task_id"])
        assert completed["status"] == "success"
        assert completed["created_count"] == 2
        assert completed["updated_metadata_count"] == 3
        assert completed["synced_supplier_count"] == 4
        assert completed["deleted_supplier_count"] == 1
        assert completed["unmatched_supplier_count"] == 2
        assert completed["hierarchy_total_count"] == 10
        assert completed["synced_hierarchy_count"] == 5
        assert completed["deleted_hierarchy_count"] == 1
        assert completed["unresolved_vehicle_count"] == 2
        assert completed["invalid_hierarchy_count"] == 3
        assert completed["progress"] == 100

    asyncio.run(scenario())


def test_inquiry_sync_receives_task_id_and_persists_semantic_follow_up():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        received = {}

        async def runner(**kwargs):
            received.update(kwargs)
            return {
                "total_items": 1,
                "processed_items": 1,
                "success_count": 1,
                "fail_count": 0,
                "created_count": 1,
                "skipped_count": 0,
                "synced_image_count": 0,
                "failure_details": [],
                "semantic_index_triggered": True,
                "semantic_index_task_id": "semantic-1",
                "semantic_index_warning": None,
            }

        started = await manager.start("inquiry-history", runner)
        completed = await wait_terminal(manager, started["task_id"])

        assert received["_sync_task_id"] == started["task_id"]
        assert completed["status"] == "success"
        assert completed["semantic_index_triggered"] is True
        assert completed["semantic_index_task_id"] == "semantic-1"

    asyncio.run(scenario())


def test_sgo_sync_task_manager_appends_incremental_failures_without_replacing_them():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        failures = [
            {
                "item_id": "101",
                "error_code": "SGO_DOWNLOAD_FAILED",
                "stage": "sgo_download",
                "error_type": "TimeoutError",
                "error_message": "download timeout",
            },
            {
                "item_id": "102",
                "error_code": "MINIO_UPLOAD_FAILED",
                "stage": "minio_upload",
                "error_type": "RuntimeError",
                "error_message": "upload failed",
            },
        ]

        async def runner(**kwargs):
            await kwargs["progress_callback"](
                {"processed_items": 1, "new_failure_details": [failures[0]]}
            )
            await kwargs["progress_callback"](
                {"processed_items": 2, "new_failure_details": [failures[1]]}
            )
            return {
                "total_items": 3,
                "processed_items": 3,
                "success_count": 1,
                "fail_count": 2,
                "created_count": 0,
                "skipped_count": 0,
                "synced_image_count": 0,
                "failure_details": [failures[0]],
                "failures_persisted_incrementally": True,
            }

        started = await manager.start("images", runner, sync_scope="all", item_id_list=[])
        completed = await wait_terminal(manager, started["task_id"])

        assert completed["status"] == "success"
        assert repository.failures[started["task_id"]] == failures

    asyncio.run(scenario())


def test_sgo_sync_task_manager_rejects_global_parallel_task():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        release = asyncio.Event()

        async def runner(**_kwargs):
            await release.wait()
            return {"total_items": 0, "processed_items": 0}

        first = await manager.start("parts", runner)
        with pytest.raises(RuntimeError, match=first["task_id"]):
            await manager.start("images", runner, item_id_list=["101"])
        release.set()
        await wait_terminal(manager, first["task_id"])

    asyncio.run(scenario())


def test_sgo_sync_task_manager_marks_only_total_failure_as_failed():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)

        async def partial_runner(**_kwargs):
            return {
                "total_items": 10,
                "processed_items": 10,
                "success_count": 0,
                "fail_count": 2,
                "created_count": 0,
                "skipped_count": 8,
                "synced_image_count": 0,
                "failure_details": [
                    {
                        "item_id": "109",
                        "stage": "source_validation",
                        "error_type": "InvalidSourceData",
                        "error_message": "配件名称为空",
                    }
                ],
            }

        async def failed_runner(**_kwargs):
            return {
                "total_items": 2,
                "processed_items": 2,
                "success_count": 0,
                "fail_count": 2,
                "created_count": 0,
                "skipped_count": 0,
                "synced_image_count": 0,
                "failure_details": [
                    {
                        "item_id": "101",
                        "stage": "base_images",
                        "error_type": "RuntimeError",
                        "error_message": "download failed",
                    }
                ],
            }

        partial = await manager.start("parts", partial_runner)
        partial_done = await wait_terminal(manager, partial["task_id"])
        assert partial_done["status"] == "success"
        assert "配件名称为空" in partial_done["error_message"]
        assert len(repository.failures[partial["task_id"]]) == 1

        failed = await manager.start("images", failed_runner, item_id_list=["101", "102"])
        failed_done = await wait_terminal(manager, failed["task_id"])
        assert failed_done["status"] == "failed"
        assert "全部 2 个配件同步失败" in failed_done["error_message"]

    asyncio.run(scenario())


def test_sgo_sync_task_manager_detail_keeps_bounded_failure_compatibility():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        record = await repository.create(
            task_id="failed-task",
            root_task_id="failed-task",
            retry_from_task_id=None,
            task_type="images",
            task_params_json={"item_id_list": ["101", "102"]},
            status="failed",
            fail_count=2,
        )
        repository.failures[record["task_id"]] = [
                {
                    "item_id": str(item_id),
                    "error_code": "BASE_IMAGE_METADATA_INVALID",
                    "stage": "base_images",
                "error_type": "RuntimeError",
                "error_message": "download failed",
            }
            for item_id in range(25)
        ]

        detail = await manager.get(record["task_id"])

        assert len(detail["failure_details"]) == 20
        assert detail["failed_item_ids"] == [str(item_id) for item_id in range(20)]
        assert detail["failure_groups"] == [
            {
                "error_code": "BASE_IMAGE_METADATA_INVALID",
                "stage": "base_images",
                "error_type": "RuntimeError",
                "error_message": "download failed",
                "count": 25,
            }
        ]

        records, total = await manager.list_failures(
            record["task_id"],
            page=1,
            per_page=10,
            stage="base_images",
            error_type="RuntimeError",
            error_message="download failed",
            error_code="BASE_IMAGE_METADATA_INVALID",
        )
        assert len(records) == 10
        assert total == 25

        repository.failures[record["task_id"]].append({
            "item_id": "extra", "error_code": "BASE_IMAGE_METADATA_INVALID",
            "stage": "base_images", "error_type": "ValueError",
            "error_message": "another message",
        })
        updated = await manager.get(record["task_id"])
        assert len(updated["failure_groups"]) == 1
        assert updated["failure_groups"][0]["count"] == 26

    asyncio.run(scenario())


def test_sgo_sync_task_manager_cancels_running_task():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        started_event = asyncio.Event()

        async def runner(**_kwargs):
            started_event.set()
            await asyncio.Event().wait()

        started = await manager.start("parts", runner)
        await started_event.wait()
        cancelling = await manager.cancel(started["task_id"], "用户停止")
        assert cancelling["status"] == "cancelling"
        completed = await wait_terminal(manager, started["task_id"])
        assert completed["status"] == "cancelled"
        assert completed["cancel_reason"] == "用户停止"

    asyncio.run(scenario())


def test_sgo_sync_task_manager_cancels_pending_task_before_runner_starts():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)

        async def runner(**_kwargs):
            await asyncio.Event().wait()

        started = await manager.start("parts", runner)
        await manager.cancel(started["task_id"], "提交后立即取消")

        completed = await wait_terminal(manager, started["task_id"])
        assert completed["status"] == "cancelled"
        assert completed["cancel_reason"] == "提交后立即取消"

        next_task = await manager.start("parts", runner)
        await manager.cancel(next_task["task_id"])
        await wait_terminal(manager, next_task["task_id"])

    asyncio.run(scenario())


def test_sgo_sync_task_manager_retries_with_original_parameters():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        calls = []

        async def runner(**kwargs):
            calls.append(kwargs["item_id_list"])
            return {
                "total_items": 1,
                "processed_items": 1,
                "success_count": 1,
                "fail_count": 0,
                "created_count": 0,
                "skipped_count": 1,
                "synced_image_count": 0,
                "failure_details": [],
            }

        manager = SgoSyncTaskManager(
            repository=repository,
            runner_resolver=lambda _task_type: runner,
        )
        original = await repository.create(
            task_id="old-task",
            root_task_id="root-task",
            retry_from_task_id=None,
            task_type="images",
            task_params_json={"item_id_list": ["101"]},
            status="interrupted",
        )

        retried = await manager.retry(original["task_id"])
        assert retried["root_task_id"] == "root-task"
        assert retried["retry_from_task_id"] == "old-task"
        await wait_terminal(manager, retried["task_id"])
        assert calls == [["101"]]

    asyncio.run(scenario())


def test_sgo_sync_task_manager_deletes_terminal_tasks_and_failure_details():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        for task_id, status in (("done-1", "success"), ("done-2", "failed")):
            await repository.create(
                task_id=task_id,
                root_task_id=task_id,
                retry_from_task_id=None,
                task_type="parts",
                task_params_json={},
                status=status,
            )
            repository.failures[task_id] = [{"item_id": task_id}]

        result = await manager.delete_tasks(["done-1", "done-2", "missing"])

        assert result == {
            "requested_count": 3,
            "deleted_task_count": 2,
            "deleted_failure_count": 2,
            "missing_task_ids": ["missing"],
        }
        assert repository.records == {}
        assert repository.failures == {}

    asyncio.run(scenario())


def test_sgo_sync_task_manager_rejects_batch_containing_active_task():
    async def scenario():
        repository = FakeSgoSyncTaskRepository()
        manager = SgoSyncTaskManager(repository=repository)
        for task_id, status in (("done", "success"), ("active", "running")):
            await repository.create(
                task_id=task_id,
                root_task_id=task_id,
                retry_from_task_id=None,
                task_type="parts",
                task_params_json={},
                status=status,
            )

        with pytest.raises(RuntimeError, match="运行中的 SGO 同步任务不可删除"):
            await manager.delete_tasks(["done", "active"])

        assert set(repository.records) == {"done", "active"}

    asyncio.run(scenario())
