import asyncio
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from csrcqsf.biz.railwayparts.api_models import ListItemReq


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


def test_list_item_uses_v2_flags_for_filter_and_response():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    page_result = SimpleNamespace(
        total=1,
        data=[
            SimpleNamespace(
                id=101,
                item_name="橡胶套",
                item_code="40000543491",
                obj_url=None,
                height=None,
                long=None,
                width=None,
                weight=None,
                source_video_path="bfr-3d-videos/raw-videos/demo.mp4",
                has_v2_index=1,
                v2_indexed_image_num=4,
                time_created=datetime(2025, 10, 24, 15, 40, 16),
            )
        ],
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "list_items", AsyncMock(return_value=page_result)) as list_mock, \
         patch.object(parts_module.RailwayPartsManager, "list_item_images", AsyncMock(return_value=[])), \
         patch.object(parts_module, "MilvusStateManagerV2") as state_cls:
        state_cls.return_value.list_item_index.return_value = {}
        res = asyncio.run(
            parts_module.RailwayPartsManager.list_item(
                ListItemReq(page=1, pageSize=20, only_has_index=1, has_source_video=1)
            )
        )

    kwargs = list_mock.await_args.kwargs
    assert kwargs["need_v2_index"] is True
    assert kwargs["has_source_video"] == 1
    assert res.items[0].has_index == 1
    assert res.items[0].has_source_video == 1
    assert res.items[0].images_total_indexed_num == 4
