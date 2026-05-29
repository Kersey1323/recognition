import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


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


def _fake_minio_module():
    return SimpleNamespace(
        minio_instance=SimpleNamespace(client=MagicMock()),
        ensure_minio_bucket=MagicMock(),
        parse_minio_path=MagicMock(),
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
            "csrcqsf.data.minio": _fake_minio_module(),
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


async def _async_iter(items):
    for item in items:
        yield item


def test_get_item_detail_uses_v2_indexed_images_and_returns_image_url():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        obj_url=None,
        height=None,
        width=None,
        long=None,
        weight=None,
        source_video_path=None,
        item_name="橡胶套",
        item_code="40000543491",
        time_created=None,
        time_updated=None,
        size_str=None,
    )
    fake_images = [
        SimpleNamespace(id=9001, image_url="bfr-ai-files/a.jpg", image_source="INQUERY"),
        SimpleNamespace(id=9002, image_url="bfr-ai-files/b.jpg", image_source="INQUERY"),
    ]
    fake_state_manager = MagicMock()
    fake_state_manager.get_indexed_images_by_item_id.return_value = {
        9001: "bfr-ai-files/a.jpg",
    }
    fake_reconstruction_manager = SimpleNamespace(
        ensure_item_result_persisted=AsyncMock(),
    )

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.reconstruction_service": SimpleNamespace(
                ReconstructionManager=fake_reconstruction_manager
            )
        },
    ), patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "get_images", MagicMock(return_value=_async_iter(fake_images))), \
         patch.object(parts_module, "MilvusManager", SimpleNamespace(list_item_index=AsyncMock(return_value={}))), \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager), \
         patch.object(parts_module, "date_to_str", side_effect=lambda _value: "2026-04-27 11:39:23"):
        res = asyncio.run(parts_module.RailwayPartsManager.get_item_detail(101))

    assert len(res.images_index_list) == 1
    assert res.images_index_list[0].image_id == "9001"
    assert res.images_index_list[0].image_url == "bfr-ai-files/a.jpg"
    assert res.images[0].image_id == "9001"
    assert res.images[0].has_indexed == 1
    assert res.images[0].image_url == "bfr-ai-files/a.jpg"
    assert res.images[1].image_id == "9002"
    assert res.images[1].has_indexed == 0
    assert res.images[1].image_url == "bfr-ai-files/b.jpg"


def test_get_item_detail_prefers_segmented_image_url_for_index_panel():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        obj_url=None,
        height=None,
        width=None,
        long=None,
        weight=None,
        source_video_path=None,
        item_name="座便器盖组成",
        item_code="40000976677",
        time_created=None,
        time_updated=None,
        size_str=None,
    )
    fake_images = [
        SimpleNamespace(id=9001, image_url="bfr-ai-files/source-a.jpg", image_source="INQUERY"),
    ]
    fake_segmented_records = [
        SimpleNamespace(
            source_image_id=9001,
            segmented_image_url="bfr-ai-files/segmented/9001.jpg",
            status="success",
        ),
    ]
    fake_state_manager = MagicMock()
    fake_state_manager.get_indexed_images_by_item_id.return_value = {
        9001: "bfr-ai-files/source-a.jpg",
    }
    fake_reconstruction_manager = SimpleNamespace(
        ensure_item_result_persisted=AsyncMock(),
    )

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.reconstruction_service": SimpleNamespace(
                ReconstructionManager=fake_reconstruction_manager
            )
        },
    ), patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "get_images", MagicMock(return_value=_async_iter(fake_images))), \
         patch.object(parts_module, "SegmentedImage", SimpleNamespace(list_by_item_id=AsyncMock(return_value=fake_segmented_records)), create=True), \
         patch.object(parts_module, "MilvusManager", SimpleNamespace(list_item_index=AsyncMock(return_value={}))), \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager), \
         patch.object(parts_module, "date_to_str", side_effect=lambda _value: "2026-04-27 11:39:23"):
        res = asyncio.run(parts_module.RailwayPartsManager.get_item_detail(101))

    assert len(res.images_index_list) == 1
    assert res.images_index_list[0].image_id == "9001"
    assert res.images_index_list[0].image_url == "bfr-ai-files/segmented/9001.jpg"
    assert res.images[0].image_url == "bfr-ai-files/source-a.jpg"


def test_get_item_detail_does_not_persist_reconstruction_result_during_read():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(
        id=101,
        obj_url=None,
        height=None,
        width=None,
        long=None,
        weight=None,
        source_video_path=None,
        item_name="橡胶套",
        item_code="40000543491",
        time_created=None,
        time_updated=None,
        size_str=None,
    )
    fake_state_manager = MagicMock()
    fake_state_manager.get_indexed_images_by_item_id.return_value = {}
    fake_reconstruction_manager = SimpleNamespace(
        ensure_item_result_persisted=AsyncMock(),
    )

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.reconstruction_service": SimpleNamespace(
                ReconstructionManager=fake_reconstruction_manager
            )
        },
    ), patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "get_images", MagicMock(return_value=_async_iter([]))), \
         patch.object(parts_module, "SegmentedImage", SimpleNamespace(list_by_item_id=AsyncMock(return_value=[])), create=True), \
         patch.object(parts_module, "MilvusManager", SimpleNamespace(list_item_index=AsyncMock(return_value={}))), \
         patch.object(parts_module, "MilvusStateManagerV2", return_value=fake_state_manager), \
         patch.object(parts_module, "date_to_str", side_effect=lambda _value: "2026-04-27 11:39:23"):
        asyncio.run(parts_module.RailwayPartsManager.get_item_detail(101))

    fake_reconstruction_manager.ensure_item_result_persisted.assert_not_awaited()
