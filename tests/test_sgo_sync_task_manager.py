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
