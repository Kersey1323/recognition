import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.sgo_external import (
    SgoMaterielInfoTree,
    SgoMaterielMasterplate,
    SgoMaterielSupplier,
)
from csrcqsf.modules.sgo import services as sgo_services


def test_template_query_uses_info_only_for_missing_fields_and_includes_only_a1():
    from sqlalchemy.dialects import postgresql

    stmt = SgoMaterielMasterplate.sync_items_statement()
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "sgo_materiel_info" in sql
    assert "materiel_info_id" in sql
    assert "A1" in sql
    assert all(board not in sql for board in ("A3", "A5", "A9"))
    assert "MAKTX" in sql and "WRKST" in sql and "ZEINR" in sql


def test_same_a1_code_prefers_newer_template_id():
    from csrcqsf.modules.sgo.services import _sync_template_sort_key

    templates = [
        SimpleNamespace(id="100", column_id="A1"),
        SimpleNamespace(id="101", column_id="A1"),
    ]
    templates.sort(key=_sync_template_sort_key)
    assert [row.id for row in templates] == ["101", "100"]


def test_supplier_and_hierarchy_queries_include_only_a1():
    from sqlalchemy.dialects import postgresql

    statements = (
        SgoMaterielSupplier.sync_suppliers_statement(),
        SgoMaterielInfoTree.sync_hierarchy_statement(),
    )
    for statement in statements:
        sql = str(statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        ))
        assert "A1" in sql
        assert all(board not in sql for board in ("A3", "A5", "A9"))


def test_non_a1_cleanup_preserves_codes_shared_with_a1():
    source_rows = [
        ("A9", "DEMO-ONLY"),
        ("A9", "SHARED"),
        ("A1", "SHARED"),
        ("A3", "METRO"),
        ("A5", "OTHER"),
    ]

    scope = sgo_services._partition_non_a1_cleanup_codes(source_rows)

    assert scope["non_a1_codes"] == {"DEMO-ONLY", "SHARED", "METRO", "OTHER"}
    assert scope["shared_codes"] == {"SHARED"}
    assert scope["exclusive_codes"] == {"DEMO-ONLY", "METRO", "OTHER"}


def test_non_a1_cleanup_scope_protects_a1_and_uploaded_source_video():
    local_rows = [
        SimpleNamespace(
            id=101, item_code="A1-KEEP", item_name="A1 配件",
            source_video_path=None, image_index_num=0, feature_index_num=0,
            has_v2_index=0, time_updated=None,
        ),
        SimpleNamespace(
            id=102, item_code="A5-VIDEO", item_name="已采集配件",
            source_video_path="bfr-3d-videos/raw.mp4", image_index_num=1,
            feature_index_num=1, has_v2_index=1, time_updated=None,
        ),
        SimpleNamespace(
            id=103, item_code="A5-DELETE", item_name="待清理配件",
            source_video_path=None, image_index_num=0, feature_index_num=0,
            has_v2_index=0, time_updated=None,
        ),
    ]

    scope = sgo_services._build_non_a1_cleanup_scope({"a1-keep"}, local_rows)

    assert [row.id for row in scope.a1_items] == [101]
    assert [row.id for row in scope.protected_items] == [102]
    assert [row.id for row in scope.candidate_items] == [103]
    assert len(scope.preview_token) == 64


def test_non_a1_cleanup_keeps_item_when_external_artifact_cleanup_fails():
    from csrcqsf.modules.sgo.services import PartsCleanupCandidate, SGOBiz

    candidates = [
        PartsCleanupCandidate(item_id=101, item_code="A5-OK", item_name="可清理"),
        PartsCleanupCandidate(item_id=102, item_code="A5-FAIL", item_name="需重试"),
    ]
    delete_local = AsyncMock(return_value=[101])
    progress = AsyncMock()

    async def cleanup_external(candidate):
        if candidate.item_id == 102:
            raise RuntimeError("Milvus unavailable")

    with patch.object(
        SGOBiz,
        "_load_non_a1_cleanup_scope",
        AsyncMock(return_value=SimpleNamespace(
            candidate_items=[object(), object()], preview_token="preview-token"
        )),
    ), patch.object(
        SGOBiz,
        "_load_cleanup_candidates",
        AsyncMock(return_value=candidates),
    ), patch.object(
        SGOBiz,
        "_cleanup_candidate_external_indexes",
        side_effect=cleanup_external,
    ), patch.object(
        SGOBiz,
        "_delete_cleanup_local_records",
        delete_local,
    ):
        result = asyncio.run(SGOBiz.cleanup_non_a1_data(
            preview_token="preview-token",
            progress_callback=progress,
        ))

    delete_local.assert_awaited_once_with([101])
    assert result["success_count"] == 1
    assert result["fail_count"] == 1
    assert result["failure_details"][0]["item_code"] == "A5-FAIL"
    assert result["failure_details"][0]["error_code"] == "NON_A1_CLEANUP_FAILED"


def test_non_a1_cleanup_skips_vector_services_for_unindexed_item():
    from csrcqsf.modules.sgo.services import PartsCleanupCandidate, SGOBiz

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
        asyncio.run(SGOBiz._cleanup_candidate_external_indexes(
            PartsCleanupCandidate(item_id=101, item_code="A5-PLAIN", item_name="未索引")
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
    })), patch.object(
        SGOBiz,
        "sync_parts_vehicle_batch",
        AsyncMock(return_value={
            "vehicle_item_count": 0,
            "updated_vehicle_item_count": 0,
        }),
    ):
        asyncio.run(SGOBiz.sync_parts_items())

    assert FakeSession.inserted[0].item_name == "新配件"
    assert FakeSession.inserted[0].parts_model == "规格B"
    assert FakeSession.inserted[0].drawing_number == "图号B"
    assert update.await_args.args[1][0]["item_name"] == "补齐名称"
    assert update.await_args.args[1][0]["drawing_number"] == "图号A"
