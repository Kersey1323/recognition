import asyncio
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from csrcqsf.models.search_history import SearchResults


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


def test_list_review_tickets_maps_joined_history_snapshot():
    from csrcqsf.biz.railwayparts.api_models import SearchReviewTicketListReq

    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    page_result = SimpleNamespace(
        total=1,
        data=[
            SimpleNamespace(
                id=7001,
                history_id=101,
                review_status="open",
                issue_type=None,
                time_created=datetime(2026, 4, 29, 10, 0, 0),
                time_updated=datetime(2026, 4, 29, 10, 5, 0),
                query_text="钢丝绳",
                query_image=None,
                search_equipment="terminal",
                search_result_item_name="钢丝绳",
                search_result_item_code="19010036737",
                verify_remark="识别错误",
                correct_item_name=None,
                correct_item_code=None,
            )
        ],
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchReviewTicket, "list_tickets", AsyncMock(return_value=page_result)):
        res = asyncio.run(
            RailwayPartsManager.list_v2_search_review_tickets(
                SearchReviewTicketListReq(
                    page=1,
                    pageSize=10,
                    review_status="open",
                    issue_type="all",
                    search_equipment="terminal",
                    keyword="钢丝绳",
                    date_from="2026-04-27",
                    date_to="2026-04-29",
                )
            )
        )

    assert res.total == 1
    assert res.items[0].ticket_id == "7001"
    assert res.items[0].history_id == "101"
    assert res.items[0].issue_type is None
    assert res.items[0].search_equipment == "terminal"
    assert res.items[0].query_text == "钢丝绳"
    assert res.items[0].feedback_remark == "识别错误"
    assert res.items[0].search_item_code == "19010036737"


def test_get_review_ticket_detail_returns_history_snapshot():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    ticket = SimpleNamespace(
        id=7002,
        history_id=102,
        review_status="reviewing",
        issue_type="system_bug",
        time_created=datetime(2026, 4, 29, 10, 5, 0),
        time_updated=datetime(2026, 4, 29, 10, 20, 0),
        review_remark="已接单",
        resolution_remark=None,
        review_started_at=datetime(2026, 4, 29, 10, 10, 0),
        resolved_at=None,
        closed_at=None,
    )
    history = SimpleNamespace(
        id=102,
        query_text="制动阀",
        query_image=None,
        search_equipment="web",
        search_results=SearchResults(
            items=[
                {
                    "item_id": "1950361513125318656",
                    "item_code": "40000728845",
                    "item_name": "制动2",
                    "similar": 0.9584,
                    "image_url": "bfr-ai-files/b.jpg",
                    "matched_images": [
                        {"image_url": "bfr-ai-files/b.jpg", "rate": 0.9584},
                        {"image_url": "bfr-ai-files/a.jpg", "rate": 0.95},
                    ],
                }
            ]
        ),
        search_result_item_name="制动2",
        search_result_item_code="40000728845",
        verify_remark="结果不准",
        correct_item_name=None,
        correct_item_code=None,
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchReviewTicket, "get_by_id", AsyncMock(return_value=ticket)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=history)):
        detail = asyncio.run(RailwayPartsManager.get_v2_search_review_ticket_detail(7002))

    assert detail.ticket_id == "7002"
    assert detail.history_id == "102"
    assert detail.review_status == "reviewing"
    assert detail.issue_type == "system_bug"
    assert detail.time_created == "2026-04-29 10:05:00"
    assert detail.time_updated == "2026-04-29 10:20:00"
    assert detail.search_equipment == "web"
    assert detail.query_text == "制动阀"
    assert detail.feedback_remark == "结果不准"
    assert detail.result.items[0].item_code == "40000728845"
    assert len(detail.result.items[0].matched_images) == 2
    assert detail.result.items[0].matched_images[0].image_url == "bfr-ai-files/b.jpg"


def test_update_review_ticket_marks_resolved_and_backfills_correct_item():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    now = datetime(2026, 4, 29, 10, 30, 0)
    ticket = SimpleNamespace(
        id=7003,
        history_id=103,
        review_status="open",
        issue_type="precision_issue",
        review_remark=None,
        resolution_remark=None,
        review_started_at=None,
        resolved_at=None,
        closed_at=None,
    )
    history = SimpleNamespace(
        id=103,
        search_result_item_code="19010036737",
    )
    item = SimpleNamespace(item_code="19010036737", item_name="钢丝绳")

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchReviewTicket, "get_by_id", AsyncMock(return_value=ticket)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=history)), \
         patch.object(parts_module.Items, "get_item_by_item_code", AsyncMock(return_value=item)), \
         patch.object(parts_module.SearchHistory, "update_review_result", AsyncMock()) as history_update_mock, \
         patch.object(parts_module.SearchReviewTicket, "update_ticket", AsyncMock()) as ticket_update_mock, \
         patch.object(parts_module, "datetime", SimpleNamespace(now=MagicMock(return_value=now))):
        res = asyncio.run(
            RailwayPartsManager.update_v2_search_review_ticket(
                ticket_id=7003,
                review_status="resolved",
                issue_type="precision_issue",
                review_remark="核验完成",
                resolution_remark="已回填正确结果",
                correct_item_code="19010036737",
            )
        )

    history_update_mock.assert_awaited_once()
    assert history_update_mock.await_args.kwargs["verify_status"] == "wrong"
    ticket_update_mock.assert_awaited_once()
    assert res.ticket_id == "7003"
    assert res.review_status == "resolved"
    assert res.correct_item_code == "19010036737"
    assert res.correct_item_name == "钢丝绳"
    session.commit.assert_awaited()


def test_update_review_ticket_rejects_open_status():
    RailwayPartsManager, _ = _import_railway_parts_manager()

    try:
        asyncio.run(
            RailwayPartsManager.update_v2_search_review_ticket(
                ticket_id=7004,
                review_status="open",
                issue_type=None,
                review_remark=None,
                resolution_remark=None,
                correct_item_code=None,
            )
        )
    except Exception as exc:
        assert "review_status" in str(exc)
    else:
        raise AssertionError("expected update_v2_search_review_ticket to reject open status")


def test_update_review_ticket_reviewing_clears_resolved_and_closed_timestamps():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    now = datetime(2026, 4, 29, 10, 40, 0)
    ticket = SimpleNamespace(
        id=7005,
        history_id=105,
        review_status="closed",
        issue_type="system_bug",
        review_remark="已关闭",
        resolution_remark="历史问题",
        review_started_at=datetime(2026, 4, 29, 10, 0, 0),
        resolved_at=datetime(2026, 4, 29, 10, 20, 0),
        closed_at=datetime(2026, 4, 29, 10, 30, 0),
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchReviewTicket, "get_by_id", AsyncMock(return_value=ticket)), \
         patch.object(parts_module.SearchReviewTicket, "update_ticket", AsyncMock()) as ticket_update_mock, \
         patch.object(parts_module, "datetime", SimpleNamespace(now=MagicMock(return_value=now))):
        res = asyncio.run(
            RailwayPartsManager.update_v2_search_review_ticket(
                ticket_id=7005,
                review_status="reviewing",
                issue_type="system_bug",
                review_remark="重新核验",
                resolution_remark=None,
                correct_item_code=None,
            )
        )

    assert ticket_update_mock.await_args.kwargs["resolved_at"] is None
    assert ticket_update_mock.await_args.kwargs["closed_at"] is None
    assert res.review_status == "reviewing"


def test_summary_review_tickets_maps_status_and_issue_type_counts():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    fake_result = MagicMock()
    fake_result.one.return_value = (8, 2, 1, 3, 2, 1, 4, 3)

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchReviewTicket, "summarize_tickets", AsyncMock(return_value=fake_result)) as summarize_mock:
        summary = asyncio.run(RailwayPartsManager.summary_v2_search_review_ticket())

    summarize_mock.assert_awaited_once()
    assert summary.total == 8
    assert summary.open_count == 2
    assert summary.reviewing_count == 1
    assert summary.resolved_count == 3
    assert summary.closed_count == 2
    assert summary.missing_index_count == 1
    assert summary.precision_issue_count == 4
    assert summary.system_bug_count == 3
