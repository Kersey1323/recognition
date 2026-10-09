import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from csrcqsf.modules.railway_parts.services.viewer360_task_manager import (
    Viewer360ConflictError,
    Viewer360TaskManager,
)


class FakeRepository:
    def __init__(self):
        self.tasks = {}
        self.current = {}
        self.failures = []
        self.item = {
            "item_id": 12,
            "item_name": "测试配件",
            "source_video_object": "videos/12.mp4",
            "source_video_updated_at": datetime(2026, 9, 2),
        }
        self.backfill_candidates = []
        self.backfill_counts = []

    async def count_backfill_candidates(self):
        if self.backfill_counts:
            return self.backfill_counts.pop(0)
        return len(self.backfill_candidates)

    async def list_backfill_candidates(self, *, limit):
        return self.backfill_candidates[:limit]

    async def get_item_source(self, item_id):
        return self.item if item_id == 12 else None

    async def find_active_by_item(self, item_id):
        return next(
            (
                task
                for task in self.tasks.values()
                if task["item_id"] == item_id
                and task["status"] in {"pending", "running", "cancelling"}
            ),
            None,
        )

    async def get_current(self, item_id):
        return self.current.get(item_id)

    async def create_task(self, **values):
        values.setdefault("time_created", datetime.now())
        values.setdefault("time_updated", datetime.now())
        self.tasks[values["task_id"]] = values
        return dict(values)

    async def get_task(self, task_id):
        task = self.tasks.get(task_id)
        return dict(task) if task else None

    async def transition_task(self, task_id, from_statuses, **values):
        task = self.tasks.get(task_id)
        if task is None or task["status"] not in from_statuses:
            return None
        task.update(values)
        return dict(task)

    async def update_task(self, task_id, **values):
        self.tasks[task_id].update(values)
        return dict(self.tasks[task_id])

    async def reset_task_for_retry(self, task_id, from_statuses, **values):
        task = self.tasks.get(task_id)
        if task is None or task["status"] not in from_statuses:
            return None
        task.update(values)
        self.failures = [
            failure for failure in self.failures if failure["task_id"] != task_id
        ]
        return dict(task)

    async def publish_success(self, task_id, **values):
        self.tasks[task_id].update(values, status="success", progress=100)
        self.current[values["item_id"]] = {
            "item_id": values["item_id"],
            "task_id": task_id,
            "manifest_object": values["manifest_object"],
            "amount_x": values["amount_x"],
            "amount_y": values["amount_y"],
            "fingerprint": values["fingerprint"],
        }
        return dict(self.tasks[task_id])

    async def add_failure(self, **values):
        self.failures.append(values)
        return values


class FakePipeline:
    def __init__(self, work_root: Path | None = None):
        self.calls = []
        self.storage = FakeStorage()
        self.config = SimpleNamespace(
            row_count=4,
            task_timeout_seconds=1800,
            work_root=work_root,
        )

    async def run(self, task, *, source_task=None, progress_callback=None, is_cancelled=None):
        self.calls.append((task, source_task))
        await progress_callback({"current_stage": "segmenting", "progress": 50})
        return SimpleNamespace(
            manifest_object=f"viewer360/12/{task['task_id']}/manifest.json",
            amount_x=50,
            amount_y=4,
            fingerprint="fp",
            target_center=(800.0, 800.0),
            total_frames=200,
            row_states=[{"row_index": 1, "status": "success"}],
            render_mode="segmented",
            fallback_reason=None,
        )


class FakeStorage:
    result_bucket = "results"

    def __init__(self):
        self.checked_sources = []
        self.deleted_results = []

    @staticmethod
    def result_prefix(item_id, task_id):
        return f"viewer360/{item_id}/{task_id}"

    async def ensure_source_readable(self, source_path):
        self.checked_sources.append(source_path)
        return "videos", source_path

    async def delete_result(self, **kwargs):
        self.deleted_results.append(kwargs)
        return 0


def test_submit_persists_pending_task_and_rejects_duplicate_item():
    repository = FakeRepository()
    manager = Viewer360TaskManager(repository=repository, pipeline=FakePipeline())

    first = asyncio.run(manager.submit(item_id=12, rebuild_existing=True))
    with pytest.raises(Viewer360ConflictError) as exc_info:
        asyncio.run(manager.submit(item_id=12, rebuild_existing=True))

    assert first["status"] == "pending"
    assert exc_info.value.task_id == first["task_id"]


def test_submit_checks_source_video_before_creating_task():
    repository = FakeRepository()
    pipeline = FakePipeline()
    manager = Viewer360TaskManager(repository=repository, pipeline=pipeline)

    result = asyncio.run(manager.submit(item_id=12, rebuild_existing=True))

    assert pipeline.storage.checked_sources == ["videos/12.mp4"]
    assert result["status"] == "pending"


def test_backfill_creates_tasks_and_isolates_item_failures(monkeypatch):
    repository = FakeRepository()
    repository.backfill_candidates = [
        {"item_id": 12, "item_code": "P12", "item_name": "配件12"},
        {"item_id": 13, "item_code": "P13", "item_name": "配件13"},
        {"item_id": 14, "item_code": "P14", "item_name": "配件14"},
        {"item_id": 15, "item_code": "P15", "item_name": "配件15"},
    ]
    repository.backfill_counts = [4, 2]
    manager = Viewer360TaskManager(repository=repository, pipeline=FakePipeline())

    async def submit(*, item_id, rebuild_existing):
        assert rebuild_existing is False
        if item_id == 12:
            return {
                "task_id": "task-12",
                "item_id": "12",
                "item_code": "P12",
                "item_name": "配件12",
                "status": "pending",
                "reused_existing": False,
            }
        if item_id == 13:
            return {
                "task_id": "existing-13",
                "item_id": "13",
                "item_code": "P13",
                "item_name": "配件13",
                "status": "success",
                "reused_existing": True,
            }
        if item_id == 14:
            raise Viewer360ConflictError("任务已存在")
        raise OSError("source missing")

    monkeypatch.setattr(manager, "submit", submit)

    result = asyncio.run(manager.backfill(limit=4))

    assert result["eligible_total"] == 4
    assert result["created_count"] == 1
    assert result["skipped_count"] == 2
    assert result["failed_count"] == 1
    assert result["remaining_count"] == 2
    assert result["created_tasks"][0]["task_id"] == "task-12"
    assert result["failures"] == [
        {
            "item_id": "15",
            "item_code": "P15",
            "item_name": "配件15",
            "error_message": "source missing",
        }
    ]


def test_disabled_manager_rejects_backfill():
    manager = Viewer360TaskManager(
        repository=FakeRepository(),
        pipeline=FakePipeline(),
        enabled=False,
    )

    with pytest.raises(Viewer360ConflictError, match="未启用"):
        asyncio.run(manager.backfill(limit=100))


def test_disabled_manager_rejects_manual_submission_and_starts_no_workers():
    manager = Viewer360TaskManager(
        repository=FakeRepository(),
        pipeline=FakePipeline(),
        enabled=False,
    )

    async def run():
        await manager.start_workers()
        with pytest.raises(Viewer360ConflictError, match="未启用"):
            await manager.submit(item_id=12, rebuild_existing=True)
        return manager._workers

    assert asyncio.run(run()) == []


def test_submit_reuses_current_result_without_creating_task():
    repository = FakeRepository()
    repository.current[12] = {
        "item_id": 12,
        "task_id": "existing",
        "manifest_object": "viewer360/12/existing/manifest.json",
    }
    repository.tasks["existing"] = {"task_id": "existing", "item_id": 12, "status": "success"}
    manager = Viewer360TaskManager(repository=repository, pipeline=FakePipeline())

    result = asyncio.run(manager.submit(item_id=12, rebuild_existing=False))

    assert result["task_id"] == "existing"
    assert result["reused_existing"] is True
    assert len(repository.tasks) == 1


def test_task_detail_exposes_frontend_image_path_for_each_row():
    repository = FakeRepository()
    repository.tasks["completed"] = {
        "task_id": "completed",
        "item_id": 12,
        "status": "success",
        "output_bucket": "bfr-reconstruction-files",
        "manifest_object": "viewer360/12/completed/manifest.json",
        "amount_x": 72,
        "pipeline_metadata_json": {
            "render_mode": "original",
            "fallback_reason": "分割结果不完整",
        },
        "row_states_json": [
            {"row_index": 1, "status": "success"},
            {"row_index": 2, "status": "success"},
        ],
    }
    manager = Viewer360TaskManager(repository=repository, pipeline=FakePipeline())

    result = asyncio.run(manager.get("completed"))

    assert result["rows"][0] == {
        "row_index": 1,
        "status": "success",
        "image_base_url": (
            "bfr-reconstruction-files/viewer360/12/completed/images/row_01"
        ),
        "frame_count": 72,
        "frame_url_template": (
            "bfr-reconstruction-files/viewer360/12/completed/images/"
            "row_01/frame_{frame_no}.webp"
        ),
    }
    assert result["render_mode"] == "original"
    assert result["fallback_reason"] == "分割结果不完整"


def test_run_pending_task_publishes_current_pointer():
    repository = FakeRepository()
    pipeline = FakePipeline()
    manager = Viewer360TaskManager(repository=repository, pipeline=pipeline)

    async def run():
        task = await manager.submit(item_id=12, rebuild_existing=True)
        await manager.run_task(task["task_id"])
        return task

    submitted = asyncio.run(run())

    assert repository.tasks[submitted["task_id"]]["status"] == "success"
    assert repository.current[12]["task_id"] == submitted["task_id"]
    metadata = repository.tasks[submitted["task_id"]]["pipeline_metadata_json"]
    assert metadata["render_mode"] == "segmented"
    assert metadata["fallback_reason"] is None


def test_successful_task_removes_local_work_directory(tmp_path: Path):
    repository = FakeRepository()
    pipeline = FakePipeline(work_root=tmp_path)
    manager = Viewer360TaskManager(repository=repository, pipeline=pipeline)

    async def run():
        task = await manager.submit(item_id=12, rebuild_existing=True)
        task_dir = tmp_path / task["task_id"]
        task_dir.mkdir()
        (task_dir / "checkpoint.json").write_text("{}", encoding="utf-8")
        await manager.run_task(task["task_id"])
        return task_dir

    assert not asyncio.run(run()).exists()


def test_failed_task_keeps_local_work_directory_for_retry(tmp_path: Path):
    repository = FakeRepository()

    class FailingPipeline(FakePipeline):
        async def run(self, task, **_kwargs):
            task_dir = self.config.work_root / task["task_id"]
            task_dir.mkdir()
            (task_dir / "source_video").write_bytes(b"video")
            raise RuntimeError("segmentation failed")

    pipeline = FailingPipeline(work_root=tmp_path)
    manager = Viewer360TaskManager(repository=repository, pipeline=pipeline)

    async def run():
        task = await manager.submit(item_id=12, rebuild_existing=True)
        await manager.run_task(task["task_id"])
        return task["task_id"], tmp_path / task["task_id"]

    task_id, task_dir = asyncio.run(run())

    assert repository.tasks[task_id]["status"] == "failed"
    assert task_dir.is_dir()
    assert (task_dir / "source_video").is_file()


def test_start_workers_removes_expired_work_directories(tmp_path: Path):
    old_dir = tmp_path / "old-task"
    recent_dir = tmp_path / "recent-task"
    old_dir.mkdir()
    recent_dir.mkdir()
    old_timestamp = datetime(2020, 1, 1).timestamp()
    import os

    os.utime(old_dir, (old_timestamp, old_timestamp))
    manager = Viewer360TaskManager(
        repository=FakeRepository(),
        pipeline=FakePipeline(work_root=tmp_path),
        work_retention_days=1,
    )

    async def run():
        await manager.start_workers()
        await manager.stop_workers()

    asyncio.run(run())

    assert not old_dir.exists()
    assert recent_dir.exists()


def test_startup_cleanup_keeps_failed_checkpoint_and_removes_success_residue(
    tmp_path: Path,
):
    repository = FakeRepository()
    failed_dir = tmp_path / "failed-task"
    success_dir = tmp_path / "success-task"
    failed_dir.mkdir()
    success_dir.mkdir()
    repository.tasks["failed-task"] = {
        "task_id": "failed-task",
        "item_id": 12,
        "status": "failed",
    }
    repository.tasks["success-task"] = {
        "task_id": "success-task",
        "item_id": 12,
        "status": "success",
    }
    manager = Viewer360TaskManager(
        repository=repository,
        pipeline=FakePipeline(work_root=tmp_path),
    )

    asyncio.run(manager._cleanup_expired_work_dirs())

    assert failed_dir.is_dir()
    assert not success_dir.exists()


def test_cancel_pending_task_removes_local_work_directory(tmp_path: Path):
    repository = FakeRepository()
    pipeline = FakePipeline(work_root=tmp_path)
    manager = Viewer360TaskManager(repository=repository, pipeline=pipeline)

    async def run():
        task = await manager.submit(item_id=12, rebuild_existing=True)
        task_dir = tmp_path / task["task_id"]
        task_dir.mkdir()
        (task_dir / "source_video").write_bytes(b"video")
        cancelled = await manager.cancel(task["task_id"], reason="用户取消")
        return cancelled, task_dir

    cancelled, task_dir = asyncio.run(run())

    assert cancelled["status"] == "cancelled"
    assert not task_dir.exists()


def test_retry_selected_rows_reuses_original_task_id():
    repository = FakeRepository()
    repository.tasks["old"] = {
        "task_id": "old",
        "root_task_id": "root",
        "retry_from_task_id": None,
        "item_id": 12,
        "source_video_object": "videos/12.mp4",
        "source_video_updated_at": None,
        "status": "success",
        "row_count": 4,
        "manifest_object": "viewer360/12/old/manifest.json",
        "result_deleted_at": None,
        "progress": 100,
        "current_stage": "completed",
        "error_message": None,
        "completed_at": datetime(2026, 9, 2),
    }
    repository.failures.append({"task_id": "old", "stage": "postprocess"})
    manager = Viewer360TaskManager(repository=repository, pipeline=FakePipeline())

    result = asyncio.run(
        manager.retry(
            "old",
            retry_mode="resegment_rows",
            row_indexes=[4, 2, 2],
            reason="角度2和角度4分割不完整",
        )
    )

    assert result["task_id"] == "old"
    assert len(repository.tasks) == 1
    assert result["status"] == "pending"
    assert result["progress"] == 0
    assert result["current_stage"] == "preparing"
    assert result["retry_rows_json"] == [2, 4]
    assert result["retry_reason"] == "角度2和角度4分割不完整"
    assert result["completed_at"] is None
    assert repository.failures == []


def test_resume_failed_task_reuses_original_task_as_checkpoint_source():
    repository = FakeRepository()
    repository.tasks["failed-task"] = {
        "task_id": "failed-task",
        "root_task_id": "failed-task",
        "retry_from_task_id": None,
        "item_id": 12,
        "source_video_object": "videos/12.mp4",
        "source_video_updated_at": None,
        "status": "failed",
        "row_count": 4,
        "fingerprint": "fp",
        "result_deleted_at": None,
        "progress": 75,
        "current_stage": "postprocessing",
        "error_message": "center validation failed",
        "completed_at": datetime(2026, 9, 2),
    }
    pipeline = FakePipeline()
    manager = Viewer360TaskManager(repository=repository, pipeline=pipeline)

    async def run():
        retried = await manager.retry("failed-task", retry_mode="resume")
        await manager.run_task(retried["task_id"])
        return retried

    result = asyncio.run(run())

    assert result["task_id"] == "failed-task"
    assert pipeline.calls[0][1]["task_id"] == "failed-task"
    assert pipeline.calls[0][1]["fingerprint"] == "fp"


def test_cancelled_row_retry_keeps_oss_result_but_removes_local_work(
    tmp_path: Path,
):
    repository = FakeRepository()
    repository.tasks["existing"] = {
        "task_id": "existing",
        "root_task_id": "existing",
        "retry_from_task_id": None,
        "item_id": 12,
        "source_video_object": "videos/12.mp4",
        "source_video_updated_at": None,
        "status": "success",
        "row_count": 4,
        "manifest_object": "viewer360/12/existing/manifest.json",
        "pipeline_metadata_json": {"target_center": [800.0, 800.0]},
        "result_deleted_at": None,
        "progress": 100,
        "current_stage": "completed",
    }

    class CancelAfterPipeline(FakePipeline):
        async def run(self, task, **kwargs):
            task_dir = self.config.work_root / task["task_id"]
            task_dir.mkdir()
            (task_dir / "source_video").write_bytes(b"video")
            result = await super().run(task, **kwargs)
            repository.tasks[task["task_id"]]["status"] = "cancelling"
            return result

    pipeline = CancelAfterPipeline(work_root=tmp_path)
    manager = Viewer360TaskManager(repository=repository, pipeline=pipeline)

    async def run():
        retried = await manager.retry(
            "existing",
            retry_mode="resegment_rows",
            row_indexes=[2],
        )
        await manager.run_task(retried["task_id"])

    asyncio.run(run())

    assert pipeline.storage.deleted_results == []
    assert repository.tasks["existing"]["status"] == "cancelled"
    assert not (tmp_path / "existing").exists()
