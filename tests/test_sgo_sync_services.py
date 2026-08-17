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
    }
    assert [item["progress"] for item in progress] == [33, 66, 100]
    assert progress[-1]["estimated_remaining_seconds"] == 0


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
        "list_all_item_ids",
        AsyncMock(return_value=[101]),
    ), patch.object(
        SgoMaterielMasterplate,
        "list_sgo_items",
        AsyncMock(return_value=source_rows),
    ):
        result = asyncio.run(SGOBiz.sync_parts_items())

    assert result["processed_items"] == 2
    assert result["created_count"] == 1
    assert result["fail_count"] == 1
    assert result["failed_item_ids"] == ["invalid"]
