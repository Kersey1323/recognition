import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from csrcqsf.modules.sgo import routes


def test_inquiry_list_does_not_filter_index_state_by_default():
    request = routes.ListInqueryReq(page=1, pageSize=10, query="CX221203001")

    assert request.has_indexed == 0


def test_parts_sync_route_submits_background_task_without_awaiting_runner():
    manager = MagicMock()
    manager.start = AsyncMock(return_value={
        "task_id": "parts-task-1",
        "status": "pending",
        "task_type": "parts",
    })

    with patch.object(routes, "sgo_sync_task_manager", manager), patch.object(
        routes.SGOBiz,
        "sync_parts_items",
        AsyncMock(),
    ) as runner:
        result = asyncio.run(routes.sgo_parts_sync(routes.SyncItemsReq()))

    runner.assert_not_awaited()
    manager.start.assert_awaited_once_with("parts", runner)
    assert result.task_id == "parts-task-1"
    assert result.status == "pending"


def test_images_sync_route_and_status_use_same_task_manager():
    manager = MagicMock()
    manager.start = AsyncMock(return_value={
        "task_id": "images-task-1",
        "status": "pending",
        "task_type": "images",
    })
    manager.get = AsyncMock(return_value={
        "task_id": "images-task-1",
        "root_task_id": "images-task-1",
        "retry_from_task_id": None,
        "task_type": "images",
        "task_params_json": {"item_id_list": ["101", "102"]},
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
        "failure_details": [],
        "error_message": None,
        "cancel_reason": None,
        "heartbeat_at": "2026-08-17T10:00:01",
        "started_at": "2026-08-17T10:00:00",
        "completed_at": None,
        "time_created": "2026-08-17T10:00:00",
        "time_updated": "2026-08-17T10:00:01",
    })

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
    manager.start.assert_awaited_once_with(
        "images",
        runner,
        item_id_list=["101", "102"],
        sync_scope="selected",
    )
    assert started.task_id == "images-task-1"
    assert status.progress == 25
    assert status.synced_image_count == 3
    assert status.failure_details == []


def test_images_sync_route_submits_all_scope_without_expanding_item_ids():
    manager = MagicMock()
    manager.start = AsyncMock(
        return_value={
            "task_id": "images-all-task",
            "status": "pending",
            "task_type": "images",
        }
    )

    with patch.object(routes, "sgo_sync_task_manager", manager), patch.object(
        routes.SGOBiz,
        "sync_images",
        AsyncMock(),
    ) as runner:
        result = asyncio.run(
            routes.sgo_parts_image_sync(
                routes.SyncItemsImages(sync_scope="all", items_id_list=[])
            )
        )

    manager.start.assert_awaited_once_with(
        "images",
        runner,
        item_id_list=[],
        sync_scope="all",
    )
    assert result.task_id == "images-all-task"


def test_images_sync_request_rejects_ambiguous_scope_parameters():
    with pytest.raises(ValidationError, match="selected 模式必须提供"):
        routes.SyncItemsImages(sync_scope="selected", items_id_list=[])

    with pytest.raises(ValidationError, match="all 模式不允许提供"):
        routes.SyncItemsImages(sync_scope="all", items_id_list=["101"])


def test_inquiry_history_sync_route_submits_background_task_without_awaiting_runner():
    manager = MagicMock()
    manager.start = AsyncMock(return_value={
        "task_id": "history-task-1",
        "status": "pending",
        "task_type": "inquiry-history",
    })

    with patch.object(routes, "sgo_sync_task_manager", manager), patch.object(
        routes.SGOBiz,
        "sync_inquiry_history",
        AsyncMock(),
    ) as runner:
        result = asyncio.run(routes.sgo_inquiry_history_sync(routes.SyncInquiryHistoryReq()))

    runner.assert_not_awaited()
    manager.start.assert_awaited_once_with(
        "inquiry-history",
        runner,
        limit=None,
        batch_size=500,
    )
    assert result.task_id == "history-task-1"
    assert result.status == "pending"
    assert result.task_type == "inquiry-history"


def test_sync_status_returns_404_for_unknown_task():
    manager = MagicMock()
    manager.get = AsyncMock(return_value=None)
    with patch.object(routes, "sgo_sync_task_manager", manager):
        try:
            asyncio.run(routes.sgo_sync_status("missing"))
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("不存在的同步任务应返回 404")


def test_sync_task_list_cancel_retry_and_failures_routes():
    record = {
        "task_id": "task-1",
        "root_task_id": "task-1",
        "retry_from_task_id": None,
        "task_type": "parts",
        "task_params_json": {},
        "status": "success",
        "progress": 100,
        "total_items": 10,
        "processed_items": 10,
        "success_count": 2,
        "fail_count": 1,
        "created_count": 2,
        "skipped_count": 7,
        "synced_image_count": 0,
        "current_item_id": None,
        "estimated_remaining_seconds": 0,
        "estimated_remaining": "已完成",
        "error_message": "1 个配件同步失败",
        "cancel_reason": None,
        "heartbeat_at": "2026-08-21T10:00:01",
        "started_at": "2026-08-21T10:00:00",
        "completed_at": "2026-08-21T10:00:01",
        "time_created": "2026-08-21T10:00:00",
        "time_updated": "2026-08-21T10:00:01",
    }
    manager = MagicMock()
    manager.list = AsyncMock(return_value=([record], 1))
    manager.get = AsyncMock(return_value=record)
    manager.cancel = AsyncMock(return_value={**record, "status": "cancelling"})
    manager.retry = AsyncMock(
        return_value={
            **record,
            "task_id": "task-2",
            "retry_from_task_id": "task-1",
            "status": "pending",
            "progress": 0,
        }
    )
    manager.list_failures = AsyncMock(
        return_value=(
            [
                {
                    "item_id": "109",
                    "stage": "source_validation",
                    "error_type": "InvalidSourceData",
                    "error_message": "配件名称为空",
                    "time_created": datetime(2026, 8, 21, 10, 0, 0),
                }
            ],
            1,
        )
    )

    with patch.object(routes, "sgo_sync_task_manager", manager):
        listed = asyncio.run(
            routes.list_sgo_sync_tasks(
                routes.SgoSyncTaskListReq(
                    page=1,
                    pageSize=20,
                    status="all",
                    task_type="all",
                )
            )
        )
        detail = asyncio.run(routes.get_sgo_sync_task("task-1"))
        cancelling = asyncio.run(
            routes.cancel_sgo_sync_task(
                "task-1",
                routes.SgoSyncTaskCancelReq(cancel_reason="用户停止"),
            )
        )
        retried = asyncio.run(routes.retry_sgo_sync_task("task-1"))
        failures = asyncio.run(
            routes.list_sgo_sync_task_failures(
                "task-1",
                routes.SgoSyncFailureListReq(page=1, pageSize=20),
            )
        )

    assert listed.total == 1
    assert listed.records[0].task_id == "task-1"
    assert detail.task_params_json == {}
    assert cancelling.status == "cancelling"
    assert retried.task_id == "task-2"
    assert failures.total == 1
    assert failures.records[0].error_message == "配件名称为空"
