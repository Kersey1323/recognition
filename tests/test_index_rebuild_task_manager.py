import asyncio

from csrcqsf.modules.railway_parts.services.index_rebuild_task_manager import (
    IndexRebuildTaskManager,
)


def test_index_rebuild_task_manager_tracks_progress_eta_and_completion():
    async def scenario():
        manager = IndexRebuildTaskManager()
        release = asyncio.Event()

        async def runner(**kwargs):
            kwargs["progress_callback"](
                {
                    "progress": 40,
                    "total_items": 10,
                    "processed_items": 4,
                    "success_count": 12,
                    "fail_count": 1,
                    "current_item_id": 101,
                    "estimated_remaining_seconds": 90,
                }
            )
            await release.wait()
            return {
                "success_count": 30,
                "fail_count": 2,
                "total": 32,
                "processed_item_count": 10,
                "skipped_existing_count": 0,
            }

        started = manager.start(
            runner=runner,
            item_id=None,
            limit=10,
            rebuild_existing=False,
        )
        await asyncio.sleep(0)

        running = manager.get(started["task_id"])
        assert running["status"] == "running"
        assert running["progress"] == 40
        assert running["estimated_remaining_seconds"] == 90
        assert running["estimated_remaining"] == "约1分30秒"

        release.set()
        for _ in range(10):
            await asyncio.sleep(0)
            completed = manager.get(started["task_id"])
            if completed["status"] == "success":
                break

        assert completed["status"] == "success"
        assert completed["progress"] == 100
        assert completed["estimated_remaining_seconds"] == 0
        assert completed["estimated_remaining"] == "已完成"

    asyncio.run(scenario())


def test_index_rebuild_task_manager_rejects_duplicate_active_task():
    async def scenario():
        manager = IndexRebuildTaskManager()
        release = asyncio.Event()

        async def runner(**_kwargs):
            await release.wait()
            return {}

        first = manager.start(runner, item_id=None, limit=500, rebuild_existing=False)
        await asyncio.sleep(0)

        try:
            manager.start(runner, item_id=None, limit=500, rebuild_existing=False)
        except RuntimeError as exc:
            assert first["task_id"] in str(exc)
        else:
            raise AssertionError("重复的全量索引任务应被拒绝")
        finally:
            release.set()
            await asyncio.sleep(0)

    asyncio.run(scenario())
