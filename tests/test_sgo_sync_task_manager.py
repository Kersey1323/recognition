import asyncio

from csrcqsf.modules.sgo.sync_task_manager import SgoSyncTaskManager


def test_sgo_sync_task_manager_tracks_progress_and_completion():
    async def scenario():
        manager = SgoSyncTaskManager()
        release = asyncio.Event()

        async def runner(**kwargs):
            kwargs["progress_callback"](
                {
                    "progress": 50,
                    "total_items": 10,
                    "processed_items": 5,
                    "success_count": 4,
                    "fail_count": 1,
                    "created_count": 3,
                    "skipped_count": 1,
                    "synced_image_count": 8,
                    "current_item_id": "101",
                    "estimated_remaining_seconds": 30,
                }
            )
            await release.wait()
            return {
                "total_items": 10,
                "processed_items": 10,
                "success_count": 9,
                "fail_count": 1,
                "created_count": 3,
                "skipped_count": 6,
                "synced_image_count": 12,
                "failed_item_ids": ["109"],
            }

        started = manager.start("images", runner, item_id_list=["101", "109"])
        await asyncio.sleep(0)

        running = manager.get(started["task_id"])
        assert running["status"] == "running"
        assert running["progress"] == 50
        assert running["estimated_remaining"] == "约30秒"
        assert running["synced_image_count"] == 8

        release.set()
        for _ in range(10):
            await asyncio.sleep(0)
            completed = manager.get(started["task_id"])
            if completed["status"] == "success":
                break

        assert completed["status"] == "success"
        assert completed["progress"] == 100
        assert completed["created_count"] == 3
        assert completed["failed_item_ids"] == ["109"]

    asyncio.run(scenario())


def test_sgo_sync_task_manager_rejects_any_parallel_sync():
    async def scenario():
        manager = SgoSyncTaskManager()
        release = asyncio.Event()

        async def runner(**_kwargs):
            await release.wait()
            return {}

        first = manager.start("parts", runner)
        await asyncio.sleep(0)
        try:
            manager.start("images", runner, item_id_list=["101"])
        except RuntimeError as exc:
            assert first["task_id"] in str(exc)
        else:
            raise AssertionError("已有 SGO 同步运行时应拒绝新任务")
        finally:
            release.set()
            await asyncio.sleep(0)

    asyncio.run(scenario())


def test_sgo_sync_task_manager_marks_all_item_failures_as_failed():
    async def scenario():
        manager = SgoSyncTaskManager()

        async def runner(**_kwargs):
            return {
                "total_items": 2,
                "processed_items": 2,
                "success_count": 0,
                "fail_count": 2,
                "created_count": 0,
                "skipped_count": 0,
                "synced_image_count": 0,
                "failed_item_ids": ["101", "102"],
                "failure_details": [
                    {
                        "item_id": "101",
                        "stage": "base_images",
                        "error_type": "RuntimeError",
                        "error_message": "SGO download failed",
                    },
                    {
                        "item_id": "102",
                        "stage": "base_images",
                        "error_type": "RuntimeError",
                        "error_message": "SGO download failed",
                    },
                ],
            }

        started = manager.start("images", runner, item_id_list=["101", "102"])
        for _ in range(10):
            await asyncio.sleep(0)
            completed = manager.get(started["task_id"])
            if completed["status"] not in {"pending", "running"}:
                break

        assert completed["status"] == "failed"
        assert completed["progress"] == 100
        assert completed["failure_details"][0]["stage"] == "base_images"
        assert "全部 2 个配件同步失败" in completed["error_message"]
        assert "SGO download failed" in completed["error_message"]

    asyncio.run(scenario())


def test_sgo_sync_task_manager_does_not_treat_skipped_items_as_failures():
    async def scenario():
        manager = SgoSyncTaskManager()

        async def runner(**_kwargs):
            return {
                "total_items": 10,
                "processed_items": 10,
                "success_count": 0,
                "fail_count": 2,
                "created_count": 0,
                "skipped_count": 8,
                "synced_image_count": 0,
                "failed_item_ids": ["109", "110"],
                "failure_details": [
                    {
                        "item_id": "109",
                        "stage": "source_validation",
                        "error_type": "InvalidSourceData",
                        "error_message": "配件名称为空",
                    }
                ],
            }

        started = manager.start("parts", runner)
        for _ in range(10):
            await asyncio.sleep(0)
            completed = manager.get(started["task_id"])
            if completed["status"] not in {"pending", "running"}:
                break

        assert completed["status"] == "success"
        assert completed["error_message"] == (
            "2 个配件同步失败；首个错误 [source_validation] "
            "InvalidSourceData: 配件名称为空"
        )

    asyncio.run(scenario())
