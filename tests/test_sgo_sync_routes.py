import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from csrcqsf.modules.sgo import routes


def test_parts_sync_route_submits_background_task_without_awaiting_runner():
    manager = MagicMock()
    manager.start.return_value = {
        "task_id": "parts-task-1",
        "status": "pending",
        "task_type": "parts",
    }

    with patch.object(routes, "sgo_sync_task_manager", manager), patch.object(
        routes.SGOBiz,
        "sync_parts_items",
        AsyncMock(),
    ) as runner:
        result = asyncio.run(routes.sgo_parts_sync(routes.SyncItemsReq()))

    runner.assert_not_awaited()
    manager.start.assert_called_once_with("parts", runner)
    assert result.task_id == "parts-task-1"
    assert result.status == "pending"


def test_images_sync_route_and_status_use_same_task_manager():
    manager = MagicMock()
    manager.start.return_value = {
        "task_id": "images-task-1",
        "status": "pending",
        "task_type": "images",
    }
    manager.get.return_value = {
        "task_id": "images-task-1",
        "task_type": "images",
        "status": "running",
        "progress": 25,
        "total_items": 4,
        "processed_items": 1,
        "success_count": 1,
        "fail_count": 0,
        "created_count": 0,
        "skipped_count": 0,
        "synced_image_count": 3,
        "current_item_id": "101",
        "estimated_remaining_seconds": 9,
        "estimated_remaining": "约9秒",
        "failed_item_ids": [],
        "error_message": None,
        "time_created": "2026-08-17T10:00:00",
        "time_updated": "2026-08-17T10:00:01",
    }

    with patch.object(routes, "sgo_sync_task_manager", manager), patch.object(
        routes.SGOBiz,
        "sync_images",
        AsyncMock(),
    ) as runner:
        started = asyncio.run(
            routes.sgo_parts_image_sync(routes.SyncItemsImages(items_id_list=["101", "102"]))
        )
        status = asyncio.run(routes.sgo_sync_status("images-task-1"))

    runner.assert_not_awaited()
    manager.start.assert_called_once_with(
        "images",
        runner,
        item_id_list=["101", "102"],
    )
    assert started.task_id == "images-task-1"
    assert status.progress == 25
    assert status.synced_image_count == 3


def test_sync_status_returns_404_for_unknown_task():
    manager = MagicMock()
    manager.get.return_value = None
    with patch.object(routes, "sgo_sync_task_manager", manager):
        try:
            asyncio.run(routes.sgo_sync_status("missing"))
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("不存在的同步任务应返回 404")
