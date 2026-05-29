import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _fake_v1_milvus_module():
    return SimpleNamespace(
        MilvusManager=lambda: MagicMock(),
        ImageIndex=object,
        PartsIndex=object,
        FeaturesIndex=object,
        ColletionEnum=object,
    )


def _fake_cv2_module():
    return SimpleNamespace(
        COLOR_BGR2RGB=1,
        cvtColor=lambda image, _code: image,
    )


def _import_railway_parts_manager():
    cached = getattr(_import_railway_parts_manager, "_cached", None)
    if cached is not None:
        return cached

    existing = sys.modules.get("csrcqsf.modules.railway_parts.services.parts_service")
    if existing is not None:
        _import_railway_parts_manager._cached = existing
        return existing

    preserved_modules = {}
    with patch.dict(
        sys.modules,
        {
            "csrcqsf.data.milvus": SimpleNamespace(milvus_client=MagicMock()),
            "csrcqsf.data.mdpdb": SimpleNamespace(sgo_sessionLocal=MagicMock()),
            "csrcqsf.biz.railwayparts.milvus": _fake_v1_milvus_module(),
            "cv2": _fake_cv2_module(),
        },
    ):
        import csrcqsf.modules.railway_parts.services.parts_service as parts_module
        preserved_modules = {
            "csrcqsf.modules.railway_parts.services.parts_service": parts_module,
            "csrcqsf.models.item": sys.modules.get("csrcqsf.models.item"),
            "csrcqsf.models.sgo": sys.modules.get("csrcqsf.models.sgo"),
            "csrcqsf.models.search_history": sys.modules.get("csrcqsf.models.search_history"),
        }

    for module_name, module in preserved_modules.items():
        if module is not None:
            sys.modules[module_name] = module

    _import_railway_parts_manager._cached = parts_module
    return parts_module


def test_statistics_reads_v2_snapshot_and_zeroes_legacy_recognition_fields():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_snapshot = {
        "siglip_count": 8,
        "dinov2_count": 6,
        "siglip_item_ids": {1, 2, 3},
        "dinov2_item_ids": {2, 3, 4},
    }

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module, "async_get_count", AsyncMock(return_value=99)), \
         patch.object(parts_module, "MilvusStateManagerV2") as state_cls:
        state_cls.return_value.get_statistics_snapshot.return_value = fake_snapshot
        state_cls.return_value.get_item_index_state_snapshot.return_value = {
            2: {"has_v2_index": 1, "v2_indexed_image_num": 3},
            3: {"has_v2_index": 1, "v2_indexed_image_num": 1},
        }
        res = asyncio.run(parts_module.RailwayPartsManager.statistics())

    assert res.total_item_num == 99
    assert res.total_image_index == 8
    assert res.total_feature_index == 6
    assert res.total_index == 14
    assert res.total_indexed_item_num == 2
    assert res.recognition_number == 0
    assert res.corrrect_recognition_number == 0
    assert res.recognition_ration == 0


def test_statistics_counts_only_items_with_completed_v2_index_state():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_snapshot = {
        "siglip_count": 5,
        "dinov2_count": 5,
        "siglip_item_ids": {1, 2, 3},
        "dinov2_item_ids": {2, 3, 4},
    }
    fake_state_snapshot = {
        1: {"has_v2_index": 0, "v2_indexed_image_num": 0},
        2: {"has_v2_index": 1, "v2_indexed_image_num": 2},
        3: {"has_v2_index": 0, "v2_indexed_image_num": 0},
        4: {"has_v2_index": 0, "v2_indexed_image_num": 0},
    }

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module, "async_get_count", AsyncMock(return_value=99)), \
         patch.object(parts_module, "MilvusStateManagerV2") as state_cls:
        state_cls.return_value.get_statistics_snapshot.return_value = fake_snapshot
        state_cls.return_value.get_item_index_state_snapshot.return_value = fake_state_snapshot
        res = asyncio.run(parts_module.RailwayPartsManager.statistics())

    assert res.total_indexed_item_num == 1


def test_delete_v2_index_is_idempotent_for_existing_item_without_vectors():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(id=1935558010375340032)

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module, "MilvusStateManagerV2") as state_cls:
        state_cls.return_value.delete_item_index.return_value = {
            "siglip_deleted": 0,
            "dinov2_deleted": 0,
        }
        res = asyncio.run(parts_module.RailwayPartsManager.delete_v2_index(1935558010375340032))

    assert res["item_id"] == 1935558010375340032
    assert res["siglip_deleted"] == 0
    assert res["dinov2_deleted"] == 0
    assert "成功" in res["message"]


def test_delete_v2_index_clears_pg_cache_state():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(id=1935558010375340032)

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.Items, "update_v2_index_state", AsyncMock()) as update_mock, \
         patch.object(parts_module, "MilvusStateManagerV2") as state_cls:
        state_cls.return_value.delete_item_index.return_value = {
            "siglip_deleted": 0,
            "dinov2_deleted": 0,
        }
        asyncio.run(parts_module.RailwayPartsManager.delete_v2_index(1935558010375340032))

    update_mock.assert_awaited()
    session.commit.assert_awaited()


def test_rebuild_v2_index_syncs_single_item_state_after_success():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(id=101, item_name="橡胶套", item_code="40000543491")
    fake_image = SimpleNamespace(id=9001, image_url="bfr-ai-files/demo.jpg")
    fake_image_array = np.zeros((2, 2, 3), dtype=np.uint8)
    fake_state_manager = MagicMock()
    fake_cv2 = SimpleNamespace(
        COLOR_BGR2RGB=1,
        cvtColor=lambda image, _code: image,
    )

    with patch.dict(sys.modules, {"cv2": fake_cv2}), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "list_item_images_by_item_id", AsyncMock(return_value=[fake_image])), \
         patch.object(parts_module.RailwayPartsManager, "get_image_from_oss", AsyncMock(return_value=fake_image_array)), \
         patch.object(parts_module.RailwayPartsManager, "sync_item_v2_index_state", AsyncMock()) as sync_mock, \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager) as state_cls:
        manager_cls.return_value.index_image = AsyncMock(return_value=(True, True))
        asyncio.run(parts_module.RailwayPartsManager.rebuild_v2_index(item_id=101, limit=1))

    state_cls.assert_called_once_with()
    sync_mock.assert_awaited_once_with(101, state_manager=fake_state_manager)


def test_rebuild_v2_index_bulk_mode_filters_existing_indexes_by_default():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        item_name="橡胶套",
        item_code="40000543491",
        has_v2_index=0,
    )
    fake_image = SimpleNamespace(id=9001, image_url="bfr-ai-files/demo.jpg")
    fake_image_array = np.zeros((2, 2, 3), dtype=np.uint8)
    fake_state_manager = MagicMock()
    fake_cv2 = SimpleNamespace(
        COLOR_BGR2RGB=1,
        cvtColor=lambda image, _code: image,
    )

    with patch.dict(sys.modules, {"cv2": fake_cv2}), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(session, "scalars", AsyncMock(return_value=[fake_item])) as scalars_mock, \
         patch.object(parts_module.SgoItemImages, "list_item_images_by_item_id", AsyncMock(return_value=[fake_image])), \
         patch.object(parts_module.RailwayPartsManager, "get_image_from_oss", AsyncMock(return_value=fake_image_array)), \
         patch.object(parts_module.RailwayPartsManager, "sync_item_v2_index_state", AsyncMock()) as sync_mock, \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager):
        manager_cls.return_value.index_image = AsyncMock(return_value=(True, True))
        result = asyncio.run(parts_module.RailwayPartsManager.rebuild_v2_index(limit=1))

    stmt = scalars_mock.await_args.args[0]
    assert "has_v2_index" in str(stmt)
    assert result["processed_item_count"] == 1
    assert result["skipped_existing_count"] == 0
    fake_state_manager.delete_item_index.assert_not_called()
    sync_mock.assert_awaited_once_with(101, state_manager=fake_state_manager)


def test_rebuild_v2_index_single_item_skips_existing_when_not_forcing_rebuild():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        item_name="橡胶套",
        item_code="40000543491",
        has_v2_index=1,
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "list_item_images_by_item_id", AsyncMock()) as list_images_mock, \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "MilvusStateManagerV2") as state_cls:
        manager_cls.return_value.index_image = AsyncMock()
        result = asyncio.run(
            parts_module.RailwayPartsManager.rebuild_v2_index(
                item_id=101,
                limit=1,
                rebuild_existing=False,
            )
        )

    list_images_mock.assert_not_awaited()
    state_cls.return_value.delete_item_index.assert_not_called()
    manager_cls.return_value.index_image.assert_not_awaited()
    assert result["processed_item_count"] == 0
    assert result["skipped_existing_count"] == 1


def test_rebuild_v2_index_force_mode_deletes_existing_vectors_before_reindex():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        item_name="橡胶套",
        item_code="40000543491",
        has_v2_index=1,
    )
    fake_image = SimpleNamespace(id=9001, image_url="bfr-ai-files/demo.jpg")
    fake_image_array = np.zeros((2, 2, 3), dtype=np.uint8)
    fake_state_manager = MagicMock()
    fake_cv2 = SimpleNamespace(
        COLOR_BGR2RGB=1,
        cvtColor=lambda image, _code: image,
    )
    call_order: list[str] = []

    async def _index_image(**_kwargs):
        call_order.append("index")
        return True, True

    def _delete_item_index(item_id):
        call_order.append(f"delete:{item_id}")
        return {"siglip_deleted": 4, "dinov2_deleted": 4}

    with patch.dict(sys.modules, {"cv2": fake_cv2}), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "list_item_images_by_item_id", AsyncMock(return_value=[fake_image])), \
         patch.object(parts_module.RailwayPartsManager, "get_image_from_oss", AsyncMock(return_value=fake_image_array)), \
         patch.object(parts_module.RailwayPartsManager, "sync_item_v2_index_state", AsyncMock()) as sync_mock, \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager):
        manager_cls.return_value.index_image = AsyncMock(side_effect=_index_image)
        fake_state_manager.delete_item_index.side_effect = _delete_item_index
        result = asyncio.run(
            parts_module.RailwayPartsManager.rebuild_v2_index(
                item_id=101,
                limit=1,
                rebuild_existing=True,
            )
        )

    assert call_order == ["delete:101", "index"]
    sync_mock.assert_awaited_once_with(101, state_manager=fake_state_manager)
    assert result["processed_item_count"] == 1
    assert result["skipped_existing_count"] == 0


def test_rebuild_v2_index_force_mode_syncs_state_after_delete_even_if_reindex_fails():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        item_name="橡胶套",
        item_code="40000543491",
        has_v2_index=1,
    )
    fake_image = SimpleNamespace(id=9001, image_url="bfr-ai-files/demo.jpg")
    fake_image_array = np.zeros((2, 2, 3), dtype=np.uint8)
    fake_state_manager = MagicMock()
    fake_cv2 = SimpleNamespace(
        COLOR_BGR2RGB=1,
        cvtColor=lambda image, _code: image,
    )

    with patch.dict(sys.modules, {"cv2": fake_cv2}), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "list_item_images_by_item_id", AsyncMock(return_value=[fake_image])), \
         patch.object(parts_module.RailwayPartsManager, "get_image_from_oss", AsyncMock(return_value=fake_image_array)), \
         patch.object(parts_module.RailwayPartsManager, "sync_item_v2_index_state", AsyncMock()) as sync_mock, \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager):
        manager_cls.return_value.index_image = AsyncMock(return_value=(False, False))
        fake_state_manager.delete_item_index.return_value = {"siglip_deleted": 4, "dinov2_deleted": 4}
        result = asyncio.run(
            parts_module.RailwayPartsManager.rebuild_v2_index(
                item_id=101,
                limit=1,
                rebuild_existing=True,
            )
        )

    sync_mock.assert_awaited_once_with(101, state_manager=fake_state_manager)
    assert result["processed_item_count"] == 1


def test_rebuild_v2_index_marks_successful_images_indexed_in_pg():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        item_name="橡胶套",
        item_code="40000543491",
        has_v2_index=0,
    )
    fake_images = [
        SimpleNamespace(id=9001, image_url="bfr-ai-files/a.jpg"),
        SimpleNamespace(id=9002, image_url="bfr-ai-files/b.jpg"),
    ]
    fake_image_array = np.zeros((2, 2, 3), dtype=np.uint8)
    fake_state_manager = MagicMock()
    fake_cv2 = SimpleNamespace(
        COLOR_BGR2RGB=1,
        cvtColor=lambda image, _code: image,
    )

    with patch.dict(sys.modules, {"cv2": fake_cv2}), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "list_item_images_by_item_id", AsyncMock(return_value=fake_images)), \
         patch.object(parts_module.SgoItemImages, "indexed_image", AsyncMock()) as indexed_mock, \
         patch.object(parts_module.RailwayPartsManager, "get_image_from_oss", AsyncMock(return_value=fake_image_array)), \
         patch.object(parts_module.RailwayPartsManager, "sync_item_v2_index_state", AsyncMock()), \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager):
        manager_cls.return_value.index_image = AsyncMock(side_effect=[(True, True), (False, False)])
        asyncio.run(parts_module.RailwayPartsManager.rebuild_v2_index(item_id=101, limit=1))

    indexed_mock.assert_awaited_once_with(session=session, image_id_list=[9001])
    session.commit.assert_awaited()


def test_rebuild_v2_index_persists_segmented_image_record_when_sam3_succeeds():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        item_name="座便器盖组成",
        item_code="40000976677",
        has_v2_index=0,
    )
    fake_image = SimpleNamespace(id=9001, image_url="bfr-ai-files/source-a.jpg")
    fake_image_array = np.zeros((2, 2, 3), dtype=np.uint8)
    fake_state_manager = MagicMock()
    fake_cv2 = SimpleNamespace(
        COLOR_BGR2RGB=1,
        cvtColor=lambda image, _code: image,
    )
    fake_preprocess_outcome = SimpleNamespace(
        result_image=object(),
        selected_prompt="toilet lid",
    )

    async def _index_image(**_kwargs):
        manager_cls.return_value.last_preprocess_outcome = fake_preprocess_outcome
        return True, True

    with patch.dict(sys.modules, {"cv2": fake_cv2}), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "list_item_images_by_item_id", AsyncMock(return_value=[fake_image])), \
         patch.object(parts_module.SgoItemImages, "indexed_image", AsyncMock()), \
         patch.object(parts_module.SegmentedImage, "batch_create", AsyncMock()) as batch_create_mock, \
         patch.object(parts_module.RailwayPartsManager, "get_image_from_oss", AsyncMock(return_value=fake_image_array)), \
         patch.object(parts_module.RailwayPartsManager, "_upload_v2_segmented_image", AsyncMock(return_value="bfr-ai-files/segmented/9001.jpg")) as upload_mock, \
         patch.object(parts_module.RailwayPartsManager, "sync_item_v2_index_state", AsyncMock()), \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager):
        manager_cls.return_value.index_image = AsyncMock(side_effect=_index_image)
        asyncio.run(parts_module.RailwayPartsManager.rebuild_v2_index(item_id=101, limit=1))

    upload_mock.assert_awaited_once_with(fake_preprocess_outcome.result_image, 101, 9001)
    batch_create_mock.assert_awaited_once()
    records = batch_create_mock.await_args.args[1]
    assert len(records) == 1
    assert records[0].item_id == 101
    assert records[0].source_image_id == 9001
    assert records[0].source_image_url == "bfr-ai-files/source-a.jpg"
    assert records[0].segmented_image_url == "bfr-ai-files/segmented/9001.jpg"
    assert records[0].is_indexed == 1
