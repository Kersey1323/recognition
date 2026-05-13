import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys


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


def test_submit_feedback_correct_updates_history_without_creating_ticket():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    now = datetime(2026, 4, 29, 9, 0, 0)
    history = SimpleNamespace(
        id=1001,
        correct_source=None,
        search_results=parts_module.SearchResults(
            items=[
                {
                    "item_id": "1950361513125318656",
                    "item_code": "40000728845",
                    "item_name": "制动2",
                    "similar": 0.95,
                    "image_url": "bfr-ai-files/top1.jpg",
                }
            ]
        ),
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=history)), \
         patch.object(parts_module.SearchHistory, "update_feedback", AsyncMock()) as update_mock, \
         patch.object(parts_module.SearchReviewTicket, "get_active_by_history_id", AsyncMock(return_value=None)), \
         patch.object(parts_module.SearchReviewTicket, "create_ticket", AsyncMock()) as create_ticket_mock, \
         patch.object(parts_module, "datetime", SimpleNamespace(now=MagicMock(return_value=now))):
        res = asyncio.run(
            RailwayPartsManager.submit_v2_search_feedback(
                history_id=1001,
                feedback_result="correct",
                remark="用户确认正确",
                selected_item_id=None,
            )
        )

    assert update_mock.await_args.kwargs["verify_status"] == "correct"
    assert update_mock.await_args.kwargs["verify_remark"] == "用户确认正确"
    assert update_mock.await_args.kwargs["verified_at"] == now
    assert update_mock.await_args.kwargs["ranking_feedback_type"] == "top1_correct"
    assert update_mock.await_args.kwargs["selected_item_id"] == 1950361513125318656
    assert update_mock.await_args.kwargs["selected_item_code"] == "40000728845"
    assert update_mock.await_args.kwargs["correct_item_id"] == 1950361513125318656
    assert update_mock.await_args.kwargs["correct_item_code"] == "40000728845"
    assert update_mock.await_args.kwargs["correct_item_name"] == "制动2"
    assert update_mock.await_args.kwargs["correct_image_url"] == "bfr-ai-files/top1.jpg"
    assert update_mock.await_args.kwargs["correct_rank"] == 1
    assert update_mock.await_args.kwargs["correct_source"] == "user_selected"
    create_ticket_mock.assert_not_awaited()
    assert res.history_id == "1001"
    assert res.verify_status == "correct"
    assert res.ranking_feedback_type == "top1_correct"
    assert res.correct_item_id == "1950361513125318656"
    assert res.correct_rank == 1
    assert res.correct_source == "user_selected"
    assert res.ticket_id is None
    assert res.ticket_created is False
    session.commit.assert_awaited()


def test_submit_feedback_wrong_creates_ticket_when_no_active_ticket():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    now = datetime(2026, 4, 29, 9, 10, 0)
    history = SimpleNamespace(
        id=1002,
        correct_source="user_selected",
        search_results=parts_module.SearchResults(items=[]),
    )
    new_ticket = SimpleNamespace(id=3001)

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=history)), \
         patch.object(parts_module.SearchHistory, "update_feedback", AsyncMock()) as update_mock, \
         patch.object(parts_module.SearchReviewTicket, "get_active_by_history_id", AsyncMock(return_value=None)), \
         patch.object(parts_module.SearchReviewTicket, "create_ticket", AsyncMock(return_value=new_ticket)) as create_ticket_mock, \
         patch.object(parts_module, "datetime", SimpleNamespace(now=MagicMock(return_value=now))), \
         patch.object(parts_module, "get_id", return_value=3001):
        res = asyncio.run(
            RailwayPartsManager.submit_v2_search_feedback(
                history_id=1002,
                feedback_result="wrong",
                remark="识别错误",
                selected_item_id=None,
            )
        )

    assert update_mock.await_args.kwargs["verify_status"] == "wrong"
    assert update_mock.await_args.kwargs["ranking_feedback_type"] == "no_correct_match"
    assert update_mock.await_args.kwargs["selected_item_id"] is None
    assert update_mock.await_args.kwargs["correct_item_id"] is None
    assert update_mock.await_args.kwargs["correct_item_code"] is None
    assert update_mock.await_args.kwargs["correct_source"] == "none"
    create_ticket_mock.assert_awaited_once()
    assert res.ticket_id == "3001"
    assert res.ticket_created is True
    session.commit.assert_awaited()


def test_submit_feedback_wrong_reuses_active_ticket():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    now = datetime(2026, 4, 29, 9, 20, 0)
    history = SimpleNamespace(
        id=1003,
        correct_item_id=9,
        correct_item_code="X9",
        correct_item_name="技术部确认结果",
        correct_image_url="bfr-ai-files/review.jpg",
        correct_rank=None,
        correct_source="review_resolved",
        search_results=parts_module.SearchResults(items=[]),
    )
    active_ticket = SimpleNamespace(id=3555)

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=history)), \
         patch.object(parts_module.SearchHistory, "update_feedback", AsyncMock()) as update_mock, \
         patch.object(parts_module.SearchReviewTicket, "get_active_by_history_id", AsyncMock(return_value=active_ticket)), \
         patch.object(parts_module.SearchReviewTicket, "create_ticket", AsyncMock()) as create_ticket_mock, \
         patch.object(parts_module, "datetime", SimpleNamespace(now=MagicMock(return_value=now))):
        res = asyncio.run(
            RailwayPartsManager.submit_v2_search_feedback(
                history_id=1003,
                feedback_result="wrong",
                remark="仍有问题",
                selected_item_id=None,
            )
        )

    assert update_mock.await_args.kwargs["verify_status"] == "wrong"
    assert update_mock.await_args.kwargs["ranking_feedback_type"] == "no_correct_match"
    assert update_mock.await_args.kwargs["correct_item_id"] == 9
    assert update_mock.await_args.kwargs["correct_item_code"] == "X9"
    assert update_mock.await_args.kwargs["correct_source"] == "review_resolved"
    create_ticket_mock.assert_not_awaited()
    assert res.ticket_id == "3555"
    assert res.ticket_created is False
    session.commit.assert_awaited()


def test_submit_feedback_correct_ranked_selection_closes_active_review_ticket():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    now = datetime(2026, 4, 30, 18, 10, 0)
    history = SimpleNamespace(
        id=1002,
        correct_source=None,
        search_results=parts_module.SearchResults(
            items=[
                {
                    "item_id": "1",
                    "item_code": "A",
                    "item_name": "错误候选",
                    "similar": 0.95,
                    "image_url": "bfr-ai-files/top1.jpg",
                },
                {
                    "item_id": "2",
                    "item_code": "B",
                    "item_name": "正确候选",
                    "similar": 0.94,
                    "image_url": "bfr-ai-files/top2.jpg",
                },
            ]
        ),
    )
    active_ticket = SimpleNamespace(
        id=3001,
        review_status="open",
        issue_type="precision_issue",
        resolution_remark=None,
        review_remark="用户先前反馈错误",
        review_started_at=None,
        resolved_at=None,
        closed_at=None,
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=history)), \
         patch.object(parts_module.SearchHistory, "update_feedback", AsyncMock()) as update_mock, \
         patch.object(parts_module.SearchReviewTicket, "get_active_by_history_id", AsyncMock(return_value=active_ticket)), \
         patch.object(parts_module.SearchReviewTicket, "update_ticket", AsyncMock()) as update_ticket_mock, \
         patch.object(parts_module, "datetime", SimpleNamespace(now=MagicMock(return_value=now))):
        res = asyncio.run(
            RailwayPartsManager.submit_v2_search_feedback(
                history_id=1002,
                feedback_result="correct",
                remark="第二名才是正确结果",
                selected_item_id="2",
            )
        )

    assert update_mock.await_args.kwargs["ranking_feedback_type"] == "topk_correct"
    assert update_mock.await_args.kwargs["selected_item_id"] == 2
    assert update_mock.await_args.kwargs["selected_item_code"] == "B"
    assert update_mock.await_args.kwargs["selected_item_name"] == "正确候选"
    assert update_mock.await_args.kwargs["selected_rank"] == 2
    assert update_mock.await_args.kwargs["selected_image_url"] == "bfr-ai-files/top2.jpg"
    assert update_mock.await_args.kwargs["correct_item_id"] == 2
    assert update_mock.await_args.kwargs["correct_item_code"] == "B"
    assert update_mock.await_args.kwargs["correct_item_name"] == "正确候选"
    assert update_mock.await_args.kwargs["correct_image_url"] == "bfr-ai-files/top2.jpg"
    assert update_mock.await_args.kwargs["correct_rank"] == 2
    assert update_mock.await_args.kwargs["correct_source"] == "user_selected"
    assert update_ticket_mock.await_args.kwargs["review_status"] == "closed"
    assert update_ticket_mock.await_args.kwargs["resolution_remark"] == "用户反馈改为正确，自动关闭核验单"
    assert update_ticket_mock.await_args.kwargs["resolved_at"] == now
    assert update_ticket_mock.await_args.kwargs["closed_at"] == now
    assert res.correct_item_id == "2"
    assert res.correct_rank == 2
    assert res.correct_source == "user_selected"
    assert res.ticket_id is None


def test_submit_feedback_correct_preserves_existing_ticket_resolution_fields():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    feedback_at = datetime(2026, 4, 30, 19, 0, 0)
    resolved_at = datetime(2026, 4, 30, 18, 30, 0)
    history = SimpleNamespace(
        id=1005,
        correct_source=None,
        search_results=parts_module.SearchResults(
            items=[
                {
                    "item_id": "9",
                    "item_code": "C",
                    "item_name": "正确候选",
                    "similar": 0.93,
                    "image_url": "bfr-ai-files/top1.jpg",
                }
            ]
        ),
    )
    active_ticket = SimpleNamespace(
        id=3999,
        review_status="reviewing",
        issue_type="precision_issue",
        resolution_remark="技术部已确认原因",
        review_remark="处理中",
        review_started_at=datetime(2026, 4, 30, 18, 0, 0),
        resolved_at=resolved_at,
        closed_at=None,
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SearchHistory, "get_history_by_id", AsyncMock(return_value=history)), \
         patch.object(parts_module.SearchHistory, "update_feedback", AsyncMock()), \
         patch.object(parts_module.SearchReviewTicket, "get_active_by_history_id", AsyncMock(return_value=active_ticket)), \
         patch.object(parts_module.SearchReviewTicket, "update_ticket", AsyncMock()) as update_ticket_mock, \
         patch.object(parts_module, "datetime", SimpleNamespace(now=MagicMock(return_value=feedback_at))):
        asyncio.run(
            RailwayPartsManager.submit_v2_search_feedback(
                history_id=1005,
                feedback_result="correct",
                remark="用户更正为正确",
                selected_item_id=None,
            )
        )

    assert update_ticket_mock.await_args.kwargs["review_status"] == "closed"
    assert update_ticket_mock.await_args.kwargs["resolution_remark"] == "技术部已确认原因"
    assert update_ticket_mock.await_args.kwargs["resolved_at"] == resolved_at
    assert update_ticket_mock.await_args.kwargs["closed_at"] == feedback_at


def test_submit_feedback_rejects_unknown_feedback_result():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    try:
        asyncio.run(
            RailwayPartsManager.submit_v2_search_feedback(
                history_id=1004,
                feedback_result="foo",
                remark="非法状态",
                selected_item_id=None,
            )
        )
    except Exception as exc:
        assert "feedback_result" in str(exc)
    else:
        raise AssertionError("expected submit_v2_search_feedback to reject unknown feedback_result")
