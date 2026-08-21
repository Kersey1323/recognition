import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.sgo_external import (
    SgoCodeInquiry,
    SgoMaterielFileImg,
)
from csrcqsf.modules.sgo import services as sgo_services
from csrcqsf.modules.sgo.schemas import ImageSourceType
from csrcqsf.modules.sgo.services import SGOBiz


class FakeSessionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def test_selected_image_item_batches_deduplicate_and_preserve_request_order():
    async def scenario():
        with patch.object(sgo_services, "SessionLocal", return_value=FakeSessionContext()), patch.object(
            Items,
            "list_item_id_codes_by_ids",
            AsyncMock(return_value=[(1, "A"), (2, "B")]),
        ) as list_items:
            batches = [
                batch
                async for batch in SGOBiz._iter_image_item_batches(
                    sync_scope="selected",
                    item_id_list=["2", "1", "2", "404"],
                    batch_size=10,
                )
            ]

        assert len(batches) == 1
        assert batches[0].requested_ids == ["2", "1", "404"]
        assert [item.item_id for item in batches[0].items] == ["2", "1"]
        list_items.assert_awaited_once_with(list_items.call_args.args[0], [2, 1, 404])

    asyncio.run(scenario())


def test_all_image_item_batches_use_keyset_pagination():
    async def scenario():
        with patch.object(sgo_services, "SessionLocal", return_value=FakeSessionContext()), patch.object(
            Items,
            "list_item_id_codes_after",
            AsyncMock(
                side_effect=[
                    [(10, "A"), (20, "B")],
                    [(30, "C")],
                    [],
                ]
            ),
        ) as list_page:
            batches = [
                batch
                async for batch in SGOBiz._iter_image_item_batches(
                    sync_scope="all",
                    item_id_list=[],
                    batch_size=2,
                )
            ]

        assert [[item.item_id for item in batch.items] for batch in batches] == [
            ["10", "20"],
            ["30"],
        ]
        assert [call.args[1:] for call in list_page.await_args_list] == [
            (0, 2),
            (20, 2),
            (30, 2),
        ]

    asyncio.run(scenario())


def test_collect_image_candidates_queries_each_source_once_per_batch():
    async def scenario():
        items = [
            sgo_services.ImageSyncItem(item_id="1", item_code="A"),
            sgo_services.ImageSyncItem(item_id="2", item_code="B"),
        ]
        base_rows = [
            SimpleNamespace(
                masterplate_id="1",
                file_src=json.dumps([{"url": "name_base-file-1"}]),
            )
        ]
        inquiry_rows = [
            (json.dumps([{"url": "name_detail-file-2"}]), None, "B")
        ]

        with patch.object(sgo_services, "sgo_sessionLocal", return_value=FakeSessionContext()), patch.object(
            SgoMaterielFileImg,
            "list_image_file",
            AsyncMock(return_value=base_rows),
        ) as list_base, patch.object(
            SgoCodeInquiry,
            "list_image_files_by_item_codes",
            AsyncMock(return_value=inquiry_rows),
        ) as list_inquiry:
            candidates, failures = await SGOBiz._collect_image_candidates(items)

        assert failures == []
        assert candidates["base-file-1"].item_id == "1"
        assert candidates["base-file-1"].image_source == ImageSourceType.BASEINFO
        assert candidates["detail-file-2"].item_id == "2"
        assert candidates["detail-file-2"].image_source == ImageSourceType.INQUERY
        assert list_base.await_count == 1
        assert list_inquiry.await_count == 1

    asyncio.run(scenario())
