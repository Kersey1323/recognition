import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.sgo_external import SgoMaterielMasterplate
from csrcqsf.modules.sgo.services import SGOBiz


sgo_services = importlib.import_module("csrcqsf.modules.sgo.services")


def test_sync_images_continues_after_single_item_failure_and_reports_progress():
    progress = []

    async def base_images(item_ids):
        if item_ids == ["102"]:
            raise RuntimeError("source image failed")
        return 2

    with patch.object(SGOBiz, "get_baseimage_id_from_db", AsyncMock(side_effect=base_images)), \
         patch.object(SGOBiz, "get_inquery_code_pic_from_db", AsyncMock(return_value=1)):
        SGOBiz.token = "test-token"
        result = asyncio.run(
            SGOBiz.sync_images(
                ["101", "102", "103"],
                progress_callback=progress.append,
            )
        )

    assert result == {
        "total_items": 3,
        "processed_items": 3,
        "success_count": 2,
        "fail_count": 1,
        "created_count": 6,
        "skipped_count": 0,
        "synced_image_count": 6,
        "failed_item_ids": ["102"],
        "failure_details": [
            {
                "item_id": "102",
                "stage": "base_images",
                "error_type": "RuntimeError",
                "error_message": "source image failed",
            }
        ],
    }
    assert [item["progress"] for item in progress] == [33, 66, 100]
    assert progress[-1]["estimated_remaining_seconds"] == 0
    assert progress[-1]["failure_details"] == result["failure_details"]


def test_sync_images_deduplicates_requested_item_ids():
    with patch.object(SGOBiz, "get_baseimage_id_from_db", AsyncMock(return_value=0)) as base, \
         patch.object(SGOBiz, "get_inquery_code_pic_from_db", AsyncMock(return_value=0)):
        SGOBiz.token = "test-token"
        result = asyncio.run(SGOBiz.sync_images(["101", "101"]))

    assert result["total_items"] == 1
    base.assert_awaited_once_with(["101"])


def test_sync_images_empty_request_does_not_fetch_token():
    with patch.object(SGOBiz, "get_token") as get_token:
        SGOBiz.token = ""
        result = asyncio.run(SGOBiz.sync_images([]))

    get_token.assert_not_called()
    assert result["total_items"] == 0
    assert result["processed_items"] == 0


def test_sync_parts_items_records_invalid_source_id_without_stopping_task():
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
        result = asyncio.run(SGOBiz.sync_parts_items())

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
        return len(payloads)

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
                progress_callback=progress.append,
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
