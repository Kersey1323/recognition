import asyncio
from datetime import datetime
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


def test_repeated_search_replaces_image_and_keeps_only_old_current_as_previous():
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
    delete_mock.assert_awaited_once_with(["old-previous.jpg"], runtime=runtime)


def test_repeated_search_without_new_file_reuses_current_query_image():
    history = _pending_history()
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
                parameters=SearchParameters(item_name="冲洗按钮", search_mode="siglip"),
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


def test_only_pending_history_can_be_searched_again():
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


def test_revision_conflict_cleans_new_upload_and_does_not_overwrite_window():
    history = _pending_history()
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
