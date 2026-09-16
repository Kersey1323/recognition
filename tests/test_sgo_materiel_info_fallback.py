import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.sgo_external import SgoMaterielMasterplate
from csrcqsf.modules.sgo import services as sgo_services


def test_template_query_uses_info_only_for_missing_fields_and_includes_a1_a5_a9():
    from sqlalchemy.dialects import postgresql

    stmt = SgoMaterielMasterplate.sync_items_statement()
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "sgo_materiel_info" in sql
    assert "materiel_info_id" in sql
    assert all(board in sql for board in ("A1", "A5", "A9"))
    assert "MAKTX" in sql and "WRKST" in sql and "ZEINR" in sql


def test_same_code_prefers_a1_template_before_a5_and_a9():
    from csrcqsf.modules.sgo.services import _sync_template_sort_key

    templates = [
        SimpleNamespace(id="300", column_id="A9"),
        SimpleNamespace(id="200", column_id="A5"),
        SimpleNamespace(id="100", column_id="A1"),
        SimpleNamespace(id="101", column_id="A1"),
    ]
    templates.sort(key=_sync_template_sort_key)
    assert [row.id for row in templates] == ["101", "100", "200", "300"]


def test_sync_parts_uses_fallback_name_model_and_drawing_without_overwriting_existing_name():
    from csrcqsf.models.orm.item import Items, ItemSupplier
    from csrcqsf.models.orm.sgo_external import SgoMaterielSupplier
    from csrcqsf.modules.sgo.services import SGOBiz

    class FakeSession:
        inserted = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def add_all(self, items):
            type(self).inserted = list(items)

        async def commit(self):
            pass

    update = AsyncMock()
    source = [
        SimpleNamespace(id="101", MATNR="CODE-1", maktx="补齐名称", wrkst="规格A", zeinr="图号A", material_quality=None),
        SimpleNamespace(id="102", MATNR="CODE-2", maktx="新配件", wrkst="规格B", zeinr="图号B", material_quality=None),
    ]
    with patch.object(sgo_services, "SessionLocal", side_effect=FakeSession), patch.object(
        sgo_services, "sgo_sessionLocal", side_effect=FakeSession
    ), patch.object(Items, "list_all_item_sync_state", AsyncMock(return_value=[
        SimpleNamespace(id=101, item_code="CODE-1", item_name="", parts_model=None, material_quality=None, drawing_number=None),
    ])), patch.object(ItemSupplier, "list_sync_state", AsyncMock(return_value=[])), patch.object(
        SgoMaterielMasterplate, "list_sgo_items", AsyncMock(return_value=source)
    ), patch.object(SgoMaterielSupplier, "list_sgo_suppliers", AsyncMock(return_value=[])), patch.object(
        Items, "update_sgo_metadata", update
    ), patch.object(ItemSupplier, "upsert_from_sgo", AsyncMock()), patch.object(
        ItemSupplier, "delete_by_source_ids", AsyncMock()
    ), patch.object(SGOBiz, "sync_parts_hierarchy", AsyncMock(return_value={
        "hierarchy_total_count": 0, "synced_hierarchy_count": 0,
        "deleted_hierarchy_count": 0, "unresolved_vehicle_count": 0,
        "invalid_hierarchy_count": 0,
    })):
        asyncio.run(SGOBiz.sync_parts_items())

    assert FakeSession.inserted[0].item_name == "新配件"
    assert FakeSession.inserted[0].parts_model == "规格B"
    assert FakeSession.inserted[0].drawing_number == "图号B"
    assert update.await_args.args[1][0]["item_name"] == "补齐名称"
    assert update.await_args.args[1][0]["drawing_number"] == "图号A"
