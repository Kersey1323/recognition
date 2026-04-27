import asyncio
import io
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys

from PIL import Image

from csrcqsf.models.search_history import SearchHistory


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

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.data.milvus": SimpleNamespace(milvus_client=MagicMock()),
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

    _import_railway_parts_manager._cached = (
        parts_module.RailwayPartsManager,
        parts_module,
    )
    return _import_railway_parts_manager._cached


def _make_upload_bytes():
    image = Image.new("RGB", (4, 4), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_search_v2_by_text_persists_query_text_after_success():
    session = AsyncMock()

    def _add(obj):
        session.added = obj

    session.add = MagicMock(side_effect=_add)

    fake_hit = {
        "entity": {
            "item_id": 1935558010375340032,
            "item_name": "螺栓M8X22",
            "item_code": "11010150131",
            "image_url": "bfr-ai-files/bolt.jpg",
        },
        "distance": 0.98,
    }
    fake_item = SimpleNamespace(
        id=1935558010375340032,
        item_code="11010150131",
        item_name="螺栓M8X22",
    )

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    with patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)):
        manager_cls.return_value.search_by_text = AsyncMock(return_value=[fake_hit])
        result = asyncio.run(RailwayPartsManager.search_v2_by_text("螺栓", top_k=5))

    assert result.data[0].item_code == "11010150131"
    assert isinstance(session.added, SearchHistory)
    assert session.added.search_result_item_code == "11010150131"
    assert session.added.query_text == "螺栓"
    assert session.added.query_image is None
    assert session.added.search_parameter is None
    assert session.added.search_results.items[0].item_id == str(fake_item.id)
    session.commit.assert_awaited()


def test_search_v2_by_image_uploads_query_image_and_persists_path():
    session = AsyncMock()

    def _add(obj):
        session.added = obj

    session.add = MagicMock(side_effect=_add)
    upload_file = SimpleNamespace(
        filename="query image.png",
        read=AsyncMock(return_value=_make_upload_bytes()),
    )
    fake_hit = {
        "entity": {
            "item_id": 1935558010375340032,
            "item_name": "螺栓M8X22",
            "item_code": "11010150131",
            "image_url": "bfr-ai-files/bolt.jpg",
        },
        "distance": 0.98,
    }

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    with patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(
             RailwayPartsManager,
             "_upload_v2_search_query_image",
             AsyncMock(return_value="bfr-search-history-files/query-images/20260427/1_query_image.png"),
         ):
        manager_cls.return_value.search_by_image = AsyncMock(return_value=[fake_hit])
        result = asyncio.run(RailwayPartsManager.search_v2_by_image(upload_file, top_k=5))

    assert result.data[0].item_code == "11010150131"
    assert session.added.query_text is None
    assert session.added.query_image == "bfr-search-history-files/query-images/20260427/1_query_image.png"
    session.commit.assert_awaited()


def test_search_v2_by_image_keeps_search_working_when_query_image_upload_fails():
    session = AsyncMock()

    def _add(obj):
        session.added = obj

    session.add = MagicMock(side_effect=_add)
    upload_file = SimpleNamespace(
        filename="broken.png",
        read=AsyncMock(return_value=_make_upload_bytes()),
    )
    fake_hit = {
        "entity": {
            "item_id": 1935558010375340032,
            "item_name": "螺栓M8X22",
            "item_code": "11010150131",
            "image_url": "bfr-ai-files/bolt.jpg",
        },
        "distance": 0.98,
    }

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    with patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(
             RailwayPartsManager,
             "_upload_v2_search_query_image",
             AsyncMock(side_effect=RuntimeError("boom")),
         ):
        manager_cls.return_value.search_by_image = AsyncMock(return_value=[fake_hit])
        result = asyncio.run(RailwayPartsManager.search_v2_by_image(upload_file, top_k=5))

    assert result.data[0].item_code == "11010150131"
    assert session.added.query_image is None
    session.commit.assert_awaited()


def test_list_v2_search_history_uses_explicit_query_fields_and_unknown_fallback():
    from csrcqsf.biz.railwayparts.api_models import SearchHistoryListReq
    from csrcqsf.models.search_history import SearchResults

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    text_history = SimpleNamespace(
        id=1,
        time_created=datetime(2026, 4, 23, 12, 0, 0),
        query_text="螺栓",
        query_image=None,
        search_results=SearchResults(items=[]),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="螺栓M8X22",
        search_result_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
    )
    image_history = SimpleNamespace(
        id=2,
        time_created=datetime(2026, 4, 23, 12, 1, 0),
        query_text=None,
        query_image="bfr-search-history-files/query-images/20260427/2_query.png",
        search_results=SearchResults(items=[]),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="螺栓M8X22",
        search_result_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
    )
    legacy_history = SimpleNamespace(
        id=3,
        time_created=datetime(2026, 4, 23, 12, 2, 0),
        query_text=None,
        query_image=None,
        search_results=SearchResults(items=[]),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name=None,
        search_result_item_code="",
        correct_item_name=None,
        correct_item_code=None,
    )
    page_result = SimpleNamespace(total=3, data=[text_history, image_history, legacy_history])

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchHistory, "list_search_history", AsyncMock(return_value=page_result)):
        res = asyncio.run(
            RailwayPartsManager.list_v2_search_history(SearchHistoryListReq(page=1, pageSize=10))
        )

    assert res.total == 3
    assert res.items[0].search_type == "text"
    assert res.items[0].query_text == "螺栓"
    assert res.items[1].search_type == "image"
    assert res.items[1].query_image.endswith("2_query.png")
    assert res.items[2].search_type == "unknown"
    assert res.items[2].query_text is None
    assert res.items[2].query_image is None
