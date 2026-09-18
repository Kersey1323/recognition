import asyncio
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.dialects import mysql

from csrcqsf.models.orm.search_history import (
    SearchHistory,
    SearchParameters,
    SearchResults,
    SearchSnapshot,
)
from csrcqsf.modules.railway_parts.repositories.contextual_search_repository import (
    ContextualSearchRepository,
)


class _ExecuteSession:
    def __init__(self, result):
        self.result = result
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.result


def test_vehicle_candidate_query_uses_complete_materiel_vehicle_relation():
    result = SimpleNamespace(all=lambda: [("19010001",), ("19010002",)])
    session = _ExecuteSession(result)

    codes = asyncio.run(
        ContextualSearchRepository.list_vehicle_item_codes(session, " sfe27 ")
    )

    sql = str(
        session.statements[0].compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert codes == {"19010001", "19010002"}
    assert "sgo_materiel_vehicle" in sql
    assert "sgo_materiel_masterplate" in sql
    assert "SFE27" in sql


def test_history_vehicle_candidate_query_returns_distinct_local_item_ids():
    result = SimpleNamespace(all=lambda: [(101,), (102,)])
    session = _ExecuteSession(result)

    item_ids = asyncio.run(
        ContextualSearchRepository.list_history_item_ids_by_vehicle(
            session,
            " sfe27 ",
        )
    )

    sql = str(
        session.statements[0].compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert item_ids == [101, 102]
    assert "item_inquiry_history" in sql
    assert (
        "upper(coalesce(nullif(trim(item_inquiry_history.vehicle_batch), ''), "
        "trim(item_inquiry_history.vehicle))) = 'SFE27'"
    ) in sql
    assert "item_inquiry_history.item_id IS NOT NULL" in sql
    assert "DISTINCT" in sql


def test_agent_history_queries_exclude_current_and_future_inquiries():
    cutoff = datetime(2026, 3, 5, 10, 30, 26)
    result = SimpleNamespace(all=lambda: [])
    result.scalars = lambda: result
    session = _ExecuteSession(result)

    asyncio.run(
        ContextualSearchRepository.list_history_item_ids_by_vehicle(
            session,
            "SFE28",
            exclude_inquiry_id="current-inquiry",
            before_inquiry_time=cutoff,
        )
    )
    asyncio.run(
        ContextualSearchRepository.list_histories_by_item_ids(
            session,
            [101],
            exclude_inquiry_id="current-inquiry",
            before_inquiry_time=cutoff,
        )
    )

    for statement in session.statements:
        sql = str(
            statement.compile(
                dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert "item_inquiry_history.inquiry_id != 'current-inquiry'" in sql
        assert "item_inquiry_history.inquiry_time < '2026-03-05 10:30:26'" in sql


def test_item_name_candidate_query_uses_normalized_exact_match():
    result = SimpleNamespace(all=lambda: [(101,), (102,)])
    session = _ExecuteSession(result)

    item_ids = asyncio.run(
        ContextualSearchRepository.list_item_ids_by_exact_name(
            session,
            " 便器冲洗按钮 ",
        )
    )

    sql = str(
        session.statements[0].compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert item_ids == [101, 102]
    assert "lower(trim(item_info.item_name)) = '便器冲洗按钮'" in sql


def test_history_window_update_uses_pending_state_and_revision_compare_and_swap():
    session = _ExecuteSession(SimpleNamespace(rowcount=1))
    snapshot = SearchSnapshot(
        query_images=["old.jpg"],
        parameters=SearchParameters(search_mode="siglip"),
        results=SearchResults(items=[]),
        searched_at=datetime(2026, 8, 18, 10, 11, 1),
    )

    updated = asyncio.run(
        ContextualSearchRepository.update_history_window(
            session,
            history_id=101,
            expected_revision=3,
            previous_snapshot=snapshot,
            query_images=["new.jpg"],
            parameters=SearchParameters(
                vehicle_batch="SFE27",
                item_description="卫生间墙面上的冲洗按钮",
            ),
            results=SearchResults(items=[]),
            top_item=None,
        )
    )

    statement = session.statements[0]
    where_sql = str(
        statement.whereclause.compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert updated is True
    assert "search_history.id = 101" in where_sql
    assert "search_history.verify_status = 'pending'" in where_sql
    assert "search_history.search_revision = 3" in where_sql
    assert statement._values[SearchHistory.__table__.columns.search_revision].value == 4
    assert (
        statement._values[SearchHistory.__table__.columns.query_text].value
        == "卫生间墙面上的冲洗按钮"
    )
