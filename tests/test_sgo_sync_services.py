import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.sgo_external import SgoMaterielMasterplate
from csrcqsf.modules.sgo.schemas import ImageSourceType
from csrcqsf.modules.sgo.services import (
    ImageSyncCandidate,
    ImageSyncItem,
    ImageSyncItemBatch,
    SGOBiz,
)


sgo_services = importlib.import_module("csrcqsf.modules.sgo.services")


def test_sync_images_continues_after_single_item_failure_and_reports_progress():
    progress = []

    async def batches():
        yield ImageSyncItemBatch(
            requested_ids=["101", "102", "103"],
            items=[
                ImageSyncItem("101", "A"),
                ImageSyncItem("102", "B"),
                ImageSyncItem("103", "C"),
            ],
        )

    candidates = {
        item_id: ImageSyncCandidate(item_id, item_id, ImageSourceType.BASEINFO)
        for item_id in ("101", "102", "103")
    }
    upload_failure = {
        "item_id": "102",
        "stage": "minio_upload",
        "error_type": "RuntimeError",
        "error_message": "source image failed",
    }
    with patch.object(
        SGOBiz,
        "count_image_sync_items",
        AsyncMock(return_value=3),
    ), patch.object(
        SGOBiz,
        "_iter_image_item_batches",
        MagicMock(return_value=batches()),
    ), patch.object(
        SGOBiz,
        "_collect_image_candidates",
        AsyncMock(return_value=(candidates, [])),
    ), patch.object(
        SGOBiz,
        "_filter_missing_candidates",
        AsyncMock(return_value=(list(candidates.values()), 0)),
    ), patch.object(
        SGOBiz,
        "_store_zip_candidates",
        AsyncMock(return_value=(2, [upload_failure])),
    ), patch.object(sgo_services, "sgo_image_zip_batch_size", 3):
        SGOBiz.token = "test-token"
        result = asyncio.run(
            SGOBiz.sync_images(
                item_id_list=["101", "102", "103"],
                sync_scope="selected",
                progress_callback=progress.append,
            )
        )

    assert result == {
        "total_items": 3,
        "processed_items": 3,
        "success_count": 2,
        "fail_count": 1,
        "created_count": 2,
        "skipped_count": 0,
        "synced_image_count": 2,
        "failed_item_ids": ["102"],
        "failure_details": [upload_failure],
        "failures_persisted_incrementally": True,
    }
    assert [item["progress"] for item in progress] == [0, 100]
    assert progress[-1]["estimated_remaining_seconds"] == 0
    assert progress[-1]["new_failure_details"] == [upload_failure]


def test_sync_images_bounds_failure_summary_in_memory():
    async def batches():
        yield ImageSyncItemBatch(
            requested_ids=["101", "102", "103"],
            items=[
                ImageSyncItem("101", "A"),
                ImageSyncItem("102", "B"),
                ImageSyncItem("103", "C"),
            ],
        )

    candidates = {
        item_id: ImageSyncCandidate(item_id, item_id, ImageSourceType.BASEINFO)
        for item_id in ("101", "102", "103")
    }
    failures = [
        {
            "item_id": item_id,
            "stage": "minio_upload",
            "error_type": "RuntimeError",
            "error_message": "source image failed",
        }
        for item_id in candidates
    ]
    with patch.object(
        SGOBiz,
        "count_image_sync_items",
        AsyncMock(return_value=3),
    ), patch.object(
        SGOBiz,
        "_iter_image_item_batches",
        MagicMock(return_value=batches()),
    ), patch.object(
        SGOBiz,
        "_collect_image_candidates",
        AsyncMock(return_value=(candidates, [])),
    ), patch.object(
        SGOBiz,
        "_filter_missing_candidates",
        AsyncMock(return_value=(list(candidates.values()), 0)),
    ), patch.object(
        SGOBiz,
        "_store_zip_candidates",
        AsyncMock(return_value=(0, failures)),
    ), patch.object(sgo_services, "MAX_SYNC_FAILURE_DETAILS", 2):
        SGOBiz.token = "test-token"
        result = asyncio.run(
            SGOBiz.sync_images(
                item_id_list=["101", "102", "103"],
                sync_scope="selected",
            )
        )

    assert result["fail_count"] == 3
    assert result["failed_item_ids"] == ["101", "102"]
    assert result["failure_details"] == failures[:2]


def test_sync_images_reports_progress_between_zip_batches():
    progress = []

    async def batches():
        yield ImageSyncItemBatch(
            requested_ids=["101", "102"],
            items=[ImageSyncItem("101", "A"), ImageSyncItem("102", "B")],
        )

    candidates = {
        item_id: ImageSyncCandidate(item_id, item_id, ImageSourceType.BASEINFO)
        for item_id in ("101", "102")
    }
    with patch.object(
        SGOBiz,
        "count_image_sync_items",
        AsyncMock(return_value=2),
    ), patch.object(
        SGOBiz,
        "_iter_image_item_batches",
        MagicMock(return_value=batches()),
    ), patch.object(
        SGOBiz,
        "_collect_image_candidates",
        AsyncMock(return_value=(candidates, [])),
    ), patch.object(
        SGOBiz,
        "_filter_missing_candidates",
        AsyncMock(return_value=(list(candidates.values()), 0)),
    ), patch.object(
        SGOBiz,
        "_store_zip_candidates",
        AsyncMock(side_effect=[(1, []), (1, [])]),
    ), patch.object(sgo_services, "sgo_image_zip_batch_size", 1):
        SGOBiz.token = "test-token"
        result = asyncio.run(
            SGOBiz.sync_images(
                item_id_list=["101", "102"],
                sync_scope="selected",
                progress_callback=progress.append,
            )
        )

    assert result["synced_image_count"] == 2
    assert [item["progress"] for item in progress] == [0, 50, 100]
    assert [item["processed_items"] for item in progress] == [0, 0, 2]
    assert [item["synced_image_count"] for item in progress] == [0, 1, 2]


def test_sync_images_limits_parallel_single_file_downloads():
    active = 0
    maximum_active = 0
    downloaded_raw_urls = []

    async def batches():
        yield ImageSyncItemBatch(
            requested_ids=[str(item_id) for item_id in range(101, 107)],
            items=[
                ImageSyncItem(str(item_id), f"CODE-{item_id}")
                for item_id in range(101, 107)
            ],
        )

    candidates = {
        f"file-{index}": ImageSyncCandidate(
            f"file-{index}",
            str(100 + index),
            ImageSourceType.BASEINFO,
        )
        for index in range(1, 7)
    }

    async def store_candidates(zip_candidates):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.02)
        downloaded_raw_urls.extend(
            candidate.raw_url for candidate in zip_candidates
        )
        active -= 1
        return len(zip_candidates), []

    with patch.object(
        SGOBiz,
        "count_image_sync_items",
        AsyncMock(return_value=6),
    ), patch.object(
        SGOBiz,
        "_iter_image_item_batches",
        MagicMock(return_value=batches()),
    ), patch.object(
        SGOBiz,
        "_collect_image_candidates",
        AsyncMock(return_value=(candidates, [])),
    ), patch.object(
        SGOBiz,
        "_filter_missing_candidates",
        AsyncMock(return_value=(list(candidates.values()), 0)),
    ), patch.object(
        SGOBiz,
        "_store_zip_candidates",
        side_effect=store_candidates,
    ), patch.object(
        sgo_services,
        "sgo_image_zip_batch_size",
        1,
    ), patch.object(
        sgo_services,
        "sgo_image_download_concurrency",
        2,
        create=True,
    ):
        SGOBiz.token = "test-token"
        result = asyncio.run(
            SGOBiz.sync_images(
                item_id_list=[str(item_id) for item_id in range(101, 107)],
                sync_scope="selected",
            )
        )

    assert result["synced_image_count"] == 6
    assert maximum_active == 2
    assert sorted(downloaded_raw_urls) == sorted(candidates)


def test_sync_images_deduplicates_requested_item_ids():
    assert asyncio.run(
        SGOBiz.count_image_sync_items(
            sync_scope="selected",
            item_id_list=["101", "101"],
        )
    ) == 1


def test_sync_images_empty_request_does_not_fetch_token():
    with patch.object(SGOBiz, "get_token") as get_token:
        SGOBiz.token = ""
        result = asyncio.run(SGOBiz.sync_images([]))

    get_token.assert_not_called()
    assert result["total_items"] == 0
    assert result["processed_items"] == 0


def test_scheduled_parts_sync_awaits_persistent_task_submission():
    manager = MagicMock()
    manager.start = AsyncMock(
        return_value={"task_id": "scheduled-task", "status": "pending"}
    )
    with patch.object(sgo_services, "sgo_sync_task_manager", manager):
        asyncio.run(SGOBiz._start_scheduled_parts_sync())

    manager.start.assert_awaited_once_with("parts", SGOBiz.sync_parts_items)


def test_sync_parts_items_records_invalid_source_id_without_stopping_task():
    progress = []

    async def capture_progress(payload):
        progress.append(payload)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def add_all(self, items):
            self.items = items

        async def commit(self):
            return None

    source_rows = [
        SimpleNamespace(id="invalid", maktx="bad", MATNR="bad"),
        SimpleNamespace(id="103", maktx=None, MATNR="missing-name"),
        SimpleNamespace(id="102", maktx="part", MATNR="code"),
    ]
    with patch.object(
        sgo_services,
        "SessionLocal",
        side_effect=FakeSession,
    ), patch.object(
        sgo_services,
        "sgo_sessionLocal",
        side_effect=FakeSession,
    ), patch.object(
        Items,
        "list_all_item_id_codes",
        AsyncMock(return_value=[(101, "existing")]),
    ), patch.object(
        SgoMaterielMasterplate,
        "list_sgo_items",
        AsyncMock(return_value=source_rows),
    ):
        result = asyncio.run(
            SGOBiz.sync_parts_items(progress_callback=capture_progress)
        )

    assert result["processed_items"] == 3
    assert result["created_count"] == 1
    assert result["fail_count"] == 2
    assert result["failed_item_ids"] == ["103", "invalid"]
    assert result["failure_details"] == [
        {
            "item_id": "103",
            "stage": "source_validation",
            "error_type": "InvalidSourceData",
            "error_message": "配件名称为空",
        },
        {
            "item_id": "invalid",
            "stage": "source_validation",
            "error_type": "InvalidSourceData",
            "error_message": "配件 ID 不是有效整数",
        }
    ]
    assert progress[-1]["progress"] == 100


def test_sync_parts_items_skips_existing_and_batch_duplicate_item_codes():
    class FakeSession:
        added_items = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def add_all(self, items):
            type(self).added_items = list(items)

        async def commit(self):
            return None

    source_rows = [
        SimpleNamespace(id="102", maktx="existing", MATNR="existing-code"),
        SimpleNamespace(id="103", maktx="older", MATNR=" new-code "),
        SimpleNamespace(id="104", maktx="newer", MATNR="new-code"),
    ]
    with patch.object(
        sgo_services,
        "SessionLocal",
        side_effect=FakeSession,
    ), patch.object(
        sgo_services,
        "sgo_sessionLocal",
        side_effect=FakeSession,
    ), patch.object(
        Items,
        "list_all_item_id_codes",
        AsyncMock(return_value=[(101, " Existing-Code ")]),
    ), patch.object(
        SgoMaterielMasterplate,
        "list_sgo_items",
        AsyncMock(return_value=source_rows),
    ):
        result = asyncio.run(SGOBiz.sync_parts_items())

    assert result["created_count"] == 1
    assert result["skipped_count"] == 2
    assert FakeSession.added_items[0].id == 104
    assert FakeSession.added_items[0].item_code == "new-code"


def test_sync_inquiry_history_maps_item_codes_and_reports_progress():
    progress = []

    async def capture_progress(payload):
        progress.append(payload)
    source_rows = [
        {
            "inquiry_id": "inq-1",
            "inquiry_num": "CX001",
            "vehicle": "SFE27_CRH380A统",
            "train_no": "2777",
            "car_num": "01",
            "inquiry_item_name": "盖板",
            "subordinate_component": "座椅",
            "remark": "01车座椅盖板",
            "return_item_name": "座椅中扶手盖板",
            "return_item_code": "code-1",
            "inquiry_time": "2023-05-18 15:26:35",
        },
        {
            "inquiry_id": "inq-2",
            "inquiry_num": "CX002",
            "vehicle": "SFE28",
            "train_no": "2334",
            "car_num": "07",
            "inquiry_item_name": "滤网",
            "subordinate_component": "电茶炉",
            "remark": "电茶炉进水电磁阀前滤网",
            "return_item_name": "进水滤网",
            "return_item_code": "code-2",
            "inquiry_time": "2023-05-19 15:26:35",
        },
    ]

    async def upsert(payloads, *, batch_size):
        assert batch_size == 50
        assert payloads[0]["item_id"] == 101
        assert payloads[0]["vehicle_batch"] == "SFE27"
        assert payloads[1]["item_id"] is None
        assert payloads[1]["vehicle_batch"] == "SFE28"
        return {"processed_count": len(payloads), "history_ids": [501, 502]}

    with patch.object(
        SGOBiz,
        "_list_sgo_inquiry_history_source_rows",
        AsyncMock(return_value=source_rows),
    ), patch.object(
        SGOBiz,
        "_list_main_item_ids_by_codes",
        AsyncMock(return_value={"code-1": 101}),
    ), patch.object(
        SGOBiz,
        "_upsert_inquiry_history_payloads",
        AsyncMock(side_effect=upsert),
    ):
        result = asyncio.run(
            SGOBiz.sync_inquiry_history(
                limit=2,
                batch_size=50,
                progress_callback=capture_progress,
            )
        )

    assert result == {
        "total_items": 2,
        "processed_items": 2,
        "success_count": 2,
        "fail_count": 0,
        "created_count": 2,
        "skipped_count": 0,
        "synced_image_count": 0,
        "failed_item_ids": [],
    }
    assert [item["progress"] for item in progress] == [0, 100]
    assert progress[-1]["current_item_id"] == "inq-2"


def test_sync_inquiry_history_enqueues_semantic_index_after_commit():
    source_rows = [
        {
            "inquiry_id": "inq-1",
            "inquiry_num": "CX001",
            "vehicle": "SFE27",
            "train_no": None,
            "car_num": None,
            "inquiry_item_name": "监控室对面窗帘",
            "subordinate_component": None,
            "remark": None,
            "return_item_name": "窗帘组件",
            "return_item_code": "code-1",
            "inquiry_time": None,
        }
    ]
    enqueue_semantic = AsyncMock(
        return_value={"task_id": "semantic-task-1", "status": "pending"}
    )

    with patch.object(
        SGOBiz,
        "_list_sgo_inquiry_history_source_rows",
        AsyncMock(return_value=source_rows),
    ), patch.object(
        SGOBiz,
        "_list_main_item_ids_by_codes",
        AsyncMock(return_value={"code-1": 101}),
    ), patch.object(
        SGOBiz,
        "_upsert_inquiry_history_payloads",
        AsyncMock(return_value={"processed_count": 1, "history_ids": [501]}),
    ), patch.object(
        SGOBiz,
        "_enqueue_inquiry_semantic_index",
        enqueue_semantic,
    ):
        result = asyncio.run(
            SGOBiz.sync_inquiry_history(_sync_task_id="sync-task-1")
        )

    assert result["semantic_index_task_id"] == "semantic-task-1"
    assert result["semantic_index_warning"] is None
    enqueue_semantic.assert_awaited_once_with(
        [501],
        source_sync_task_id="sync-task-1",
    )
