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


def _import_railway_parts_manager():
    cached = getattr(_import_railway_parts_manager, "_cached", None)
    if cached is not None:
        return cached

    existing = sys.modules.get("csrcqsf.biz.railwayparts.parts")
    if existing is not None:
        _import_railway_parts_manager._cached = existing
        return existing

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.data.milvus": SimpleNamespace(milvus_client=MagicMock()),
            "csrcqsf.data.mdpdb": SimpleNamespace(sgo_sessionLocal=MagicMock()),
            "csrcqsf.biz.railwayparts.milvus": _fake_v1_milvus_module(),
        },
    ):
        import csrcqsf.biz.railwayparts as railwayparts_pkg
        import csrcqsf.biz.railwayparts.parts as parts_module
        item_module = sys.modules.get("csrcqsf.models.item")

    railwayparts_pkg.parts = parts_module
    sys.modules["csrcqsf.biz.railwayparts.parts"] = parts_module
    if item_module is not None:
        sys.modules["csrcqsf.models.item"] = item_module

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
         patch.object(parts_module, "MilvusManagerV2") as manager_cls:
        manager_cls.return_value.get_statistics_snapshot.return_value = fake_snapshot
        res = asyncio.run(parts_module.RailwayPartsManager.statistics())

    assert res.total_item_num == 99
    assert res.total_image_index == 8
    assert res.total_feature_index == 6
    assert res.total_index == 14
    assert res.total_indexed_item_num == 2
    assert res.recognition_number == 0
    assert res.corrrect_recognition_number == 0
    assert res.recognition_ration == 0


def test_delete_v2_index_is_idempotent_for_existing_item_without_vectors():
    parts_module = _import_railway_parts_manager()

    session = AsyncMock()
    fake_item = SimpleNamespace(id=1935558010375340032)

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls:
        manager_cls.return_value.delete_item_index.return_value = {
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
         patch.object(parts_module, "MilvusManagerV2") as manager_cls:
        manager_cls.return_value.delete_item_index.return_value = {
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
         patch.object(parts_module, "MilvusManagerV2") as manager_cls:
        manager_cls.return_value.index_image = AsyncMock(return_value=(True, True))
        asyncio.run(parts_module.RailwayPartsManager.rebuild_v2_index(item_id=101, limit=1))

    sync_mock.assert_awaited_with(101)
