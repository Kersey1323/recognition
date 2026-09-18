import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.sgo_external import (
    SgoMaterielInfoTree,
    SgoMaterielMasterplate,
    SgoMaterielSupplier,
)
from csrcqsf.modules.sgo import services as sgo_services


def test_template_query_uses_info_only_for_missing_fields_and_includes_a1_a3_a5():
    from sqlalchemy.dialects import postgresql

    stmt = SgoMaterielMasterplate.sync_items_statement()
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "sgo_materiel_info" in sql
    assert "materiel_info_id" in sql
    assert all(board in sql for board in ("A1", "A3", "A5"))
    assert "A9" not in sql
    assert "MAKTX" in sql and "WRKST" in sql and "ZEINR" in sql


def test_same_code_prefers_a1_template_before_a3_and_a5():
    from csrcqsf.modules.sgo.services import _sync_template_sort_key

    templates = [
        SimpleNamespace(id="300", column_id="A5"),
        SimpleNamespace(id="200", column_id="A3"),
        SimpleNamespace(id="100", column_id="A1"),
        SimpleNamespace(id="101", column_id="A1"),
    ]
    templates.sort(key=_sync_template_sort_key)
    assert [row.id for row in templates] == ["101", "100", "200", "300"]


def test_supplier_and_hierarchy_queries_exclude_a9():
    from sqlalchemy.dialects import postgresql

    statements = (
        SgoMaterielSupplier.sync_suppliers_statement(),
        SgoMaterielInfoTree.sync_hierarchy_statement(),
    )
    for statement in statements:
        sql = str(statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        ))
        assert all(board in sql for board in ("A1", "A3", "A5"))
        assert "A9" not in sql


def test_a9_cleanup_candidates_exclude_codes_shared_with_sync_boards():
    source_rows = [
        ("A9", "DEMO-ONLY"),
        ("A9", "SHARED"),
        ("A1", "SHARED"),
        ("A3", "METRO"),
        ("A5", "OTHER"),
    ]

    scope = sgo_services._partition_a9_cleanup_codes(source_rows)

    assert scope["a9_codes"] == {"DEMO-ONLY", "SHARED"}
    assert scope["shared_codes"] == {"SHARED"}
    assert scope["exclusive_codes"] == {"DEMO-ONLY"}


def test_a9_cleanup_keeps_item_when_external_artifact_cleanup_fails():
    from csrcqsf.modules.sgo.services import A9CleanupCandidate, SGOBiz

    candidates = [
        A9CleanupCandidate(item_id=101, item_code="A9-OK", item_name="可清理"),
        A9CleanupCandidate(item_id=102, item_code="A9-FAIL", item_name="需重试"),
    ]
    delete_local = AsyncMock()
    progress = AsyncMock()

    async def cleanup_external(candidate):
        if candidate.item_id == 102:
            raise RuntimeError("Milvus unavailable")

    with patch.object(
        SGOBiz,
        "_load_a9_cleanup_scope",
        AsyncMock(return_value={"local_items": [object(), object()]}),
    ), patch.object(
        SGOBiz,
        "_load_a9_cleanup_candidates",
        AsyncMock(return_value=candidates),
    ), patch.object(
        SGOBiz,
        "_cleanup_a9_external_artifacts",
        side_effect=cleanup_external,
    ), patch.object(
        SGOBiz,
        "_delete_a9_local_records",
        delete_local,
    ):
        result = asyncio.run(SGOBiz.cleanup_a9_demo_data(progress_callback=progress))

    delete_local.assert_awaited_once_with([101])
    assert result["success_count"] == 1
    assert result["fail_count"] == 1
    assert result["failure_details"][0]["item_code"] == "A9-FAIL"
    assert result["failure_details"][0]["error_code"] == "A9_CLEANUP_FAILED"


def test_a9_cleanup_skips_vector_services_for_unindexed_item():
    from csrcqsf.modules.sgo.services import A9CleanupCandidate, SGOBiz

    with patch.object(
        sgo_services.MilvusManager,
        "delete_part_index",
        AsyncMock(),
    ) as delete_legacy, patch.object(
        sgo_services.MilvusManager,
        "delete_hp_part_index",
        AsyncMock(),
    ) as delete_hp, patch.object(
        sgo_services.RailwayPartsManager,
        "delete_v2_index",
        AsyncMock(),
    ) as delete_v2:
        asyncio.run(SGOBiz._cleanup_a9_external_artifacts(
            A9CleanupCandidate(item_id=101, item_code="A9-PLAIN", item_name="未索引")
        ))

    delete_legacy.assert_not_awaited()
    delete_hp.assert_not_awaited()
    delete_v2.assert_not_awaited()


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
