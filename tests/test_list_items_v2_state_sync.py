import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _fake_v1_milvus_module():
    return MagicMock(
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
            "csrcqsf.data.milvus": MagicMock(milvus_client=MagicMock()),
            "csrcqsf.data.mdpdb": MagicMock(sgo_sessionLocal=MagicMock()),
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


def test_sync_all_v2_index_state_resets_and_bulk_updates_snapshot():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_snapshot = {
        101: {"has_v2_index": 1, "v2_indexed_image_num": 3},
        202: {"has_v2_index": 1, "v2_indexed_image_num": 1},
    }

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module.Items, "reset_v2_index_state", AsyncMock()) as reset_mock, \
         patch.object(parts_module.Items, "bulk_update_v2_index_state", AsyncMock()) as bulk_mock:
        manager_cls.return_value.get_item_index_state_snapshot.return_value = fake_snapshot
        res = asyncio.run(parts_module.RailwayPartsManager.sync_all_v2_index_state())

    reset_mock.assert_awaited()
    bulk_mock.assert_awaited()
    session.commit.assert_awaited()
    assert res["indexed_item_count"] == 2


def test_sync_single_item_v2_index_state_clears_missing_item():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module.Items, "update_v2_index_state", AsyncMock()) as update_mock:
        manager_cls.return_value.get_item_index_state_snapshot.return_value = {}
        asyncio.run(parts_module.RailwayPartsManager.sync_item_v2_index_state(303))

    update_mock.assert_awaited()
    session.commit.assert_awaited()
