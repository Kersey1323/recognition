import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import mysql

from csrcqsf.models.orm.item import ItemHierarchyRelation
from csrcqsf.models.orm.search_history import SearchParameters, SearchResultItem, SearchResults
from csrcqsf.modules.railway_parts.schemas.parts import GetItemDetailRes
from csrcqsf.modules.railway_parts.schemas.search import SearchItem
from csrcqsf.modules.railway_parts.services import search_hierarchy_service


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RecordingSession:
    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(all=lambda: [])


def test_hierarchy_relation_query_only_reads_business_columns():
    session = RecordingSession()

    asyncio.run(ItemHierarchyRelation.list_search_relations(session, ["A"]))

    sql = str(
        session.statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "item_hierarchy_relation.column_id IN ('A1', 'A3', 'A5')" in sql
    assert "'A9'" not in sql


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


def test_history_detail_enriches_current_and_previous_results_with_their_vehicle_filters():
    from csrcqsf.modules.railway_parts.routes import search_routes

    current = SearchResultItem(item_id="1", item_code="A", similar=0.9)
    previous = SearchResultItem(item_id="2", item_code="A", similar=0.8)
    detail = SimpleNamespace(
        result=SearchResults(items=[current]),
        search_parameter=SearchParameters(vehicle_batch="SFE27"),
        previous_result=SearchResults(items=[previous]),
        previous_search_parameter=SearchParameters(vehicle_batch="SFE28"),
    )
    rows = [
        SimpleNamespace(materiel_code="A", parent_materiel_code="P27", parent_materiel_name="车型27父件", materiel_name="部件", vehicle_batch="SFE27"),
        SimpleNamespace(materiel_code="A", parent_materiel_code="P28", parent_materiel_name="车型28父件", materiel_name="部件", vehicle_batch="SFE28"),
    ]
    with patch.object(search_routes.RailwayPartsManager, "get_v2_search_history_detail", AsyncMock(return_value=detail)), patch.object(
        search_hierarchy_service, "SessionLocal", return_value=FakeSession()
    ), patch.object(ItemHierarchyRelation, "list_search_relations", AsyncMock(return_value=rows)):
        result = asyncio.run(search_routes.get_v2_search_history_detail(
            search_routes.SearchHistoryDetailReq(history_id="123")
        ))

    assert [(part.item_code, part.item_name) for part in result.result.items[0].parent_parts] == [("P27", "车型27父件")]
    assert [part.item_code for part in result.previous_result.items[0].parent_parts] == ["P28"]
    assert "parent_parts" in SearchResultItem.schema()["properties"]
    assert "child_parts" in SearchResultItem.schema()["properties"]


def test_item_detail_returns_direct_parents_and_children_without_vehicle_filter():
    from csrcqsf.modules.railway_parts.routes import parts_routes

    detail = GetItemDetailRes(
        ply_url=None, height=None, length=None, width=None, weight=None,
        video_path=None, name="当前件", item_code="A", id="1",
        created_at="2026-09-16", updated_at="2026-09-16",
        parent_item_name=None, parent_item_code=None, parent_item_id=None,
        size_str=None,
    )
    rows = [
        SimpleNamespace(materiel_code="A", parent_materiel_code="P", parent_materiel_name="父件", materiel_name="当前件", vehicle_batch="SFE27"),
        SimpleNamespace(materiel_code="B", parent_materiel_code="A", parent_materiel_name="当前件", materiel_name="子件", vehicle_batch="SFE28"),
    ]
    with patch.object(parts_routes.RailwayPartsManager, "get_item_detail", AsyncMock(return_value=detail)), patch.object(
        search_hierarchy_service, "SessionLocal", return_value=FakeSession()
    ), patch.object(ItemHierarchyRelation, "list_search_relations", AsyncMock(return_value=rows)):
        result = asyncio.run(parts_routes.get_item_image_detail(parts_routes.GetItemDetailReq(item_id="1")))

    assert [(part.item_code, part.item_name) for part in result.parent_parts] == [("P", "父件")]
    assert [(part.item_code, part.item_name) for part in result.child_parts] == [("B", "子件")]
    assert "parent_parts" in GetItemDetailRes.schema()["properties"]
    assert "child_parts" in GetItemDetailRes.schema()["properties"]


def test_hierarchy_item_detail_includes_virtual_node_and_vehicle_filtered_relations():
    from csrcqsf.modules.railway_parts.routes import parts_routes

    rows = [
        SimpleNamespace(materiel_code="A124", materiel_name="底板组件", parent_materiel_code="A12", parent_materiel_name="设备舱", vehicle_batch="E27"),
        SimpleNamespace(materiel_code="B", materiel_name="下部盖板", parent_materiel_code="A124", parent_materiel_name="底板组件", vehicle_batch="E27"),
        SimpleNamespace(materiel_code="A124", materiel_name="底板组件(另一车型)", parent_materiel_code="P", parent_materiel_name="另一父件", vehicle_batch="E01"),
    ]
    with patch.object(search_hierarchy_service, "SessionLocal", return_value=FakeSession()), patch.object(
        ItemHierarchyRelation, "list_search_relations", AsyncMock(return_value=rows)
    ):
        detail = asyncio.run(parts_routes.get_hierarchy_item_detail(
            parts_routes.HierarchyItemDetailReq(item_code=" A124 ", vehicle_batch="E27")
        ))
        all_detail = asyncio.run(parts_routes.get_hierarchy_item_detail(
            parts_routes.HierarchyItemDetailReq(item_code="A124")
        ))

    assert detail.item_code == "A124"
    assert detail.item_name == "底板组件"
    assert detail.item_names == ["底板组件"]
    assert detail.vehicle_batches == ["E27"]
    assert [(part.item_code, part.item_name) for part in detail.parent_parts] == [("A12", "设备舱")]
    assert [(part.item_code, part.item_name) for part in detail.child_parts] == [("B", "下部盖板")]
    assert all_detail.item_names == ["底板组件", "底板组件(另一车型)"]
    assert all_detail.vehicle_batches == ["E01", "E27"]


def test_hierarchy_item_detail_unknown_code_returns_404():
    from csrcqsf.modules.railway_parts.routes import parts_routes

    with patch.object(search_hierarchy_service, "SessionLocal", return_value=FakeSession()), patch.object(
        ItemHierarchyRelation, "list_search_relations", AsyncMock(return_value=[])
    ), pytest.raises(HTTPException) as error:
        asyncio.run(parts_routes.get_hierarchy_item_detail(
            parts_routes.HierarchyItemDetailReq(item_code="UNKNOWN")
        ))

    assert error.value.status_code == 404


def test_hierarchy_item_detail_supports_parent_only_node_and_rejects_blank_code():
    rows = [
        SimpleNamespace(materiel_code="B", materiel_name="子件", parent_materiel_code="VIRTUAL", parent_materiel_name="虚拟装配件", vehicle_batch=None),
    ]
    with patch.object(search_hierarchy_service, "SessionLocal", return_value=FakeSession()), patch.object(
        ItemHierarchyRelation, "list_search_relations", AsyncMock(return_value=rows)
    ):
        detail = asyncio.run(search_hierarchy_service.get_hierarchy_item_detail("VIRTUAL"))

    assert detail.item_name == "虚拟装配件"
    assert detail.parent_parts == []
    assert [(part.item_code, part.item_name) for part in detail.child_parts] == [("B", "子件")]
    assert detail.vehicle_batches == []

    from csrcqsf.modules.railway_parts.schemas.parts import HierarchyItemDetailReq
    with pytest.raises(ValidationError):
        HierarchyItemDetailReq(item_code="   ")
