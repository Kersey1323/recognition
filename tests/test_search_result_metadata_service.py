import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.item import ItemSupplier, Items
from csrcqsf.models.orm.search_history import SearchResults
from csrcqsf.modules.railway_parts.services.search_result_metadata_service import (
    enrich_search_result_metadata,
)


def test_enrich_search_result_metadata_reads_persisted_item_and_supplier_fields():
    search_results = SearchResults(
        items=[
            {
                "item_id": "1595252215646867456",
                "item_code": "19010004899",
                "item_name": "快捷锁",
                "similar": 0.99,
            }
        ]
    )
    item = SimpleNamespace(
        id=1595252215646867456,
        parts_model="规格 A",
        material_quality="不锈钢",
    )
    supplier = SimpleNamespace(
        item_id=1595252215646867456,
        supplier_code="S001",
        supplier_name="供应商甲",
        supplier_item_code="V001",
        supplier_item_name="供方快捷锁",
        supplier_parts_model="供方规格 A",
        model_number="MODEL-A",
        manufacturer="制造商甲",
    )

    async def _yield_items(*args, **kwargs):
        yield item

    session = AsyncMock()
    with (
        patch.object(Items, "get_item_by_id_list", _yield_items),
        patch.object(
            ItemSupplier,
            "list_active_by_item_ids",
            AsyncMock(return_value=[supplier]),
        ),
    ):
        asyncio.run(enrich_search_result_metadata(session, search_results))

    result_item = search_results.items[0]
    assert result_item.parts_model == "规格 A"
    assert result_item.material_quality == "不锈钢"
    assert result_item.suppliers[0].supplier_name == "供应商甲"
    assert result_item.suppliers[0].model_number == "MODEL-A"
    assert result_item.suppliers[0].manufacturer == "制造商甲"


def test_enrich_search_result_metadata_leaves_unknown_item_fields_empty():
    search_results = SearchResults(
        items=[
            {
                "item_id": "1",
                "item_code": "UNKNOWN",
                "item_name": "未知配件",
                "similar": 0.5,
            }
        ]
    )

    async def _yield_items(*args, **kwargs):
        if False:
            yield None

    session = AsyncMock()
    with (
        patch.object(Items, "get_item_by_id_list", _yield_items),
        patch.object(
            ItemSupplier,
            "list_active_by_item_ids",
            AsyncMock(return_value=[]),
        ),
    ):
        asyncio.run(enrich_search_result_metadata(session, search_results))

    result_item = search_results.items[0]
    assert result_item.parts_model is None
    assert result_item.material_quality is None
    assert result_item.suppliers == []
