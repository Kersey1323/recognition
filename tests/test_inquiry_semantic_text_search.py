import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.search_history import MatchedImage, SearchResultItem, SearchResults
from csrcqsf.modules.railway_parts.schemas.search import SearchItem, SearchRes
from csrcqsf.modules.railway_parts.services import search_service
from csrcqsf.modules.railway_parts.services.text_search_grouping import (
    aggregate_text_search_items_by_name,
)


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
        assert item_ids == [1, 2]
        return [
            SimpleNamespace(id=11, item_id=1, image_url="first.jpg"),
            SimpleNamespace(id=21, item_id=2, image_url="filter.jpg"),
        ]

    @classmethod
    async def list_histories_by_item_ids(cls, session, item_ids):
        assert item_ids == [1, 2]
        return []


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
    assert search_kwargs["top_k"] == 100
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


def test_agent_switch_controls_global_text_history_boundary():
    cutoff = datetime(2026, 3, 5, 10, 30, 26)
    semantic_service = SimpleNamespace(search=AsyncMock(return_value=[]))
    runtime = SimpleNamespace(get_id=lambda: 1004, SearchRes=SearchRes)
    manager_cls = SimpleNamespace(_persist_v2_search_history=AsyncMock())

    with patch.object(
        search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ), patch.object(search_service, "agent_running", False):
        asyncio.run(
            search_service.search_v2_by_text(
                manager_cls,
                query_text="门控器",
                source_inquiry_id="current-inquiry",
                source_inquiry_time=cutoff,
                runtime=runtime,
            )
        )

    assert semantic_service.search.await_args.kwargs == {
        "query_text": "门控器",
        "top_k": 100,
        "item_ids": None,
    }

    semantic_service.search.reset_mock()
    with patch.object(
        search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ), patch.object(search_service, "agent_running", True):
        asyncio.run(
            search_service.search_v2_by_text(
                manager_cls,
                query_text="门控器",
                source_inquiry_id="current-inquiry",
                source_inquiry_time=cutoff,
                runtime=runtime,
            )
        )

    assert semantic_service.search.await_args.kwargs == {
        "query_text": "门控器",
        "top_k": 100,
        "item_ids": None,
        "exclude_inquiry_id": "current-inquiry",
        "before_inquiry_time": cutoff,
    }


def test_direct_text_search_reranks_with_item_names():
    semantic_service = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "distance": 0.90,
                    "entity": {
                        "item_id": 1,
                        "description": "温水器",
                        "inquiry_id": "inq-1",
                    },
                },
                {
                    "distance": 0.80,
                    "entity": {
                        "item_id": 2,
                        "description": "电热开水器",
                        "inquiry_id": "inq-2",
                    },
                },
            ]
        )
    )
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(id=1, item_code="CODE-1", item_name="温水器"),
                SimpleNamespace(id=2, item_code="CODE-2", item_name="电热开水器"),
            ]
        ),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )
    persist = AsyncMock()
    runtime = SimpleNamespace(
        get_id=lambda: 1003,
        SessionLocal=lambda: _AsyncSessionContext(),
        ContextualSearchRepository=repository,
        SearchItem=SearchItem,
        SearchRes=SearchRes,
    )

    with patch.object(
        search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ):
        response = asyncio.run(
            search_service.search_v2_by_text(
                SimpleNamespace(_persist_v2_search_history=persist),
                query_text="电热开水器（海能）",
                top_k=2,
                runtime=runtime,
            )
        )

    assert [item.item_id for item in response.data] == ["2", "1"]
    assert response.data[0].matched_description == "电热开水器"
    assert response.data[0].rate > response.data[1].rate


def test_direct_text_search_fetches_one_thousand_candidates_once_before_grouping():
    class DeepSemanticService:
        def __init__(self):
            self.requested_limits = None

        async def search_candidate_batches(self, query_text, *, candidate_limits, **kwargs):
            self.requested_limits = candidate_limits
            yield [
                {
                    "distance": 0.93,
                    "entity": {"item_id": 1, "description": "铰链", "inquiry_id": "inq-1"},
                },
                {
                    "distance": 0.92,
                    "entity": {"item_id": 2, "description": "铰链", "inquiry_id": "inq-2"},
                },
                {
                    "distance": 0.80,
                    "entity": {"item_id": 3, "description": "门控器", "inquiry_id": "inq-3"},
                },
            ]

    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(
            side_effect=lambda _session, item_ids: [
                item
                for item in [
                    SimpleNamespace(id=1, item_code="CODE-1", item_name=" ＡＢＣ  铰链 "),
                    SimpleNamespace(id=2, item_code="CODE-2", item_name="abc 铰链"),
                    SimpleNamespace(id=3, item_code="CODE-3", item_name="门控器"),
                ]
                if item.id in item_ids
            ]
        ),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )
    semantic_service = DeepSemanticService()
    persist = AsyncMock()
    runtime = SimpleNamespace(
        get_id=lambda: 1005,
        SessionLocal=lambda: _AsyncSessionContext(),
        ContextualSearchRepository=repository,
        SearchItem=SearchItem,
        SearchRes=SearchRes,
    )

    with patch.object(
        search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ):
        response = asyncio.run(
            search_service.search_v2_by_text(
                SimpleNamespace(_persist_v2_search_history=persist),
                query_text="铰链",
                top_k=2,
                runtime=runtime,
            )
        )

    assert semantic_service.requested_limits == (1000,)
    repository.list_items_by_ids.assert_awaited_once()
    repository.list_histories_by_item_ids.assert_awaited_once()
    repository.list_first_images_by_item_ids.assert_awaited_once()
    assert [item.item_name.strip() for item in response.data] == ["ＡＢＣ  铰链", "门控器"]
    assert [member.item_code for member in response.data[0].group_members] == [
        "CODE-1",
        "CODE-2",
    ]
    assert response.data[0].rate >= response.data[1].rate
    assert persist.await_args.kwargs["search_items"][0].group_members[1].item_code == "CODE-2"


def test_empty_item_names_remain_separate_groups_by_item_code():
    grouped = aggregate_text_search_items_by_name(
        [
            SearchItem(item_id="1", item_code="CODE-1", item_name="", rate=0.9),
            SearchItem(item_id="2", item_code="CODE-2", item_name=" ", rate=0.8),
        ],
        limit=20,
    )

    assert [item.item_code for item in grouped] == ["CODE-1", "CODE-2"]
    assert [[member.item_code for member in item.group_members] for item in grouped] == [
        ["CODE-1"],
        ["CODE-2"],
    ]
