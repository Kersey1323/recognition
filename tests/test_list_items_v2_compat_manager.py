import asyncio
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from csrcqsf.modules.railway_parts.schemas.parts import ListItemReq


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

    existing = sys.modules.get("csrcqsf.modules.railway_parts.services.parts_service")
    if existing is not None:
        _import_railway_parts_manager._cached = existing
        return existing

    preserved_modules = {}
    with patch.dict(
        sys.modules,
        {
            "csrcqsf.infra.vector_store.milvus": SimpleNamespace(milvus_client=MagicMock()),
            "csrcqsf.infra.db.mdp_db": SimpleNamespace(sgo_sessionLocal=MagicMock()),
            "csrcqsf.modules.railway_parts.integrations.milvus_state_manager": _fake_v1_milvus_module(),
        },
    ):
        import csrcqsf.modules.railway_parts.services.parts_service as parts_module
        preserved_modules = {
            "csrcqsf.modules.railway_parts.services.parts_service": parts_module,
            "csrcqsf.models.orm.item": sys.modules.get("csrcqsf.models.orm.item"),
            "csrcqsf.models.orm.sgo": sys.modules.get("csrcqsf.models.orm.sgo"),
            "csrcqsf.models.orm.search_history": sys.modules.get("csrcqsf.models.orm.search_history"),
        }

    for module_name, module in preserved_modules.items():
        if module is not None:
            sys.modules[module_name] = module

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


def test_list_item_passes_item_code_as_exact_filter():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    page_result = SimpleNamespace(total=0, data=[])

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "list_items", AsyncMock(return_value=page_result)) as list_mock, \
         patch.object(parts_module.RailwayPartsManager, "list_item_images", AsyncMock(return_value=[])), \
         patch.object(parts_module, "MilvusStateManagerV2") as state_cls:
        state_cls.return_value.list_item_index.return_value = {}
        asyncio.run(
            parts_module.RailwayPartsManager.list_item(
                ListItemReq(page=1, pageSize=20, item_code="12312321")
            )
        )

    kwargs = list_mock.await_args.kwargs
    assert kwargs["item_code_list"] == ["12312321"]
