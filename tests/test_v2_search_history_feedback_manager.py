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
    history = SimpleNamespace(id=1001)

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
            )
        )

    assert update_mock.await_args.kwargs["verify_status"] == "correct"
    assert update_mock.await_args.kwargs["verify_remark"] == "用户确认正确"
    assert update_mock.await_args.kwargs["verified_at"] == now
    create_ticket_mock.assert_not_awaited()
    assert res.history_id == "1001"
    assert res.verify_status == "correct"
    assert res.ticket_id is None
    assert res.ticket_created is False
    session.commit.assert_awaited()


def test_submit_feedback_wrong_creates_ticket_when_no_active_ticket():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    now = datetime(2026, 4, 29, 9, 10, 0)
    history = SimpleNamespace(id=1002)
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
            )
        )

    assert update_mock.await_args.kwargs["verify_status"] == "wrong"
    create_ticket_mock.assert_awaited_once()
    assert res.ticket_id == "3001"
    assert res.ticket_created is True
    session.commit.assert_awaited()


def test_submit_feedback_wrong_reuses_active_ticket():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    now = datetime(2026, 4, 29, 9, 20, 0)
    history = SimpleNamespace(id=1003)
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
            )
        )

    assert update_mock.await_args.kwargs["verify_status"] == "wrong"
    create_ticket_mock.assert_not_awaited()
    assert res.ticket_id == "3555"
    assert res.ticket_created is False
    session.commit.assert_awaited()


def test_submit_feedback_rejects_unknown_feedback_result():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    try:
        asyncio.run(
            RailwayPartsManager.submit_v2_search_feedback(
                history_id=1004,
                feedback_result="foo",
                remark="非法状态",
            )
        )
    except Exception as exc:
        assert "feedback_result" in str(exc)
    else:
        raise AssertionError("expected submit_v2_search_feedback to reject unknown feedback_result")
