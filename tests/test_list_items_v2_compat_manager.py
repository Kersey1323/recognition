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
                v2_index_updated_at=datetime(2026, 10, 9, 10, 20, 30),
                time_created=datetime(2025, 10, 24, 15, 40, 16),
            )
        ],
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "list_items", AsyncMock(return_value=page_result)) as list_mock, \
         patch.object(parts_module.ItemInquiryHistory, "list_summary_by_item_ids", AsyncMock(return_value=[])), \
         patch.object(parts_module.InquiryTextIndexDocumentRepository, "list_features_by_item_ids", AsyncMock(return_value={})), \
         patch.object(parts_module.RailwayPartsManager, "list_item_images", AsyncMock(return_value=[])), \
         patch.object(parts_module, "run_sync", AsyncMock(return_value={})) as run_sync_mock, \
         patch.object(parts_module, "MilvusStateManagerV2") as state_cls:
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
    assert res.items[0].updated_at == "2026-10-09 10:20:30"
    assert run_sync_mock.await_count == 0
    state_cls.assert_not_called()


def test_list_item_passes_item_code_as_exact_filter():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    page_result = SimpleNamespace(total=0, data=[])

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "list_items", AsyncMock(return_value=page_result)) as list_mock, \
         patch.object(parts_module.ItemInquiryHistory, "list_summary_by_item_ids", AsyncMock(return_value=[])), \
         patch.object(parts_module.InquiryTextIndexDocumentRepository, "list_features_by_item_ids", AsyncMock(return_value={})), \
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


def test_list_item_passes_item_name_as_exact_filter():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    page_result = SimpleNamespace(total=0, data=[])

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "list_items", AsyncMock(return_value=page_result)) as list_mock, \
         patch.object(parts_module.ItemInquiryHistory, "list_summary_by_item_ids", AsyncMock(return_value=[])), \
         patch.object(parts_module.InquiryTextIndexDocumentRepository, "list_features_by_item_ids", AsyncMock(return_value={})), \
         patch.object(parts_module.RailwayPartsManager, "list_item_images", AsyncMock(return_value=[])):
        asyncio.run(
            parts_module.RailwayPartsManager.list_item(
                ListItemReq(page=1, pageSize=20, item_name="橡胶套")
            )
        )

    assert list_mock.await_args.kwargs["item_name"] == "橡胶套"


def test_list_item_passes_vehicle_batch_as_exact_filter():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    page_result = SimpleNamespace(total=0, data=[])

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "list_items", AsyncMock(return_value=page_result)) as list_mock, \
         patch.object(parts_module.ItemInquiryHistory, "list_summary_by_item_ids", AsyncMock(return_value=[])), \
         patch.object(parts_module.InquiryTextIndexDocumentRepository, "list_features_by_item_ids", AsyncMock(return_value={})), \
         patch.object(parts_module.RailwayPartsManager, "list_item_images", AsyncMock(return_value=[])):
        asyncio.run(
            parts_module.RailwayPartsManager.list_item(
                ListItemReq(page=1, pageSize=20, vehicle_batch="SFE27")
            )
        )

    assert list_mock.await_args.kwargs["vehicle_batch"] == "SFE27"


def test_list_item_filters_inquiry_records_from_local_history():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    page_result = SimpleNamespace(total=0, data=[])

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "list_items", AsyncMock(return_value=page_result)) as list_mock, \
         patch.object(parts_module.ItemInquiryHistory, "list_summary_by_item_ids", AsyncMock(return_value=[])), \
         patch.object(parts_module.InquiryTextIndexDocumentRepository, "list_features_by_item_ids", AsyncMock(return_value={})), \
         patch.object(parts_module.RailwayPartsManager, "list_item_images", AsyncMock(return_value=[])):
        asyncio.run(
            parts_module.RailwayPartsManager.list_item(
                ListItemReq(page=1, pageSize=20, has_inquery_code=1)
            )
        )

    assert list_mock.await_args.kwargs["has_inquiry_history"] is True


def test_list_item_adds_batched_images_and_all_inquiry_numbers_for_current_page():
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
                source_video_path=None,
                has_v2_index=0,
                v2_indexed_image_num=0,
                time_created=datetime(2025, 10, 24, 15, 40, 16),
            )
        ],
    )
    inquiry_rows = [(101, ["CX20260802001", "CX20260729001"], 2)]
    image_rows = [
        SimpleNamespace(item_id=101, image_url="bfr-ai-files/items/101/a.jpg"),
        SimpleNamespace(item_id=101, image_url="bfr-ai-files/items/101/b.jpg"),
    ]

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "list_items", AsyncMock(return_value=page_result)), \
         patch.object(parts_module.RailwayPartsManager, "list_item_images", AsyncMock(return_value=image_rows)), \
         patch.object(parts_module.ItemInquiryHistory, "list_summary_by_item_ids", AsyncMock(return_value=inquiry_rows)) as inquiry_mock, \
         patch.object(
             parts_module.InquiryTextIndexDocumentRepository,
             "list_features_by_item_ids",
             AsyncMock(return_value={101: ["司机室橡胶套", "橡胶保护套"]}),
         ) as feature_mock, \
         patch.object(parts_module, "run_sync", AsyncMock(return_value={})):
        res = asyncio.run(
            parts_module.RailwayPartsManager.list_item(
                ListItemReq(page=1, pageSize=20)
            )
        )

    inquiry_mock.assert_awaited_once_with(session, [101])
    feature_mock.assert_awaited_once_with(session, [101])
    assert res.items[0].images_url == [
        "bfr-ai-files/items/101/a.jpg",
        "bfr-ai-files/items/101/b.jpg",
    ]
    assert res.items[0].inquiry_nums == ["CX20260802001", "CX20260729001"]
    assert res.items[0].inquiry_count == 2
    assert res.items[0].features == ["司机室橡胶套", "橡胶保护套"]
    assert res.items[0].features_num == 2
