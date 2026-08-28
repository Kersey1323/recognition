import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.search_history import MatchedImage, SearchResultItem, SearchResults
from csrcqsf.modules.railway_parts.schemas.search import SearchItem, SearchRes
from csrcqsf.modules.railway_parts.services import search_service


class _AsyncSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Repository:
    @classmethod
    async def list_items_by_ids(cls, session, item_ids):
        assert item_ids == [1, 999, 2]
        return [
            SimpleNamespace(id=1, item_code="CODE-1", item_name="窗帘组件"),
            SimpleNamespace(id=2, item_code="CODE-2", item_name="滤网组件"),
        ]

    @classmethod
    async def list_first_images_by_item_ids(cls, session, item_ids):
        assert item_ids == [1, 999, 2]
        return [
            SimpleNamespace(id=11, item_id=1, image_url="first.jpg"),
            SimpleNamespace(id=21, item_id=2, image_url="filter.jpg"),
        ]


def test_direct_text_search_uses_inquiry_semantics_and_persists_explanation():
    semantic_service = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "distance": 0.93,
                    "entity": {
                        "item_id": 1,
                        "description": "监控室对面窗帘",
                        "inquiry_id": "inq-1",
                    },
                },
                {
                    "distance": 0.92,
                    "entity": {
                        "item_id": 999,
                        "description": "已经删除的配件",
                        "inquiry_id": "inq-missing",
                    },
                },
                {
                    "distance": 0.88,
                    "entity": {
                        "item_id": 2,
                        "description": "电茶炉进水口前面的滤网",
                        "inquiry_id": "inq-2",
                    },
                },
            ]
        )
    )
    persist = AsyncMock()
    manager_cls = SimpleNamespace(_persist_v2_search_history=persist)
    runtime = SimpleNamespace(
        get_id=lambda: 1001,
        SessionLocal=lambda: _AsyncSessionContext(),
        ContextualSearchRepository=_Repository,
        SearchItem=SearchItem,
        SearchRes=SearchRes,
        MatchedImage=MatchedImage,
        SearchResultItem=SearchResultItem,
        SearchResults=SearchResults,
        _get_bound_milvus_manager_v2_cls=lambda: (_ for _ in ()).throw(
            AssertionError("direct text search must not use SigLIP")
        ),
    )

    with patch.object(
        search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
        create=True,
    ):
        response = asyncio.run(
            search_service.search_v2_by_text(
                manager_cls,
                query_text="监控室对面窗帘",
                top_k=2,
                runtime=runtime,
            )
        )

    assert [item.item_id for item in response.data] == ["1", "2"]
    assert response.data[0].image_url == "first.jpg"
    assert response.data[0].matched_images == []
    assert response.data[0].matched_description == "监控室对面窗帘"
    assert response.data[0].matched_inquiry_id == "inq-1"
    semantic_service.search.assert_awaited_once()
    search_kwargs = semantic_service.search.await_args.kwargs
    assert search_kwargs["query_text"] == "监控室对面窗帘"
    assert search_kwargs["item_ids"] is None
    assert search_kwargs["top_k"] >= 2
    persisted = persist.await_args.kwargs["search_items"]
    assert persisted[0].matched_description == "监控室对面窗帘"


def test_direct_text_search_allows_empty_semantic_results():
    semantic_service = SimpleNamespace(search=AsyncMock(return_value=[]))
    persist = AsyncMock()
    manager_cls = SimpleNamespace(_persist_v2_search_history=persist)
    runtime = SimpleNamespace(
        get_id=lambda: 1002,
        SessionLocal=lambda: _AsyncSessionContext(),
        ContextualSearchRepository=_Repository,
        SearchItem=SearchItem,
        SearchRes=SearchRes,
    )

    with patch.object(
        search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
        create=True,
    ):
        response = asyncio.run(
            search_service.search_v2_by_text(
                manager_cls,
                query_text="不存在的自然语言描述",
                top_k=5,
                runtime=runtime,
            )
        )

    assert response.data == []
    persist.assert_awaited_once()
