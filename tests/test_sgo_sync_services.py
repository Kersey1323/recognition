import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from csrcqsf.models.orm.item import ItemHierarchyRelation, ItemSupplier, Items
from csrcqsf.models.orm.sgo_external import (
    SgoMaterielInfoTree,
    SgoMaterielMasterplate,
    SgoMaterielSupplier,
    SgoMaterielVehicle,
)
from csrcqsf.modules.sgo.schemas import ImageSourceType
from csrcqsf.modules.sgo.services import (
    ImageSyncCandidate,
    ImageSyncItem,
    ImageSyncItemBatch,
    SGOBiz,
)


sgo_services = importlib.import_module("csrcqsf.modules.sgo.services")

EMPTY_HIERARCHY_RESULT = {
    "hierarchy_total_count": 0,
    "synced_hierarchy_count": 0,
    "deleted_hierarchy_count": 0,
    "unresolved_vehicle_count": 0,
    "invalid_hierarchy_count": 0,
}


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_list_inquiry_uses_persisted_index_state_without_scanning_milvus():
    main_session = AsyncMock()
    sgo_session = AsyncMock()
    indexed_codes = ["A001", "A002"]
    inquiry_rows = [SimpleNamespace(inquiry_id="Q001")]
    expected = SimpleNamespace(total=1, data=[])

    with patch.object(
        sgo_services,
        "SessionLocal",
        return_value=_AsyncSessionContext(main_session),
    ), patch.object(
        sgo_services,
        "sgo_sessionLocal",
        return_value=_AsyncSessionContext(sgo_session),
    ), patch.object(
        Items,
        "list_v2_indexed_item_codes",
        AsyncMock(return_value=indexed_codes),
    ) as codes_mock, patch.object(
        sgo_services.SgoCodeInquiryReturn,
        "get_return_by_code_id_list",
        AsyncMock(return_value=inquiry_rows),
    ) as return_mock, patch.object(
        sgo_services.SgoCodeInquiry,
        "list_code_inquiry",
        AsyncMock(return_value=expected),
    ) as list_mock, patch.object(
        sgo_services,
        "MilvusStateManagerV2",
        create=True,
    ) as state_cls:
        result = asyncio.run(
            SGOBiz.list_inquery(
                page=1,
                per_page=20,
                status="FINISH",
                has_indexed=1,
            )
        )

    assert result is expected
    codes_mock.assert_awaited_once_with(main_session)
    return_mock.assert_awaited_once_with(sgo_session, indexed_codes)
    assert list_mock.await_args.args[5] == ["Q001"]
    state_cls.assert_not_called()


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


def test_parent_materiel_name_prefers_vehicle_context_then_global_frequency():
    source_rows = [
        SimpleNamespace(
            materiel_code="PARENT",
            materiel_name="同车型父配件",
            b_vehicle_id="vehicle-1",
        ),
        SimpleNamespace(
            materiel_code="PARENT",
            materiel_name="全局常用父配件",
            b_vehicle_id="vehicle-2",
        ),
        SimpleNamespace(
            materiel_code="PARENT",
            materiel_name="全局常用父配件",
            b_vehicle_id="vehicle-3",
        ),
    ]

    names_by_vehicle, names_by_code = sgo_services._build_parent_name_counters(
        source_rows
    )

    assert sgo_services._resolve_parent_materiel_name(
        "PARENT",
        "vehicle-1",
        names_by_vehicle,
        names_by_code,
    ) == "同车型父配件"
    assert sgo_services._resolve_parent_materiel_name(
        "PARENT",
        "missing-vehicle",
        names_by_vehicle,
        names_by_code,
    ) == "全局常用父配件"
    assert sgo_services._resolve_parent_materiel_name(
        "UNKNOWN",
        "vehicle-1",
        names_by_vehicle,
        names_by_code,
    ) is None


def test_sync_parts_hierarchy_maps_items_and_vehicle_names_and_preserves_anomalies():
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def commit(self):
            return None

    item_rows = [
        SimpleNamespace(id=101, item_code="CHILD"),
        SimpleNamespace(id=102, item_code="PARENT"),
    ]
    source_rows = [
        SimpleNamespace(
            id="relation-1",
            materiel_code="CHILD",
            materiel_name="子配件",
            parent_materiel_code="PARENT",
            figure_number="FIG-1",
            train_type_group="SFE27",
            b_vehicle_id="vehicle-1",
            serial_number="1",
            column_id="A1",
            tenant_id_="tenant-1",
        ),
        SimpleNamespace(
            id="relation-2",
            materiel_code="SELF",
            materiel_name="自环配件",
            parent_materiel_code="SELF",
            figure_number=None,
            train_type_group=None,
            b_vehicle_id="missing-vehicle",
            serial_number="2",
            column_id="A1",
            tenant_id_="tenant-1",
        ),
        SimpleNamespace(
            id="relation-root",
            materiel_code="PARENT",
            materiel_name="父配件",
            parent_materiel_code=None,
            figure_number=None,
            train_type_group="SFE27",
            b_vehicle_id="vehicle-1",
            serial_number="0",
            column_id="A1",
            tenant_id_="tenant-1",
        ),
    ]
    vehicle_rows = [
        SimpleNamespace(
            vehicle_id="vehicle-1",
            vehicle_batch="SFE27",
            vehicle_name="CRH380A",
        )
    ]
    upsert_relations = AsyncMock()
    delete_relations = AsyncMock()

    with patch.object(sgo_services, "SessionLocal", side_effect=FakeSession), patch.object(
        sgo_services,
        "sgo_sessionLocal",
        side_effect=FakeSession,
    ), patch.object(
        Items,
        "list_all_item_id_codes",
        AsyncMock(return_value=item_rows),
    ), patch.object(
        ItemHierarchyRelation,
        "list_sync_state",
        AsyncMock(
            return_value=[
                SimpleNamespace(source_relation_id="relation-1", source_hash="old"),
                SimpleNamespace(source_relation_id="stale-relation", source_hash="stale"),
            ]
        ),
    ), patch.object(
        SgoMaterielInfoTree,
        "list_hierarchy_relations",
        AsyncMock(return_value=source_rows),
    ), patch.object(
        SgoMaterielVehicle,
        "list_vehicle_mappings",
        AsyncMock(return_value=vehicle_rows),
    ), patch.object(
        ItemHierarchyRelation,
        "upsert_from_sgo",
        upsert_relations,
    ), patch.object(
        ItemHierarchyRelation,
        "delete_by_source_ids",
        delete_relations,
    ):
        result = asyncio.run(SGOBiz.sync_parts_hierarchy())

    payloads = upsert_relations.await_args.args[1]
    assert payloads[0]["source_relation_id"] == "relation-1"
    assert payloads[0]["item_id"] == 101
    assert payloads[0]["parent_item_id"] == 102
    assert payloads[0]["parent_materiel_name"] == "父配件"
    assert payloads[0]["vehicle_batch"] == "SFE27"
    assert payloads[0]["vehicle_name"] == "CRH380A"
    assert payloads[0]["vehicle_resolved"] is True
    assert payloads[0]["is_valid"] is True
    assert payloads[1]["vehicle_resolved"] is False
    assert payloads[1]["is_valid"] is False
    assert payloads[1]["invalid_reason"] == "子配件编码与父配件编码相同"
    delete_relations.assert_awaited_once()
    assert delete_relations.await_args.args[1] == ["stale-relation"]
    assert result == {
        "hierarchy_total_count": 3,
        "synced_hierarchy_count": 3,
        "deleted_hierarchy_count": 1,
        "unresolved_vehicle_count": 1,
        "invalid_hierarchy_count": 1,
    }


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
        "MAX_SYNC_FAILURE_DETAILS",
        1,
    ), patch.object(
        sgo_services,
        "SessionLocal",
        side_effect=FakeSession,
    ), patch.object(
        sgo_services,
        "sgo_sessionLocal",
        side_effect=FakeSession,
    ), patch.object(
        Items,
        "list_all_item_sync_state",
        AsyncMock(return_value=[SimpleNamespace(id=101, item_code="existing", parts_model=None, material_quality=None)]),
    ), patch.object(
        ItemSupplier,
        "list_sync_state",
        AsyncMock(return_value=[]),
    ), patch.object(
        SgoMaterielMasterplate,
        "list_sgo_items",
        AsyncMock(return_value=source_rows),
    ), patch.object(
        SgoMaterielSupplier,
        "list_sgo_suppliers",
        AsyncMock(return_value=[]),
    ), patch.object(
        Items,
        "update_sgo_metadata",
        AsyncMock(),
    ), patch.object(
        ItemSupplier,
        "upsert_from_sgo",
        AsyncMock(),
    ), patch.object(
        ItemSupplier,
        "delete_by_source_ids",
        AsyncMock(),
    ), patch.object(
        SGOBiz,
        "sync_parts_hierarchy",
        AsyncMock(return_value=EMPTY_HIERARCHY_RESULT),
    ), patch.object(
        SGOBiz,
        "sync_parts_vehicle_batch",
        AsyncMock(return_value={"vehicle_item_count": 0, "updated_vehicle_item_count": 0}),
    ):
        result = asyncio.run(
            SGOBiz.sync_parts_items(progress_callback=capture_progress)
        )

    assert result["processed_items"] == 3
    assert result["created_count"] == 1
    assert result["fail_count"] == 2
    assert result["failed_item_ids"] == ["103"]
    expected_failures = [
        {
            "item_id": "103",
            "item_code": "missing-name",
            "item_name": None,
            "stage": "source_validation",
            "error_type": "InvalidSourceData",
            "error_message": "配件名称为空",
        },
        {
            "item_id": "invalid",
            "item_code": "bad",
            "item_name": "bad",
            "stage": "source_validation",
            "error_type": "InvalidSourceData",
            "error_message": "配件 ID 不是有效整数",
        }
    ]
    assert result["failure_details"] == expected_failures[:1]
    assert progress[-1]["progress"] == 100
    persisted_failures = [
        failure
        for payload in progress
        for failure in payload.get("new_failure_details", [])
    ]
    assert persisted_failures == expected_failures
    assert result["failures_persisted_incrementally"] is True


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
        "list_all_item_sync_state",
        AsyncMock(return_value=[SimpleNamespace(id=101, item_code=" Existing-Code ", parts_model=None, material_quality=None)]),
    ), patch.object(
        ItemSupplier,
        "list_sync_state",
        AsyncMock(return_value=[]),
    ), patch.object(
        SgoMaterielMasterplate,
        "list_sgo_items",
        AsyncMock(return_value=source_rows),
    ), patch.object(
        SgoMaterielSupplier,
        "list_sgo_suppliers",
        AsyncMock(return_value=[]),
    ), patch.object(
        Items,
        "update_sgo_metadata",
        AsyncMock(),
    ), patch.object(
        ItemSupplier,
        "upsert_from_sgo",
        AsyncMock(),
    ), patch.object(
        ItemSupplier,
        "delete_by_source_ids",
        AsyncMock(),
    ), patch.object(
        SGOBiz,
        "sync_parts_hierarchy",
        AsyncMock(return_value=EMPTY_HIERARCHY_RESULT),
    ), patch.object(
        SGOBiz,
        "sync_parts_vehicle_batch",
        AsyncMock(return_value={"vehicle_item_count": 0, "updated_vehicle_item_count": 0}),
    ):
        result = asyncio.run(SGOBiz.sync_parts_items())

    assert result["created_count"] == 1
    assert result["skipped_count"] == 2
    assert FakeSession.added_items[0].id == 104
    assert FakeSession.added_items[0].item_code == "new-code"


def test_sync_parts_items_persists_metadata_and_supplier_snapshot():
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def add_all(self, items):
            self.items = list(items)

        async def commit(self):
            return None

    item_states = [
        SimpleNamespace(
            id=101,
            item_code="CODE-1",
            parts_model=None,
            material_quality=None,
        )
    ]
    supplier_states = [
        SimpleNamespace(
            source_supplier_id="supplier-1",
            source_masterplate_id="101",
            item_id=101,
            supplier_code="OLD",
            supplier_name="旧供应商",
            supplier_item_code=None,
            supplier_item_name=None,
            supplier_parts_model=None,
            model_number=None,
            manufacturer=None,
            current_status="Draft",
            enable_status="normal",
        ),
        SimpleNamespace(
            source_supplier_id="stale-supplier",
            source_masterplate_id="101",
            item_id=101,
            supplier_code="STALE",
            supplier_name="已删除供应商",
            supplier_item_code=None,
            supplier_item_name=None,
            supplier_parts_model=None,
            model_number=None,
            manufacturer=None,
            current_status="Draft",
            enable_status="normal",
        ),
    ]
    source_parts = [
        SimpleNamespace(
            id="101",
            MATNR="CODE-1",
            maktx="配件一",
            wrkst="M10x20",
            material_quality="不锈钢",
        )
    ]
    source_suppliers = [
        SimpleNamespace(
            id="supplier-1",
            masterplate_id="101",
            supplier_code="NEW",
            supplier_name="新供应商",
            supplier_matnr="SUP-CODE-1",
            supplier_maktx="供方配件一",
            supplier_wrkst="SUP-M10x20",
            model_number="MODEL-1",
            manufacturer="制造商一",
            current_status="Draft",
            enable_status="normal",
        )
    ]
    update_metadata = AsyncMock()
    upsert_suppliers = AsyncMock()
    delete_suppliers = AsyncMock()

    with patch.object(sgo_services, "SessionLocal", side_effect=FakeSession), patch.object(
        sgo_services,
        "sgo_sessionLocal",
        side_effect=FakeSession,
    ), patch.object(
        Items,
        "list_all_item_sync_state",
        AsyncMock(return_value=item_states),
    ), patch.object(
        ItemSupplier,
        "list_sync_state",
        AsyncMock(return_value=supplier_states),
    ), patch.object(
        SgoMaterielMasterplate,
        "list_sgo_items",
        AsyncMock(return_value=source_parts),
    ), patch.object(
        SgoMaterielSupplier,
        "list_sgo_suppliers",
        AsyncMock(return_value=source_suppliers),
    ), patch.object(
        Items,
        "update_sgo_metadata",
        update_metadata,
    ), patch.object(
        ItemSupplier,
        "upsert_from_sgo",
        upsert_suppliers,
    ), patch.object(
        ItemSupplier,
        "delete_by_source_ids",
        delete_suppliers,
    ), patch.object(
        SGOBiz,
        "sync_parts_hierarchy",
        AsyncMock(return_value=EMPTY_HIERARCHY_RESULT),
    ), patch.object(
        SGOBiz,
        "sync_parts_vehicle_batch",
        AsyncMock(return_value={"vehicle_item_count": 0, "updated_vehicle_item_count": 0}),
    ):
        result = asyncio.run(SGOBiz.sync_parts_items())

    metadata_rows = update_metadata.await_args.args[1]
    assert metadata_rows == [
        {
            "item_id": 101,
            "item_name": "配件一",
            "parts_model": "M10x20",
            "drawing_number": None,
            "material_quality": "不锈钢",
        }
    ]
    supplier_rows = upsert_suppliers.await_args.args[1]
    assert supplier_rows[0]["supplier_name"] == "新供应商"
    assert supplier_rows[0]["model_number"] == "MODEL-1"
    delete_suppliers.assert_awaited_once()
    assert delete_suppliers.await_args.args[1] == ["stale-supplier"]
    assert result["updated_metadata_count"] == 1
    assert result["synced_supplier_count"] == 1
    assert result["deleted_supplier_count"] == 1


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
        return {
            "processed_count": len(payloads),
            "created_count": 1,
            "skipped_count": 1,
            "history_ids": [501],
        }

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
    ), patch.object(sgo_services.logger, "info") as logger_info:
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
        "created_count": 1,
        "skipped_count": 1,
        "synced_image_count": 0,
        "failed_item_ids": [],
        "non_indexable_without_return_code": 0,
    }
    assert [item["progress"] for item in progress] == [0, 100]
    assert progress[-1]["current_item_id"] == "inq-2"
    diagnostic_calls = [
        call
        for call in logger_info.call_args_list
        if call.args and call.args[0].startswith("SGO 询码历史同步诊断:")
    ]
    assert len(diagnostic_calls) == 1
    assert diagnostic_calls[0].args[1:7] == (2, 2, 1, 1, 1, 0)


def test_sync_inquiry_history_persists_rows_without_return_item_code():
    source_rows = [
        {
            "inquiry_id": "inq-1",
            "inquiry_num": "CX001",
            "vehicle": "SFE27",
            "train_no": "2777",
            "car_num": "01",
            "inquiry_item_name": "监控室抽屉把手",
            "subordinate_component": None,
            "remark": "监控室把手缺，需更换处理。",
            "return_item_name": "监控室抽屉拉手",
            "return_item_code": "400001",
            "inquiry_time": "2018-11-02 15:36:30",
        },
        {
            "inquiry_id": "inq-2",
            "inquiry_num": "CX002",
            "vehicle": None,
            "train_no": "2053",
            "car_num": "5",
            "inquiry_item_name": "展示柜压缩机",
            "subordinate_component": None,
            "remark": "展示柜风扇振动大，待更换压缩机",
            "return_item_name": "压缩机候选描述",
            "return_item_code": None,
            "inquiry_time": "2018-11-02 15:51:29",
        },
    ]

    async def upsert(payloads, *, batch_size):
        assert batch_size == 500
        assert len(payloads) == 2
        assert payloads[0]["inquiry_id"] == "inq-1"
        assert payloads[0]["return_item_code"] == "400001"
        assert payloads[1]["inquiry_id"] == "inq-2"
        assert payloads[1]["item_code"] is None
        assert payloads[1]["return_item_code"] == ""
        return {
            "processed_count": 2,
            "created_count": 2,
            "skipped_count": 0,
            "history_ids": [501, 502],
        }

    with patch.object(
        SGOBiz,
        "_list_sgo_inquiry_history_source_rows",
        AsyncMock(return_value=source_rows),
    ), patch.object(
        SGOBiz,
        "_list_main_item_ids_by_codes",
        AsyncMock(return_value={"400001": 101}),
    ) as list_item_ids, patch.object(
        SGOBiz,
        "_upsert_inquiry_history_payloads",
        AsyncMock(side_effect=upsert),
    ):
        result = asyncio.run(SGOBiz.sync_inquiry_history())

    list_item_ids.assert_awaited_once_with({"400001"})
    assert result["total_items"] == 2
    assert result["processed_items"] == 2
    assert result["success_count"] == 2
    assert result["created_count"] == 2
    assert result["skipped_count"] == 0
    assert result["non_indexable_without_return_code"] == 1
    assert result["fail_count"] == 0


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
        AsyncMock(
            return_value={
                "processed_count": 1,
                "created_count": 1,
                "skipped_count": 0,
                "history_ids": [501],
            }
        ),
    ), patch.object(
        SGOBiz,
        "_enqueue_inquiry_semantic_index",
        enqueue_semantic,
    ):
        result = asyncio.run(
            SGOBiz.sync_inquiry_history(_sync_task_id="sync-task-1")
        )

    assert result["semantic_index_task_id"] == "semantic-task-1"
    assert result["semantic_index_triggered"] is True
    assert result["semantic_index_warning"] is None
    enqueue_semantic.assert_awaited_once_with(
        [501],
        source_sync_task_id="sync-task-1",
    )


def test_inquiry_history_insert_sql_does_not_update_closed_records():
    statement = sgo_services._build_inquiry_history_upsert_sql()
    update_clause = statement.split("ON DUPLICATE KEY UPDATE", 1)[1].strip()

    assert update_clause == "`id` = `item_inquiry_history`.`id`"
    assert "CURRENT_TIMESTAMP" not in update_clause
    assert "new.`inquiry_item_name`" not in update_clause


def test_upsert_inquiry_history_returns_only_rows_inserted_by_current_sync():
    class Result:
        def __init__(self, rows=(), scalar_values=()):
            self.rows = list(rows)
            self.scalar_values = list(scalar_values)

        def __iter__(self):
            return iter(self.rows)

        def scalars(self):
            return iter(self.scalar_values)

    class Session:
        inserted_rows = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def execute(self, statement, params=None):
            sql = str(statement)
            if sql.startswith("SELECT item_inquiry_history.source"):
                return Result(rows=[("sgo", "inq-existing", "code-1")])
            if sql.startswith("INSERT INTO `item_inquiry_history`"):
                self.inserted_rows.extend(params)
                return Result()
            if sql.startswith("SELECT item_inquiry_history.id"):
                return Result(scalar_values=[501, 502])
            raise AssertionError(f"unexpected SQL: {sql}")

        async def flush(self):
            return None

        async def commit(self):
            return None

    payloads = [
        {
            "source": "sgo",
            "inquiry_id": "inq-existing",
            "return_item_code": "code-1",
        },
        {
            "source": "sgo",
            "inquiry_id": "inq-existing",
            "return_item_code": "code-2",
        },
        {
            "source": "sgo",
            "inquiry_id": "inq-new",
            "return_item_code": "code-3",
        },
        {
            "source": "sgo",
            "inquiry_id": "inq-new",
            "return_item_code": "code-3",
        },
    ]

    with patch.object(sgo_services, "SessionLocal", side_effect=Session), patch.object(
        sgo_services,
        "get_id",
        side_effect=[501, 502],
    ), patch.object(sgo_services.logger, "info") as logger_info:
        result = asyncio.run(
            SGOBiz._upsert_inquiry_history_payloads(payloads, batch_size=10)
        )

    assert result == {
        "processed_count": 4,
        "created_count": 2,
        "skipped_count": 2,
        "history_ids": [501, 502],
    }
    assert len(Session.inserted_rows) == 2
    assert {
        (row["inquiry_id"], row["return_item_code"])
        for row in Session.inserted_rows
    } == {("inq-existing", "code-2"), ("inq-new", "code-3")}
    diagnostic_calls = [
        call
        for call in logger_info.call_args_list
        if call.args and call.args[0].startswith("SGO 询码历史本地写入诊断:")
    ]
    assert len(diagnostic_calls) == 1
    assert diagnostic_calls[0].args[1:5] == (4, 1, 2, 2)


def test_sync_inquiry_history_does_not_enqueue_semantic_task_without_new_rows():
    source_rows = [{"inquiry_id": "inq-1", "return_item_code": "code-1"}]
    enqueue_semantic = AsyncMock()

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
        AsyncMock(
            return_value={
                "processed_count": 1,
                "created_count": 0,
                "skipped_count": 1,
                "history_ids": [],
            }
        ),
    ), patch.object(
        SGOBiz,
        "_enqueue_inquiry_semantic_index",
        enqueue_semantic,
    ):
        result = asyncio.run(
            SGOBiz.sync_inquiry_history(_sync_task_id="sync-task-1")
        )

    enqueue_semantic.assert_not_awaited()
    assert result["semantic_index_triggered"] is False
    assert result["semantic_index_task_id"] is None
    assert result["semantic_index_warning"] is None


def test_sync_inquiry_history_respects_disabled_auto_index_switch():
    source_rows = [{"inquiry_id": "inq-1", "return_item_code": "code-1"}]
    enqueue_semantic = AsyncMock()

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
        AsyncMock(
            return_value={
                "processed_count": 1,
                "created_count": 1,
                "skipped_count": 0,
                "history_ids": [501],
            }
        ),
    ), patch.object(
        SGOBiz,
        "_enqueue_inquiry_semantic_index",
        enqueue_semantic,
    ), patch.object(
        sgo_services,
        "inquiry_text_auto_index_enabled",
        False,
        create=True,
    ):
        result = asyncio.run(
            SGOBiz.sync_inquiry_history(_sync_task_id="sync-task-1")
        )

    enqueue_semantic.assert_not_awaited()
    assert result["semantic_index_triggered"] is False
    assert result["semantic_index_task_id"] is None


def test_sync_inquiry_history_reports_semantic_enqueue_warning():
    source_rows = [{"inquiry_id": "inq-1", "return_item_code": "code-1"}]

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
        AsyncMock(
            return_value={
                "processed_count": 1,
                "created_count": 1,
                "skipped_count": 0,
                "history_ids": [501],
            }
        ),
    ), patch.object(
        SGOBiz,
        "_enqueue_inquiry_semantic_index",
        AsyncMock(side_effect=RuntimeError("queue unavailable")),
    ):
        result = asyncio.run(
            SGOBiz.sync_inquiry_history(_sync_task_id="sync-task-1")
        )

    assert result["semantic_index_triggered"] is False
    assert result["semantic_index_task_id"] is None
    assert result["semantic_index_warning"] == "queue unavailable"
