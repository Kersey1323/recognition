import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, insert, select
from sqlalchemy.dialects import mysql

from csrcqsf.models.orm.search_history import SearchHistory, SearchReviewTicket, SearchParameters, SearchResults, SearchSnapshot
from csrcqsf.modules.railway_parts.repositories.search_history_repository import SearchHistoryRepository
from csrcqsf.modules.railway_parts.schemas.search import SearchHistoryDeleteRes
from csrcqsf.modules.railway_parts.services import search_service


class MemorySession:
    def __init__(self, connection):
        self.connection = connection
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.connection.execute(statement)

    async def scalar(self, statement):
        return (await self.execute(statement)).scalar()

    async def flush(self):
        pass


@pytest.fixture
def memory_session():
    engine = create_engine("sqlite://")
    SearchHistory.__table__.create(engine)
    SearchReviewTicket.__table__.create(engine)
    with engine.connect() as connection:
        histories = [
            {"id": identifier, "verify_status": status, "search_result_item_code": "TEST"}
            for identifier, status in enumerate(["pending", None, "wrong", "correct", "partial", "user_misjudged"], start=1)
        ]
        connection.execute(insert(SearchHistory), histories)
        connection.execute(insert(SearchReviewTicket), [
            {"id": identifier + 10, "history_id": identifier, "review_status": "open"}
            for identifier in [1, 2, 3, 4]
        ])
        connection.commit()
        yield MemorySession(connection)
    engine.dispose()


def test_pending_cleanup_preserves_feedback_and_new_records_and_deletes_associated_tickets(memory_session):
    async def run():
        upper_bound = await SearchHistoryRepository.get_pending_history_cleanup_upper_bound(memory_session)
        assert upper_bound == 2
        memory_session.connection.execute(insert(SearchHistory).values(
            id=100, verify_status="pending", search_result_item_code="NEW",
        ))
        first = await SearchHistoryRepository.delete_pending_history_batch_with_query_images(
            memory_session, upper_bound=upper_bound, batch_size=1,
        )
        second = await SearchHistoryRepository.delete_pending_history_batch_with_query_images(
            memory_session, upper_bound=upper_bound, batch_size=1,
        )
        empty = await SearchHistoryRepository.delete_pending_history_batch_with_query_images(
            memory_session, upper_bound=upper_bound, batch_size=1,
        )
        assert [row[0] for row in first + second] == [1, 2]
        assert empty == []

    asyncio.run(run())
    remaining = memory_session.connection.execute(select(SearchHistory.id)).scalars().all()
    assert remaining == [3, 4, 5, 6, 100]
    tickets = memory_session.connection.execute(select(SearchReviewTicket.history_id)).scalars().all()
    assert tickets == [3, 4]
    selections = [statement for statement in memory_session.statements if getattr(statement, "is_select", False) and statement._for_update_arg is not None]
    assert selections
    assert "FOR UPDATE" in str(selections[0].compile(dialect=mysql.dialect()))


def test_cleanup_commits_each_batch_before_removing_query_images_and_continues_after_storage_error():
    session = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    previous = SearchSnapshot(query_images=["history/old.jpg", "history/current.jpg"],
                              parameters=SearchParameters(), results=SearchResults(items=[]), searched_at=datetime(2026, 10, 14))
    repository = SimpleNamespace(
        get_pending_history_cleanup_upper_bound=AsyncMock(return_value=3),
        delete_pending_history_batch_with_query_images=AsyncMock(side_effect=[
            [(1, "history/current.jpg", ["history/current.jpg", "history/extra.jpg"], previous)],
            [(2, None, None, None), (3, "history/next.jpg", None, None)],
            [],
        ]),
    )
    events = []
    session.commit.side_effect = lambda: events.append("commit")

    def remove_object(bucket, key):
        events.append((bucket, key))
        if key == "current.jpg":
            raise RuntimeError("storage unavailable")

    remove = MagicMock(side_effect=remove_object)
    helpers = MagicMock(return_value=(None, SimpleNamespace(client=SimpleNamespace(remove_object=remove)),
                                     lambda path, default_bucket: tuple(path.split("/", 1))))
    runtime = SimpleNamespace(SessionLocal=lambda: context, SearchHistoryRepository=repository,
                              SearchHistory=SearchHistory, SearchHistoryDeleteRes=SearchHistoryDeleteRes,
                              minio_search_history_bucket="history", _get_minio_helpers=helpers,
                              logger=MagicMock())
    method = getattr(search_service, "cleanup_pending_v2_search_history", None)
    assert method is not None
    response = asyncio.run(method(object, runtime=runtime))
    assert response.deleted_count == 3
    assert remove.call_count == 4
    assert events[:4] == ["commit", ("history", "current.jpg"), ("history", "extra.jpg"), ("history", "old.jpg")]
    assert events[4:6] == ["commit", ("history", "next.jpg")]
    runtime.logger.warning.assert_called_once()


def test_empty_pending_cleanup_returns_zero_without_deleting_or_accessing_storage():
    session = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    repository = SimpleNamespace(get_pending_history_cleanup_upper_bound=AsyncMock(return_value=None),
                                 delete_pending_history_batch_with_query_images=AsyncMock())
    runtime = SimpleNamespace(SessionLocal=lambda: context, SearchHistoryRepository=repository,
                              SearchHistory=SearchHistory, SearchHistoryDeleteRes=SearchHistoryDeleteRes,
                              _get_minio_helpers=MagicMock())
    method = getattr(search_service, "cleanup_pending_v2_search_history", None)
    assert method is not None
    response = asyncio.run(method(object, runtime=runtime))
    assert response.deleted_count == 0
    repository.delete_pending_history_batch_with_query_images.assert_not_awaited()
    runtime._get_minio_helpers.assert_not_called()


def test_cleanup_endpoints_have_data_cleanup_category_and_pending_cleanup_needs_no_body():
    from csrcqsf.modules.railway_parts.routes import search_routes
    from csrcqsf.modules.railway_parts.services import parts_service
    from csrcqsf.modules.sgo.routes import sgo_router

    app = FastAPI()
    app.include_router(search_routes.parts_router)
    app.include_router(sgo_router)
    paths = app.openapi()["paths"]
    endpoint = "/railway/parts/v2/search/history/cleanup/pending"
    assert endpoint in paths
    for path, verb in [(endpoint, "post"), ("/sgo/sgo/parts/cleanup/non-a1/preview", "get"), ("/sgo/sgo/parts/cleanup/non-a1", "post")]:
        assert "数据清理" in paths[path][verb]["tags"]
        assert "业务-SGO集成" not in paths[path][verb]["tags"]
    assert "requestBody" not in paths[endpoint]["post"]

    async def run():
        session = AsyncMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch.object(parts_service, "SessionLocal", return_value=context), patch.object(
            SearchHistory, "get_pending_history_cleanup_upper_bound", AsyncMock(return_value=None),
        ) as upper_bound:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(endpoint)
            assert response.status_code == 200
            assert response.json()["deleted_count"] == 0
            upper_bound.assert_awaited_once_with(session)

    asyncio.run(run())
