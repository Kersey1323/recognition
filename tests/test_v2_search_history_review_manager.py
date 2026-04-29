import asyncio
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from csrcqsf.models.item import Items
from csrcqsf.models.search_history import SearchHistory, SearchResults, SearchReviewTicket


def test_search_history_list_helper_applies_search_equipment_filter():
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))

    with patch("csrcqsf.models.search_history.async_get_count", AsyncMock(return_value=0)):
        asyncio.run(
            SearchHistory.list_search_history(
                session=session,
                page=1,
                per_page=10,
                search_type="image",
                search_equipment="terminal",
                keyword="19010036737",
                status="pending",
                date_from="2026-04-27",
                date_to="2026-04-28",
            )
        )

    stmt = session.scalars.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "query_image" in sql
    assert "query_text" in sql
    assert "search_equipment = 'terminal'" in sql
    assert "verify_status" in sql


def test_search_history_list_helper_treats_partial_as_wrong_filter():
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))

    with patch("csrcqsf.models.search_history.async_get_count", AsyncMock(return_value=0)):
        asyncio.run(
            SearchHistory.list_search_history(
                session=session,
                page=1,
                per_page=10,
                status="wrong",
            )
        )

    stmt = session.scalars.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "verify_status = 'wrong'" in sql
    assert "verify_status = 'partial'" in sql


def test_search_history_detail_summary_and_verify_helpers_exist():
    assert hasattr(SearchHistory, "get_history_by_id")
    assert hasattr(SearchHistory, "summarize_review_status")
    assert hasattr(SearchHistory, "update_review_result")


def test_search_review_ticket_helpers_exist():
    assert hasattr(SearchReviewTicket, "get_active_by_history_id")
    assert hasattr(SearchReviewTicket, "create_ticket")
    assert hasattr(SearchReviewTicket, "get_by_id")
    assert hasattr(SearchReviewTicket, "list_tickets")
    assert hasattr(SearchReviewTicket, "summarize_tickets")


def test_search_review_ticket_summarize_uses_required_status_and_issue_types():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())

    asyncio.run(SearchReviewTicket.summarize_tickets(session))

    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "reviewing" in sql
    assert "missing_index" in sql
    assert "precision_issue" in sql
    assert "system_bug" in sql
    assert "processing" not in sql
    assert "issue_type_count" not in sql


def test_items_suggest_helper_exists():
    assert hasattr(Items, "suggest_items")


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

    _import_railway_parts_manager._cached = (parts_module.RailwayPartsManager, parts_module)
    return _import_railway_parts_manager._cached


def test_list_v2_search_history_passes_search_equipment_filter_and_latest_ticket_fields():
    from csrcqsf.biz.railwayparts.api_models import SearchHistoryListReq

    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    page_result = SimpleNamespace(
        total=1,
        data=[
            SimpleNamespace(
                id=1,
                query_text="钢丝绳",
                query_image=None,
                verify_status=None,
                time_created=datetime(2026, 4, 28, 10, 0, 0),
                search_results=SearchResults(items=[]),
                inquery_id=None,
                inquery_num=None,
                search_result_item_name="钢丝绳",
                search_result_item_code="19010036737",
                correct_item_name=None,
                correct_item_code=None,
            )
        ],
    )
    latest_ticket = SimpleNamespace(
        id=3001,
        history_id=1,
        review_status="open",
        issue_type="precision_issue",
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchHistory, "list_search_history", AsyncMock(return_value=page_result)) as list_mock, \
         patch.object(parts_module.SearchReviewTicket, "list_latest_by_history_ids", AsyncMock(return_value={1: latest_ticket})):
        res = asyncio.run(
            RailwayPartsManager.list_v2_search_history(
                SearchHistoryListReq(
                    page=1,
                    pageSize=10,
                    search_type="text",
                    search_equipment="terminal",
                    keyword="钢丝绳",
                    status="pending",
                    date_from="2026-04-27",
                    date_to="2026-04-28",
                )
            )
        )

    assert list_mock.await_args.kwargs["search_type"] == "text"
    assert list_mock.await_args.kwargs["search_equipment"] == "terminal"
    assert list_mock.await_args.kwargs["keyword"] == "钢丝绳"
    assert res.items[0].status == "pending"
    assert res.items[0].has_open_review_ticket is True
    assert res.items[0].latest_ticket_id == "3001"
    assert res.items[0].latest_review_status == "open"
    assert res.items[0].latest_issue_type == "precision_issue"


def test_list_v2_search_history_maps_partial_status_to_wrong():
    from csrcqsf.biz.railwayparts.api_models import SearchHistoryListReq

    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    page_result = SimpleNamespace(
        total=1,
        data=[
            SimpleNamespace(
                id=1,
                query_text="钢丝绳",
                query_image=None,
                verify_status="partial",
                time_created=datetime(2026, 4, 28, 10, 0, 0),
                search_results=SearchResults(items=[]),
                inquery_id=None,
                inquery_num=None,
                search_result_item_name="钢丝绳",
                search_result_item_code="19010036737",
                correct_item_name=None,
                correct_item_code=None,
            )
        ],
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchHistory, "list_search_history", AsyncMock(return_value=page_result)), \
         patch.object(parts_module.SearchReviewTicket, "list_latest_by_history_ids", AsyncMock(return_value={})):
        res = asyncio.run(
            RailwayPartsManager.list_v2_search_history(SearchHistoryListReq(page=1, pageSize=10))
        )

    assert res.items[0].status == "wrong"


def test_get_v2_search_history_detail_returns_full_record():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    fake_history = SimpleNamespace(
        id=1,
        query_text="钢丝绳",
        query_image=None,
        verify_status="correct",
        verify_remark="人工确认",
        verified_at=datetime(2026, 4, 28, 11, 0, 0),
        time_created=datetime(2026, 4, 28, 10, 0, 0),
        search_results=SearchResults(
            items=[
                {
                    "item_id": "101",
                    "item_code": "19010036737",
                    "similar": 0.91,
                    "image_url": "bfr-ai-files/demo.jpg",
                }
            ]
        ),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="钢丝绳",
        search_result_item_code="19010036737",
        correct_item_name="钢丝绳",
        correct_item_code="19010036737",
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=fake_history)), \
         patch.object(parts_module.SearchReviewTicket, "list_latest_by_history_ids", AsyncMock(return_value={})):
        detail = asyncio.run(RailwayPartsManager.get_v2_search_history_detail(1))

    assert detail.history_id == "1"
    assert detail.status == "correct"
    assert detail.verify_remark == "人工确认"
    assert detail.result.items[0].image_url == "bfr-ai-files/demo.jpg"


def test_summary_v2_search_history_uses_open_ticket_count_instead_of_partial():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    fake_result = MagicMock()
    fake_result.one.return_value = (10, 4, 3, 2)

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchHistory, "summarize_review_status", AsyncMock(return_value=fake_result)), \
         patch.object(parts_module.SearchReviewTicket, "count_open_tickets", AsyncMock(return_value=2)):
        summary = asyncio.run(RailwayPartsManager.summary_v2_search_history())

    assert summary.total == 10
    assert summary.pending_count == 4
    assert summary.open_ticket_count == 2


def test_verify_v2_search_history_autofills_correct_item_when_status_is_correct():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_history = SimpleNamespace(
        id=1,
        search_result_item_code="19010036737",
        search_result_item_name="钢丝绳",
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=fake_history)), \
         patch.object(parts_module.SearchHistory, "update_review_result", AsyncMock()) as update_mock:
        res = asyncio.run(
            RailwayPartsManager.verify_v2_search_history(
                history_id=1,
                verify_status="correct",
                correct_item_code=None,
                remark="人工确认正确",
            )
        )

    assert update_mock.await_args.kwargs["correct_item_code"] == "19010036737"
    assert update_mock.await_args.kwargs["correct_item_name"] == "钢丝绳"
    assert res.status == "correct"


def test_verify_v2_search_history_uses_lookup_item_for_partial():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_history = SimpleNamespace(
        id=1,
        search_result_item_code="19010036737",
        search_result_item_name="钢丝绳",
    )
    fake_item = SimpleNamespace(id=2, item_code="19010030048", item_name="穿墙体接头")

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=fake_history)), \
         patch.object(parts_module.Items, "get_item_by_item_code", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SearchHistory, "update_review_result", AsyncMock()) as update_mock:
        res = asyncio.run(
            RailwayPartsManager.verify_v2_search_history(
                history_id=1,
                verify_status="partial",
                correct_item_code="19010030048",
                remark="部分正确",
            )
        )

    assert update_mock.await_args.kwargs["correct_item_name"] == "穿墙体接头"
    assert res.correct_item_code == "19010030048"


def test_suggest_items_returns_lightweight_candidates():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    fake_items = [
        SimpleNamespace(id=1, item_code="19010036737", item_name="钢丝绳"),
        SimpleNamespace(id=2, item_code="19010030048", item_name="穿墙体接头"),
    ]

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.Items, "suggest_items", AsyncMock(return_value=fake_items)):
        res = asyncio.run(RailwayPartsManager.suggest_items("1901", limit=5))

    assert res.items[0].item_code == "19010036737"
    assert res.items[1].item_name == "穿墙体接头"


def test_delete_v2_search_history_deletes_records_and_best_effort_query_images():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    deleted_rows = [
        (1, "bfr-search-history-files/query-images/20260428/1_demo.png"),
        (2, None),
    ]

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchHistory, "delete_history_with_query_images", AsyncMock(return_value=deleted_rows)), \
         patch.object(parts_module, "parse_minio_path", return_value=("bfr-search-history-files", "query-images/20260428/1_demo.png")), \
         patch.object(parts_module.minio_instance.client, "remove_object", MagicMock()) as remove_mock:
        res = asyncio.run(RailwayPartsManager.delete_v2_search_history([1, 2]))

    remove_mock.assert_called_once_with(
        "bfr-search-history-files",
        "query-images/20260428/1_demo.png",
    )
    assert res.deleted_count == 2
