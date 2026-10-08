import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from csrcqsf.modules.sgo import routes


def test_inquiry_list_does_not_filter_index_state_by_default():
    request = routes.ListInqueryReq(page=1, pageSize=10, query="CX221203001")

    assert request.has_indexed == 0


def test_inquiry_list_exposes_manually_confirmed_item_code_and_name():
    row = SimpleNamespace(
        id="inquiry-1",
        inquiry_num="CX20260908020",
        creater_org_name="太原分中心",
        creater="朱厚霖",
        item_name="直流型小型断路器",
        subordinate_component="电气",
        train_no="2933",
        car_num="00",
        vehicle="SFE27",
        submission_date="2026-09-08",
        remark=None,
        current_status="FINISH",
        supplier_name=None,
        supplier_code=None,
        nameplate_photos=None,
        detailed_photos=None,
        return_item_name_raw="锁闭L=1889",
        return_item_code_raw="19010033275",
    )
    page = SimpleNamespace(total=1, data=[row])
    req = routes.ListInqueryReq(page=1, pageSize=10, current_status="FINISH")

    with patch.object(routes.SGOBiz, "list_inquery", AsyncMock(return_value=page)):
        result = asyncio.run(routes.sgo_inquery_list(req))

    assert result.items[0].item_name == "直流型小型断路器"
    assert result.items[0].return_item_code == "19010033275"
    assert result.items[0].return_item_name == "锁闭L=1889"


@pytest.mark.parametrize(
    ("physical_item_name", "physical_item_code", "expected_code", "expected_name"),
    [
        (
            "M8*20 不锈钢三组合螺栓",
            "40000537115",
            "40000537115",
            "M8*20 不锈钢三组合螺栓",
        ),
        ("19010029156", "机械螺丝钉", "19010029156", "机械螺丝钉"),
    ],
)
def test_inquiry_return_fields_support_normal_and_reversed_sgo_rows(
    physical_item_name,
    physical_item_code,
    expected_code,
    expected_name,
):
    from csrcqsf.modules.sgo.item_mapping import normalize_sgo_return_item

    assert normalize_sgo_return_item(physical_item_name, physical_item_code) == (
        expected_code,
        expected_name,
    )


def test_sgo_sync_status_schema_exposes_semantic_trigger_flag():
    properties = routes.SgoSyncTaskStatusRes.schema()["properties"]

    assert properties["semantic_index_triggered"]["type"] == "boolean"
    assert "创建或合并" in properties["semantic_index_triggered"]["description"]
    assert "updated_metadata_count" in properties
    assert "synced_supplier_count" in properties
    assert "deleted_supplier_count" in properties
    assert "unmatched_supplier_count" in properties
    assert "hierarchy_total_count" in properties
    assert "synced_hierarchy_count" in properties
    assert "deleted_hierarchy_count" in properties
    assert "unresolved_vehicle_count" in properties
    assert "invalid_hierarchy_count" in properties


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


def test_non_a1_cleanup_preview_and_execute_routes_are_separated():
    manager = MagicMock()
    manager.start = AsyncMock(return_value={
        "task_id": "cleanup-task-1",
        "status": "pending",
        "task_type": "parts-cleanup",
    })
    preview = {
        "source_a1_code_count": 87_817,
        "local_item_count": 90_000,
        "a1_retained_count": 87_800,
        "protected_source_video_count": 12,
        "candidate_count": 2_188,
        "candidate_with_images_count": 20,
        "candidate_with_indexes_count": 5,
        "preview_token": "a" * 64,
        "sample_items": [{"item_id": "101", "item_code": "A5-1", "item_name": "待清理配件"}],
    }

    with patch.object(routes, "sgo_sync_task_manager", manager), patch.object(
        routes.SGOBiz,
        "preview_non_a1_cleanup",
        AsyncMock(return_value=preview),
    ), patch.object(
        routes.SGOBiz,
        "validate_non_a1_cleanup_preview",
        AsyncMock(),
    ), patch.object(
        routes.SGOBiz,
        "cleanup_non_a1_data",
        AsyncMock(),
    ) as runner:
        preview_result = asyncio.run(routes.preview_sgo_non_a1_cleanup())
        started = asyncio.run(routes.execute_sgo_non_a1_cleanup(
            routes.SgoNonA1CleanupExecuteReq(
                preview_token="a" * 64,
                confirmation="DELETE_NON_A1_WITHOUT_SOURCE_VIDEO",
            )
        ))

    assert preview_result.candidate_count == 2_188
    runner.assert_not_awaited()
    manager.start.assert_awaited_once_with(
        "parts-cleanup",
        runner,
        preview_token="a" * 64,
    )
    assert started.task_id == "cleanup-task-1"


def test_non_a1_cleanup_execute_request_requires_token_and_fixed_confirmation():
    with pytest.raises(ValidationError):
        routes.SgoNonA1CleanupExecuteReq(
            preview_token="a" * 64,
            confirmation="yes",
        )
    with pytest.raises(ValidationError):
        routes.SgoNonA1CleanupExecuteReq(
            confirmation="DELETE_NON_A1_WITHOUT_SOURCE_VIDEO",
        )


def test_non_a1_cleanup_execute_rejects_stale_preview_token():
    with patch.object(
        routes.SGOBiz,
        "validate_non_a1_cleanup_preview",
        AsyncMock(side_effect=ValueError("清理范围已变化，请重新调用预览接口")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(routes.execute_sgo_non_a1_cleanup(
                routes.SgoNonA1CleanupExecuteReq(
                    preview_token="a" * 64,
                    confirmation="DELETE_NON_A1_WITHOUT_SOURCE_VIDEO",
                )
            ))

    assert exc_info.value.status_code == 409


def test_non_a1_cleanup_routes_replace_obsolete_a9_routes():
    paths = {route.path for route in routes.sgo_router.routes}

    assert "/sgo/sgo/parts/cleanup/non-a1/preview" in paths
    assert "/sgo/sgo/parts/cleanup/non-a1" in paths
    assert "/sgo/sgo/parts/cleanup/a9/preview" not in paths
    assert "/sgo/sgo/parts/cleanup/a9" not in paths


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
                    "item_code": "40000537115",
                    "item_name": "不锈钢三组合螺栓",
                    "error_code": "SOURCE_ITEM_NAME_EMPTY",
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
                routes.SgoSyncFailureListReq(
                    page=1,
                    pageSize=20,
                    error_code="SOURCE_ITEM_NAME_EMPTY",
                ),
            )
        )

    assert listed.total == 1
    assert listed.records[0].task_id == "task-1"
    assert detail.task_params_json == {}
    assert cancelling.status == "cancelling"
    assert retried.task_id == "task-2"
    assert failures.total == 1
    assert failures.records[0].item_id == "109"
    assert failures.records[0].item_code == "40000537115"
    assert failures.records[0].item_name == "不锈钢三组合螺栓"
    assert failures.records[0].error_code == "SOURCE_ITEM_NAME_EMPTY"
    assert failures.records[0].error_message == "配件名称为空"
    manager.list_failures.assert_awaited_once_with(
        "task-1",
        page=1,
        per_page=20,
        stage=None,
        error_type=None,
        error_message=None,
        error_code="SOURCE_ITEM_NAME_EMPTY",
    )


def test_delete_sync_tasks_route_returns_cleanup_counts():
    assert any(
        route.path == "/sgo/sgo/sync/tasks/delete" and "POST" in route.methods
        for route in routes.sgo_router.routes
    )
    manager = MagicMock()
    manager.delete_tasks = AsyncMock(return_value={
        "requested_count": 3,
        "deleted_task_count": 2,
        "deleted_failure_count": 3974,
        "missing_task_ids": ["missing"],
    })

    with patch.object(routes, "sgo_sync_task_manager", manager):
        result = asyncio.run(routes.delete_sgo_sync_tasks(
            routes.SgoSyncTaskDeleteReq(task_id_list=["task-1", "task-2", "missing"])
        ))

    assert result.deleted_task_count == 2
    assert result.deleted_failure_count == 3974
    assert result.missing_task_ids == ["missing"]
    manager.delete_tasks.assert_awaited_once_with(["task-1", "task-2", "missing"])


def test_delete_sync_tasks_route_maps_active_task_conflict():
    manager = MagicMock()
    manager.delete_tasks = AsyncMock(side_effect=RuntimeError("运行中的 SGO 同步任务不可删除"))

    with patch.object(routes, "sgo_sync_task_manager", manager), pytest.raises(HTTPException) as error:
        asyncio.run(routes.delete_sgo_sync_tasks(
            routes.SgoSyncTaskDeleteReq(task_id_list=["active-task"])
        ))

    assert error.value.status_code == 409


def test_sync_task_statistics_route_selects_tab_type():
    assert any(
        route.path == "/sgo/sgo/sync/tasks/statistics" and "POST" in route.methods
        for route in routes.sgo_router.routes
    )
    manager = MagicMock()
    manager.statistics = AsyncMock(return_value={
        "task_success_rate": 99,
        "total_tasks": 324,
        "successful_tasks": 322,
        "failed_tasks": 0,
        "active_tasks": 0,
    })
    with patch.object(routes, "sgo_sync_task_manager", manager):
        result = asyncio.run(routes.get_sgo_sync_task_statistics(
            routes.SgoSyncTaskStatisticsReq(type="parts")
        ))
    assert result.task_success_rate == 99
    assert result.total_tasks == 324
    manager.statistics.assert_awaited_once_with("parts")
