import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.item import ItemHierarchyRelation
from csrcqsf.modules.railway_parts.schemas.search import SearchItem
from csrcqsf.modules.railway_parts.services import search_hierarchy_service


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def test_enrich_search_items_returns_all_unique_parent_and_child_names():
    rows = [
        SimpleNamespace(materiel_code="A", parent_materiel_code="P", parent_materiel_name="父组件", materiel_name="当前件", vehicle_batch="SFE27"),
        SimpleNamespace(materiel_code="A", parent_materiel_code="P", parent_materiel_name="父组件", materiel_name="当前件", vehicle_batch="SFE27"),
        SimpleNamespace(materiel_code="A", parent_materiel_code="Q", parent_materiel_name="父配件", materiel_name="当前件", vehicle_batch="SFE28"),
        SimpleNamespace(materiel_code="B", parent_materiel_code="A", parent_materiel_name="当前件", materiel_name="子组件", vehicle_batch="SFE27"),
        SimpleNamespace(materiel_code="A", parent_materiel_code="A", parent_materiel_name="当前件", materiel_name="当前件", vehicle_batch="SFE27"),
    ]
    items = [SearchItem(item_id="1", item_code="A", item_name="当前件")]
    query = AsyncMock(return_value=rows)
    with patch.object(search_hierarchy_service, "SessionLocal", return_value=FakeSession()), patch.object(
        ItemHierarchyRelation, "list_search_relations", query
    ):
        asyncio.run(search_hierarchy_service.enrich_search_items(items))

    query.assert_awaited_once()
    assert [(part.item_code, part.item_name) for part in items[0].parent_parts] == [
        ("P", "父组件"), ("Q", "父配件")
    ]
    assert [(part.item_code, part.item_name) for part in items[0].child_parts] == [
        ("B", "子组件")
    ]


def test_enrich_search_items_filters_vehicle_and_handles_missing_relations():
    rows = [
        SimpleNamespace(materiel_code="A", parent_materiel_code="P", parent_materiel_name="父组件", materiel_name="当前件", vehicle_batch="SFE27"),
        SimpleNamespace(materiel_code="A", parent_materiel_code="Q", parent_materiel_name="另一车型父组件", materiel_name="当前件", vehicle_batch="SFE28"),
    ]
    items = [
        SearchItem(item_id="1", item_code="A"),
        SearchItem(item_id="2", item_code="MISSING"),
    ]
    with patch.object(search_hierarchy_service, "SessionLocal", return_value=FakeSession()), patch.object(
        ItemHierarchyRelation, "list_search_relations", AsyncMock(return_value=rows)
    ):
        asyncio.run(search_hierarchy_service.enrich_search_items(items, vehicle_batch="SFE27"))

    assert [part.item_code for part in items[0].parent_parts] == ["P"]
    assert items[1].parent_parts == []
    assert items[1].child_parts == []
