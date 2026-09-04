import asyncio
from copy import deepcopy
from datetime import datetime


ACTIVE = {"pending", "running", "cancelling"}


class FakeRepository:
    def __init__(self):
        self.records = {}
        self.failures = {}

    async def create(self, **values):
        now = datetime.now()
        record = {
            "progress": 0,
            "total_items": 0,
            "processed_items": 0,
            "indexed_count": 0,
            "skipped_count": 0,
            "fail_count": 0,
            "deleted_count": 0,
            "current_inquiry_id": None,
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
        return deepcopy(self.records.get(task_id))

    async def update(self, task_id, **values):
        self.records[task_id].update(values, time_updated=datetime.now())
        return deepcopy(self.records[task_id])

    async def transition(self, task_id, from_statuses, **values):
        record = self.records.get(task_id)
        if record is None or record["status"] not in from_statuses:
            return None
        record.update(values, time_updated=datetime.now())
        return deepcopy(record)

    async def claim_next_pending(self):
        pending = [record for record in self.records.values() if record["status"] == "pending"]
        if not pending:
            return None
        record = sorted(pending, key=lambda item: item["time_created"])[0]
        record.update(status="running", started_at=datetime.now(), heartbeat_at=datetime.now())
        return deepcopy(record)

    async def list(self, **_filters):
        records = list(self.records.values())
        return [deepcopy(record) for record in records], len(records)

    async def append_failures(self, task_id, failures):
        self.failures.setdefault(task_id, []).extend(deepcopy(failures))

    async def replace_failures(self, task_id, failures):
        self.failures[task_id] = deepcopy(failures)

    async def list_failures(self, task_id, *, page, per_page):
        rows = self.failures.get(task_id, [])
        start = (page - 1) * per_page
        return deepcopy(rows[start : start + per_page]), len(rows)

    async def summarize_failure_types(self, task_id, *, limit=3):
        rows = self.failures.get(task_id, [])
        order = []
        counts = {}
        samples = {}
        for row in rows:
            key = (row["error_type"], str(row.get("stage") or "unknown"))
            if key not in counts:
                order.append(key)
                samples[key] = row.get("error_message")
            counts[key] = counts.get(key, 0) + 1
        ordered = sorted(order, key=lambda key: (-counts[key], key[0]))
        return [
            {
                "error_type": error_type,
                "stage": stage,
                "count": counts[(error_type, stage)],
                "sample_message": samples[(error_type, stage)],
            }
            for error_type, stage in ordered[:limit]
        ]


class FakeService:
    def __init__(self):
        self.calls = []

    async def run_incremental(self, history_ids, progress_callback=None):
        self.calls.append(("incremental", list(history_ids)))
        await progress_callback({"progress": 50, "processed_items": 1})
        return {
            "total_items": len(history_ids),
            "processed_items": len(history_ids),
            "indexed_count": len(history_ids),
            "skipped_count": 0,
            "deleted_count": 0,
            "fail_count": 0,
            "failure_details": [],
        }

    async def run_full(self, task_id, progress_callback=None):
        self.calls.append(("full", task_id))
        return {
            "total_items": 2,
            "processed_items": 2,
            "indexed_count": 2,
            "skipped_count": 0,
            "deleted_count": 0,
            "fail_count": 0,
            "failure_details": [],
        }


async def wait_terminal(manager, task_id):
    for _ in range(100):
        await asyncio.sleep(0)
        record = await manager.get(task_id)
        if record["status"] not in ACTIVE:
            return record
    raise AssertionError("task did not finish")


def test_manager_runs_queued_incremental_and_full_tasks_in_order():
    from csrcqsf.modules.railway_parts.services.inquiry_text_index_task_manager import (
        InquiryTextIndexTaskManager,
    )

    async def scenario():
        repository = FakeRepository()
        service = FakeService()
        manager = InquiryTextIndexTaskManager(repository=repository, service=service)
        first = await manager.enqueue_incremental([1, 2], source_sync_task_id="sync-1")
        second = await manager.enqueue_full()
        await manager.start_worker()
        first_done = await wait_terminal(manager, first["task_id"])
        second_done = await wait_terminal(manager, second["task_id"])
        await manager.stop_worker()

        assert first_done["status"] == "success"
        assert first_done["indexed_count"] == 2
        assert second_done["status"] == "success"
        assert [call[0] for call in service.calls] == ["incremental", "full"]

    asyncio.run(scenario())


def test_manager_cancels_pending_task_and_retries_terminal_task():
    from csrcqsf.modules.railway_parts.services.inquiry_text_index_task_manager import (
        InquiryTextIndexTaskManager,
    )

    async def scenario():
        manager = InquiryTextIndexTaskManager(repository=FakeRepository(), service=FakeService())
        original = await manager.enqueue_incremental([7, 8])
        cancelled = await manager.cancel(original["task_id"], "暂不执行")
        retry = await manager.retry(original["task_id"])

        assert cancelled["status"] == "cancelled"
        assert retry["status"] == "pending"
        assert retry["root_task_id"] == original["task_id"]
        assert retry["retry_from_task_id"] == original["task_id"]
        assert retry["history_ids_json"] == [7, 8]

    asyncio.run(scenario())


def test_manager_marks_any_index_failure_as_failed():
    from csrcqsf.modules.railway_parts.services.inquiry_text_index_task_manager import (
        InquiryTextIndexTaskManager,
    )

    class FailingService(FakeService):
        async def run_incremental(self, history_ids, progress_callback=None):
            return {
                "total_items": 2,
                "processed_items": 2,
                "indexed_count": 1,
                "skipped_count": 0,
                "deleted_count": 0,
                "fail_count": 1,
                "failure_details": [
                    {
                        "history_id": 8,
                        "inquiry_id": "1008",
                        "item_id": 80,
                        "stage": "embedding",
                        "error_type": "RuntimeError",
                        "error_message": "model unavailable",
                    }
                ],
            }

    async def scenario():
        repository = FakeRepository()
        manager = InquiryTextIndexTaskManager(repository=repository, service=FailingService())
        task = await manager.enqueue_incremental([7, 8])
        await manager.start_worker()
        completed = await wait_terminal(manager, task["task_id"])
        await manager.stop_worker()

        assert completed["status"] == "failed"
        assert completed["fail_count"] == 1
        assert repository.failures[task["task_id"]][0]["history_id"] == 8

    asyncio.run(scenario())


def test_manager_get_exposes_failure_types_summary_in_task_error_message():
    from csrcqsf.modules.railway_parts.services.inquiry_text_index_task_manager import (
        InquiryTextIndexTaskManager,
    )

    async def scenario():
        repository = FakeRepository()
        manager = InquiryTextIndexTaskManager(repository=repository, service=FakeService())
        task = await manager.enqueue_full()
        repository.records[task["task_id"]].update(
            status="failed",
            fail_count=3,
            error_message="3 条询码语义索引失败，请查看失败明细",
        )
        repository.failures[task["task_id"]] = [
            {
                "history_id": 8,
                "inquiry_id": "1008",
                "item_id": 80,
                "stage": "embedding_or_upsert",
                "error_type": "RuntimeError",
                "error_message": "BGE-M3 model service unavailable",
            },
            {
                "history_id": 9,
                "inquiry_id": "1009",
                "item_id": 81,
                "stage": "embedding_or_upsert",
                "error_type": "RuntimeError",
                "error_message": "BGE-M3 model service unavailable",
            },
            {
                "history_id": 10,
                "inquiry_id": "1010",
                "item_id": 82,
                "stage": "embedding_or_upsert",
                "error_type": "TimeoutError",
                "error_message": "request timed out",
            },
        ]

        detail = await manager.get(task["task_id"])

        assert detail["error_message"] == (
            "3 条询码语义索引失败："
            "RuntimeError×2（阶段 embedding_or_upsert，示例：BGE-M3 model service unavailable）；"
            "TimeoutError×1（阶段 embedding_or_upsert，示例：request timed out）。"
            "完整明细请查看失败明细接口"
        )

    asyncio.run(scenario())


def test_manager_does_not_initialize_milvus_service_until_task_execution(monkeypatch):
    from csrcqsf.modules.railway_parts.services import inquiry_text_index_task_manager as module

    get_service = lambda: (_ for _ in ()).throw(
        AssertionError("service must be initialized lazily")
    )
    monkeypatch.setattr(module, "get_inquiry_semantic_index_service", get_service)

    manager = module.InquiryTextIndexTaskManager(repository=FakeRepository())

    assert manager.service is None
