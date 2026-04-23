import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys

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

    _import_railway_parts_manager._cached = parts_module.RailwayPartsManager
    return parts_module.RailwayPartsManager


def test_search_v2_by_text_persists_history_after_success():
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

    RailwayPartsManager = _import_railway_parts_manager()

    with patch("csrcqsf.biz.railwayparts.parts.MilvusManagerV2") as manager_cls, \
         patch("csrcqsf.biz.railwayparts.parts.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.biz.railwayparts.parts.Items.get_item_by_id", AsyncMock(return_value=fake_item)):
        manager_cls.return_value.search_by_text = AsyncMock(return_value=[fake_hit])
        result = asyncio.run(RailwayPartsManager.search_v2_by_text("螺栓", top_k=5))

    assert result.data[0].item_code == "11010150131"
    assert isinstance(session.added, SearchHistory)
    assert session.added.search_result_item_code == "11010150131"
    assert session.added.search_parameter.features == ["螺栓"]
    session.commit.assert_awaited()


def test_list_v2_search_history_maps_search_type():
    from csrcqsf.biz.railwayparts.api_models import SearchHistoryListReq
    from csrcqsf.models.search_history import SearchParameters, SearchResults

    RailwayPartsManager = _import_railway_parts_manager()

    history = SimpleNamespace(
        id=1,
        time_created=datetime(2026, 4, 23, 12, 0, 0),
        search_parameter=SearchParameters(features=["螺栓"], images=[]),
        search_results=SearchResults(items=[]),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="螺栓M8X22",
        search_result_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
    )
    page_result = SimpleNamespace(total=1, data=[history])

    with patch("csrcqsf.biz.railwayparts.parts.SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch("csrcqsf.biz.railwayparts.parts.SearchHistory.list_search_history", AsyncMock(return_value=page_result)):
        res = asyncio.run(RailwayPartsManager.list_v2_search_history(SearchHistoryListReq(page=1, pageSize=10)))

    assert res.total == 1
    assert res.items[0].search_type == "text"
    assert res.items[0].history_id == "1"
