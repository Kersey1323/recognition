import asyncio
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from csrcqsf.models.orm.search_history import (
    MatchedImage,
    SearchHistory,
    SearchParameters,
    SearchResultItem,
    SearchResults,
    SearchSnapshot,
)
from csrcqsf.modules.railway_parts.schemas.search import (
    ContextualSearchRes,
    ContextualSearchSnapshotRes,
    SearchItem,
)
from csrcqsf.modules.railway_parts.services import contextual_search_service


class _Session:
    def __init__(self):
        self.added = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    def add(self, row):
        self.added.append(row)


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _runtime(session, repository):
    return SimpleNamespace(
        SessionLocal=lambda: _AsyncSessionContext(session),
        ContextualSearchRepository=repository,
        SearchHistory=SearchHistory,
        SearchParameters=SearchParameters,
        SearchResults=SearchResults,
        SearchSnapshot=SearchSnapshot,
        SearchResultItem=SearchResultItem,
        MatchedImage=MatchedImage,
        SearchItem=SearchItem,
        ContextualSearchRes=ContextualSearchRes,
        ContextualSearchSnapshotRes=ContextualSearchSnapshotRes,
        datetime=datetime,
        get_id=lambda: 2048696242753638400,
        logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )


def _item(item_id: str, name: str = "便器冲洗按钮"):
    return SearchItem(
        item_id=item_id,
        item_code=f"CODE-{item_id}",
        item_name=name,
        image_url=f"result-{item_id}.jpg",
        rate=0.9,
    )


def _pending_history():
    return SearchHistory(
        id=101,
        search_result_item_name="旧结果",
        search_result_item_code="OLD",
        search_parameter=SearchParameters(search_mode="siglip"),
        query_image="old-current.jpg",
        query_images_json=None,
        search_equipment="web",
        verify_status="pending",
        search_results=SearchResults(items=[]),
        previous_search_snapshot=SearchSnapshot(
            query_images=["old-previous.jpg"],
            parameters=SearchParameters(search_mode="siglip"),
            results=SearchResults(items=[]),
            searched_at=datetime(2026, 8, 18, 9, 0, 0),
        ),
        search_revision=2,
        time_created=datetime(2026, 8, 18, 8, 0, 0),
        time_updated=datetime(2026, 8, 18, 10, 0, 0),
    )


def test_vehicle_candidates_are_loaded_from_local_inquiry_history():
    session = _Session()
    repository = SimpleNamespace(
        list_history_item_ids_by_vehicle=AsyncMock(return_value=[101, 102]),
    )
    runtime = _runtime(session, repository)

    item_ids = asyncio.run(
        contextual_search_service._vehicle_candidate_item_ids(
            "SFE27",
            runtime=runtime,
        )
    )

    assert item_ids == [101, 102]
    repository.list_history_item_ids_by_vehicle.assert_awaited_once_with(
        session,
        "SFE27",
    )


def test_first_contextual_search_creates_one_pending_history():
    session = _Session()
    repository = SimpleNamespace()
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "_prepare_uploaded_query_images",
        AsyncMock(return_value=(["new.jpg"], [object()])),
    ), patch.object(
        contextual_search_service,
        "_execute_contextual_search",
        AsyncMock(return_value=([_item("1")], None)),
    ):
        response = asyncio.run(
            contextual_search_service.search_v2_contextual(
                object,
                history_id=None,
                files=[object()],
                vehicle_batch="SFE27",
                search_mode="siglip",
                runtime=runtime,
            )
        )

    assert response.history_id == "2048696242753638400"
    assert response.previous is None
    assert response.current.query_images == ["new.jpg"]
    assert response.current.data[0].item_id == "1"
    assert len(session.added) == 1
    assert session.added[0].verify_status == "pending"
    assert session.added[0].search_revision == 1
    session.commit.assert_awaited_once()


def test_first_contextual_search_accepts_description_without_image():
    session = _Session()
    repository = SimpleNamespace()
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "_prepare_uploaded_query_images",
        AsyncMock(),
    ) as prepare_mock, patch.object(
        contextual_search_service,
        "_execute_contextual_search",
        AsyncMock(return_value=([_item("1")], None)),
    ) as execute_mock:
        response = asyncio.run(
            contextual_search_service.search_v2_contextual(
                object,
                history_id=None,
                files=[],
                item_description="厕所里的马桶盖",
                runtime=runtime,
            )
        )

    prepare_mock.assert_not_awaited()
    assert execute_mock.await_args.kwargs["query_images"] == []
    assert response.current.query_images == []
    assert response.current.parameters.item_description == "厕所里的马桶盖"
    assert session.added[0].query_text == "厕所里的马桶盖"


@pytest.mark.parametrize("status", ["pending", "wrong"])
def test_repeated_search_replaces_image_and_keeps_only_old_current_as_previous(status):
    history = _pending_history()
    history.verify_status = status
    session = _Session()
    repository = SimpleNamespace(
        get_history=AsyncMock(return_value=history),
        update_history_window=AsyncMock(return_value=True),
    )
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "_prepare_uploaded_query_images",
        AsyncMock(return_value=(["replacement.jpg"], [object()])),
    ), patch.object(
        contextual_search_service,
        "_execute_contextual_search",
        AsyncMock(return_value=([_item("2")], None)),
    ), patch.object(
        contextual_search_service,
        "_delete_query_images",
        AsyncMock(),
    ) as delete_mock:
        response = asyncio.run(
            contextual_search_service.search_v2_contextual(
                object,
                history_id=101,
                files=[object()],
                item_name="便器冲洗按钮",
                search_mode="siglip",
                runtime=runtime,
            )
        )

    assert response.history_id == "101"
    assert response.previous.query_images == ["old-current.jpg"]
    assert response.current.query_images == ["replacement.jpg"]
    update_kwargs = repository.update_history_window.await_args.kwargs
    assert update_kwargs["expected_revision"] == 2
    assert update_kwargs["previous_snapshot"].query_images == ["old-current.jpg"]
    session.commit.assert_awaited_once()
    delete_mock.assert_awaited_once_with(["old-previous.jpg"], runtime=runtime)


@pytest.mark.parametrize("status", ["pending", "wrong"])
def test_repeated_search_without_new_file_reuses_current_query_image(status):
    history = _pending_history()
    history.verify_status = status
    session = _Session()
    repository = SimpleNamespace(
        get_history=AsyncMock(return_value=history),
        update_history_window=AsyncMock(return_value=True),
    )
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "_load_query_images",
        AsyncMock(return_value=[object()]),
    ) as load_mock, patch.object(
        contextual_search_service,
        "_execute_contextual_search",
        AsyncMock(return_value=([_item("2")], None)),
    ), patch.object(
        contextual_search_service,
        "_delete_query_images",
        AsyncMock(),
    ):
        response = asyncio.run(
            contextual_search_service.search_v2_contextual(
                object,
                history_id=101,
                files=None,
                item_name="便器冲洗按钮",
                runtime=runtime,
            )
        )

    load_mock.assert_awaited_once_with(["old-current.jpg"], runtime=runtime)
    assert response.current.query_images == ["old-current.jpg"]
    update_kwargs = repository.update_history_window.await_args.kwargs
    assert update_kwargs["query_images"] == ["old-current.jpg"]


def test_three_successful_searches_keep_only_previous_and_current_snapshots():
    history_before_second = _pending_history()
    history_before_third = _pending_history()
    history_before_third.previous_search_snapshot = SearchSnapshot(
        query_images=["old-current.jpg"],
        parameters=SearchParameters(search_mode="siglip"),
        results=SearchResults(items=[]),
        searched_at=datetime(2026, 8, 18, 10, 0, 0),
    )
    history_before_third.query_image = "search-2.jpg"
    history_before_third.search_revision = 3
    history_before_third.time_updated = datetime(2026, 8, 18, 11, 0, 0)
    session = _Session()
    repository = SimpleNamespace(
        get_history=AsyncMock(
            side_effect=[history_before_second, history_before_third]
        ),
        update_history_window=AsyncMock(return_value=True),
    )
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "_prepare_uploaded_query_images",
        AsyncMock(
            side_effect=[
                (["search-2.jpg"], [object()]),
                (["search-3.jpg"], [object()]),
            ]
        ),
    ), patch.object(
        contextual_search_service,
        "_execute_contextual_search",
        AsyncMock(side_effect=[([_item("2")], None), ([_item("3")], None)]),
    ), patch.object(
        contextual_search_service,
        "_delete_query_images",
        AsyncMock(),
    ) as delete_mock:
        asyncio.run(
            contextual_search_service.search_v2_contextual(
                object,
                history_id=101,
                files=[object()],
                runtime=runtime,
            )
        )
        response = asyncio.run(
            contextual_search_service.search_v2_contextual(
                object,
                history_id=101,
                files=[object()],
                runtime=runtime,
            )
        )

    assert response.previous.query_images == ["search-2.jpg"]
    assert response.current.query_images == ["search-3.jpg"]
    second_update = repository.update_history_window.await_args_list[0].kwargs
    third_update = repository.update_history_window.await_args_list[1].kwargs
    assert second_update["previous_snapshot"].query_images == ["old-current.jpg"]
    assert second_update["query_images"] == ["search-2.jpg"]
    assert third_update["previous_snapshot"].query_images == ["search-2.jpg"]
    assert third_update["query_images"] == ["search-3.jpg"]
    assert delete_mock.await_args_list[0].args[0] == ["old-previous.jpg"]
    assert delete_mock.await_args_list[1].args[0] == ["old-current.jpg"]


def test_empty_result_is_a_successful_search_and_shifts_the_window():
    history = _pending_history()
    session = _Session()
    repository = SimpleNamespace(
        get_history=AsyncMock(return_value=history),
        update_history_window=AsyncMock(return_value=True),
    )
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "_prepare_uploaded_query_images",
        AsyncMock(return_value=(["replacement.jpg"], [object()])),
    ), patch.object(
        contextual_search_service,
        "_execute_contextual_search",
        AsyncMock(return_value=([], "车型 SFE27 下没有可检索配件")),
    ), patch.object(
        contextual_search_service,
        "_delete_query_images",
        AsyncMock(),
    ):
        response = asyncio.run(
            contextual_search_service.search_v2_contextual(
                object,
                history_id=101,
                files=[object()],
                vehicle_batch="SFE27",
                runtime=runtime,
            )
        )

    assert response.previous.query_images == ["old-current.jpg"]
    assert response.current.data == []
    assert response.message == "车型 SFE27 下没有可检索配件"
    update_kwargs = repository.update_history_window.await_args.kwargs
    assert update_kwargs["results"].items == []
    assert update_kwargs["top_item"] is None


def test_failed_replacement_search_removes_new_upload_without_shifting_window():
    history = _pending_history()
    session = _Session()
    repository = SimpleNamespace(
        get_history=AsyncMock(return_value=history),
        update_history_window=AsyncMock(),
    )
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "_prepare_uploaded_query_images",
        AsyncMock(return_value=(["replacement.jpg"], [object()])),
    ), patch.object(
        contextual_search_service,
        "_execute_contextual_search",
        AsyncMock(side_effect=RuntimeError("milvus unavailable")),
    ), patch.object(
        contextual_search_service,
        "_delete_query_images",
        AsyncMock(),
    ) as delete_mock:
        with pytest.raises(RuntimeError, match="milvus unavailable"):
            asyncio.run(
                contextual_search_service.search_v2_contextual(
                    object,
                    history_id=101,
                    files=[object()],
                    item_name="按钮",
                    runtime=runtime,
                )
            )

    repository.update_history_window.assert_not_awaited()
    delete_mock.assert_awaited_once_with(["replacement.jpg"], runtime=runtime)


def test_text_recall_does_not_appear_as_a_matched_image():
    session = _Session()
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(
            return_value=[SimpleNamespace(id=1, item_code="CODE-1", item_name="冲洗按钮")]
        ),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )
    manager = SimpleNamespace(
        search_by_image=AsyncMock(
            return_value=[
                {
                    "distance": 0.8,
                    "entity": {
                        "item_id": 1,
                        "item_code": "CODE-1",
                        "item_name": "冲洗按钮",
                        "image_url": "visual.jpg",
                    },
                }
            ]
        ),
    )
    semantic_service = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "distance": 0.95,
                    "entity": {
                        "item_id": 1,
                        "description": "卫生间墙面上的冲洗按钮",
                        "inquiry_id": "inq-1",
                    },
                }
            ]
        )
    )
    runtime = _runtime(session, repository)
    runtime._get_milvus_manager_v2_cls = lambda: lambda: manager

    with patch.object(
        contextual_search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
        create=True,
    ):
        results, message = asyncio.run(
            contextual_search_service._execute_contextual_search(
                object,
                query_images=[object()],
                parameters=SearchParameters(
                    item_description="冲洗按钮",
                    search_mode="siglip",
                ),
                runtime=runtime,
            )
        )

    assert message is None
    assert results[0].image_url == "visual.jpg"
    assert [match.image_url for match in results[0].matched_images] == ["visual.jpg"]
    assert results[0].matched_description == "卫生间墙面上的冲洗按钮"
    assert results[0].matched_inquiry_id == "inq-1"
    semantic_service.search.assert_awaited_once_with(
        "冲洗按钮",
        top_k=100,
        item_ids=None,
    )


def test_description_only_search_skips_image_model_and_uses_representative_image():
    session = _Session()
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(
            return_value=[SimpleNamespace(id=1, item_code="CODE-1", item_name="马桶盖")]
        ),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(
            return_value=[SimpleNamespace(item_id=1, image_url="first.jpg")]
        ),
    )
    semantic_service = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "distance": 0.93,
                    "entity": {
                        "item_id": 1,
                        "description": "厕所里的马桶盖",
                        "inquiry_id": "inq-1",
                    },
                }
            ]
        )
    )
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ):
        results, message = asyncio.run(
            contextual_search_service._execute_contextual_search(
                object,
                query_images=[],
                parameters=SearchParameters(item_description="厕所里的马桶盖"),
                runtime=runtime,
            )
        )

    assert message is None
    assert results[0].item_name == "马桶盖"
    assert results[0].image_url == "first.jpg"
    assert results[0].matched_description == "厕所里的马桶盖"
    assert results[0].matched_images == []


def test_agent_mode_removes_current_and_future_semantic_hits():
    cutoff = datetime(2026, 3, 5, 10, 30, 26)
    session = _Session()
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(id=1, item_code="CURRENT", item_name="当前询码"),
                SimpleNamespace(id=2, item_code="OLDER", item_name="历史询码"),
                SimpleNamespace(id=3, item_code="FUTURE", item_name="未来询码"),
            ]
        ),
        list_histories_by_item_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    item_id=2,
                    inquiry_id="older-inquiry",
                    inquiry_time=datetime(2026, 3, 4, 10, 0, 0),
                    inquiry_item_name="门控器",
                    return_item_name="门控器",
                    vehicle_batch="SFE28",
                    subordinate_component="内端门",
                    train_no="2256",
                    car_num="01",
                )
            ]
        ),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )
    semantic_service = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {"distance": 0.99, "entity": {"item_id": 1, "description": "门控器", "inquiry_id": "current-inquiry"}},
                {"distance": 0.98, "entity": {"item_id": 3, "description": "门控器", "inquiry_id": "future-inquiry"}},
                {"distance": 0.90, "entity": {"item_id": 2, "description": "门控器", "inquiry_id": "older-inquiry"}},
            ]
        )
    )
    runtime = _runtime(session, repository)

    with patch.object(contextual_search_service, "agent_running", True), patch.object(
        contextual_search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ):
        results, message = asyncio.run(
            contextual_search_service._execute_contextual_search(
                object,
                query_images=[],
                parameters=SearchParameters(
                    item_description="门控器",
                    source_inquiry_id="current-inquiry",
                    source_inquiry_time=cutoff,
                ),
                runtime=runtime,
            )
        )

    assert message is None
    assert [item.item_code for item in results] == ["OLDER"]
    repository.list_histories_by_item_ids.assert_awaited_once_with(
        session,
        [1, 3, 2],
        exclude_inquiry_id="current-inquiry",
        before_inquiry_time=cutoff,
    )


def test_agent_mode_keeps_catalog_names_without_inquiry_history():
    session = _Session()
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(return_value=[
            SimpleNamespace(id=1, item_code="40001", item_name="门控器"),
        ]),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )
    semantic_service = SimpleNamespace(search=AsyncMock(return_value=[
        {"distance": 0.9, "entity": {
            "item_id": 1, "description": "门控器", "document_key": "catalog:40001",
            "history_id": 0, "inquiry_id": "",
        }},
    ]))
    with patch.object(contextual_search_service, "agent_running", True), patch.object(
        contextual_search_service, "get_inquiry_semantic_index_service", return_value=semantic_service,
    ):
        results, _ = asyncio.run(contextual_search_service._execute_contextual_search(
            object, query_images=[], runtime=_runtime(session, repository),
            parameters=SearchParameters(item_description="门控器", source_inquiry_id="current",
                                        source_inquiry_time=datetime(2026, 3, 5)),
        ))
    assert [item.item_code for item in results] == ["40001"]


def test_agent_leakage_filter_is_disabled_by_default():
    cutoff = datetime(2026, 3, 5, 10, 30, 26)
    session = _Session()
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(id=1, item_code="CURRENT", item_name="门控器")
            ]
        ),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )
    semantic_service = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "distance": 0.99,
                    "entity": {
                        "item_id": 1,
                        "description": "门控器",
                        "inquiry_id": "current-inquiry",
                    },
                }
            ]
        )
    )
    runtime = _runtime(session, repository)

    with patch.object(contextual_search_service, "agent_running", False), patch.object(
        contextual_search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ):
        results, message = asyncio.run(
            contextual_search_service._execute_contextual_search(
                object,
                query_images=[],
                parameters=SearchParameters(
                    item_description="门控器",
                    source_inquiry_id="current-inquiry",
                    source_inquiry_time=cutoff,
                ),
                runtime=runtime,
            )
        )

    assert message is None
    assert [item.item_code for item in results] == ["CURRENT"]
    repository.list_histories_by_item_ids.assert_awaited_once_with(session, [1])


def test_contextual_search_returns_top_twenty_items():
    session = _Session()
    items = [
        SimpleNamespace(
            id=item_id,
            item_code=f"CODE-{item_id}",
            item_name=f"配件{item_id}",
        )
        for item_id in range(1, 26)
    ]
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(return_value=items),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )
    semantic_service = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "distance": 1 - item_id / 100,
                    "entity": {
                        "item_id": item_id,
                        "description": f"描述{item_id}",
                        "inquiry_id": f"inquiry-{item_id}",
                    },
                }
                for item_id in range(1, 26)
            ]
        )
    )
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ):
        results, message = asyncio.run(
            contextual_search_service._execute_contextual_search(
                object,
                query_images=[],
                parameters=SearchParameters(item_description="测试描述"),
                runtime=runtime,
            )
        )

    assert message is None
    assert len(results) == 20
    assert [result.item_code for result in results] == [
        f"CODE-{item_id}" for item_id in range(1, 21)
    ]
    repository.list_histories_by_item_ids.assert_awaited_once_with(
        session,
        list(range(1, 21)),
    )
    repository.list_first_images_by_item_ids.assert_awaited_once_with(
        session,
        list(range(1, 21)),
    )


def test_contextual_text_search_groups_same_names_and_keeps_all_codes():
    session = _Session()
    all_items = [
        SimpleNamespace(id=1, item_code="CODE-1", item_name=" ＡＢＣ  铰链 "),
        SimpleNamespace(id=2, item_code="CODE-2", item_name="abc 铰链"),
        SimpleNamespace(id=3, item_code="CODE-3", item_name="门控器"),
    ]
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(
            side_effect=lambda _session, item_ids: [
                item for item in all_items if item.id in item_ids
            ]
        ),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )

    class DeepSemanticService:
        def __init__(self):
            self.requested_limits = None

        async def search_candidate_batches(self, *args, **kwargs):
            self.requested_limits = kwargs["candidate_limits"]
            yield [
                {"distance": 0.93, "entity": {"item_id": 1, "description": "铰链", "inquiry_id": "i1"}},
                {"distance": 0.92, "entity": {"item_id": 2, "description": "铰链", "inquiry_id": "i2"}},
                {"distance": 0.80, "entity": {"item_id": 3, "description": "门控器", "inquiry_id": "i3"}},
            ]

    semantic_service = DeepSemanticService()
    runtime = _runtime(session, repository)
    with patch.object(
        contextual_search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ):
        results, message = asyncio.run(
            contextual_search_service._execute_contextual_search(
                object,
                query_images=[],
                parameters=SearchParameters(item_description="铰链"),
                runtime=runtime,
            )
        )

    assert message is None
    assert semantic_service.requested_limits == (1000,)
    repository.list_items_by_ids.assert_awaited_once()
    repository.list_histories_by_item_ids.assert_awaited_once()
    assert len(results) == 2
    assert [member.item_code for member in results[0].group_members] == [
        "CODE-1",
        "CODE-2",
    ]


def test_contextual_image_only_search_keeps_same_name_items_separate():
    session = _Session()
    repository = SimpleNamespace(
        list_items_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(id=1, item_code="CODE-1", item_name="铰链"),
                SimpleNamespace(id=2, item_code="CODE-2", item_name="铰链"),
            ]
        ),
        list_histories_by_item_ids=AsyncMock(return_value=[]),
        list_first_images_by_item_ids=AsyncMock(return_value=[]),
    )
    manager = SimpleNamespace(
        search_by_image=AsyncMock(
            return_value=[
                {
                    "distance": 0.91,
                    "entity": {"item_id": 1, "item_code": "CODE-1", "item_name": "铰链"},
                },
                {
                    "distance": 0.90,
                    "entity": {"item_id": 2, "item_code": "CODE-2", "item_name": "铰链"},
                },
            ]
        )
    )
    runtime = _runtime(session, repository)
    runtime._get_milvus_manager_v2_cls = lambda: lambda: manager

    results, message = asyncio.run(
        contextual_search_service._execute_contextual_search(
            object,
            query_images=[object()],
            parameters=SearchParameters(),
            runtime=runtime,
        )
    )

    assert message is None
    assert [item.item_code for item in results] == ["CODE-1", "CODE-2"]
    assert all(not item.group_members for item in results)


def test_exact_item_name_filters_candidates_and_missing_name_falls_back():
    exact_repository = SimpleNamespace(
        list_item_ids_by_exact_name=AsyncMock(return_value=[1, 2]),
    )
    fallback_repository = SimpleNamespace(
        list_item_ids_by_exact_name=AsyncMock(return_value=[]),
    )
    exact_runtime = _runtime(_Session(), exact_repository)
    fallback_runtime = _runtime(_Session(), fallback_repository)

    exact_ids = asyncio.run(
        contextual_search_service._item_name_candidate_item_ids(
            "便器冲洗按钮",
            runtime=exact_runtime,
        )
    )
    fallback_ids = asyncio.run(
        contextual_search_service._item_name_candidate_item_ids(
            "输入错误的名称",
            runtime=fallback_runtime,
        )
    )

    assert exact_ids == [1, 2]
    assert fallback_ids is None


def test_parts_manager_delegates_item_description():
    source_path = Path(
        "csrcqsf/modules/railway_parts/services/parts_service.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    manager = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RailwayPartsManager"
    )
    method = next(
        node
        for node in manager.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "search_v2_contextual"
    )

    assert "item_description" in [arg.arg for arg in method.args.kwonlyargs]
    delegated_call = next(node for node in ast.walk(method) if isinstance(node, ast.Call))
    assert "item_description" in [keyword.arg for keyword in delegated_call.keywords]


def test_correct_history_cannot_be_searched_again():
    history = _pending_history()
    history.verify_status = "correct"
    session = _Session()
    repository = SimpleNamespace(get_history=AsyncMock(return_value=history))
    runtime = _runtime(session, repository)

    with pytest.raises(contextual_search_service.ContextualSearchBusinessError) as exc:
        asyncio.run(
            contextual_search_service.search_v2_contextual(
                object,
                history_id=101,
                files=[object()],
                runtime=runtime,
            )
        )

    assert exc.value.status_code == 409


@pytest.mark.parametrize("status", ["pending", "wrong"])
def test_revision_conflict_cleans_new_upload_and_does_not_overwrite_window(status):
    history = _pending_history()
    history.verify_status = status
    session = _Session()
    repository = SimpleNamespace(
        get_history=AsyncMock(return_value=history),
        update_history_window=AsyncMock(return_value=False),
    )
    runtime = _runtime(session, repository)

    with patch.object(
        contextual_search_service,
        "_prepare_uploaded_query_images",
        AsyncMock(return_value=(["replacement.jpg"], [object()])),
    ), patch.object(
        contextual_search_service,
        "_execute_contextual_search",
        AsyncMock(return_value=([_item("2")], None)),
    ), patch.object(
        contextual_search_service,
        "_delete_query_images",
        AsyncMock(),
    ) as delete_mock:
        with pytest.raises(contextual_search_service.ContextualSearchBusinessError) as exc:
            asyncio.run(
                contextual_search_service.search_v2_contextual(
                    object,
                    history_id=101,
                    files=[object()],
                    item_name="按钮",
                    runtime=runtime,
                )
            )

    assert exc.value.status_code == 409
    session.rollback.assert_awaited_once()
    delete_mock.assert_awaited_once_with(["replacement.jpg"], runtime=runtime)
