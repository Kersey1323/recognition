import asyncio
import io
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys

from PIL import Image

from csrcqsf.models.orm.search_history import SearchHistory


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


def _fake_cv2_module():
    return SimpleNamespace(
        COLOR_BGR2RGB=1,
        IMREAD_COLOR=1,
        INTER_AREA=1,
        cvtColor=lambda image, _code: image,
        imdecode=lambda image, _code: image,
        resize=lambda image, _size, interpolation=None: image,
    )


def _import_railway_parts_manager():
    cached = getattr(_import_railway_parts_manager, "_cached", None)
    if cached is not None:
        return cached

    existing = sys.modules.get("csrcqsf.modules.railway_parts.services.parts_service")
    if existing is not None:
        _import_railway_parts_manager._cached = (
            existing.RailwayPartsManager,
            existing,
        )
        return _import_railway_parts_manager._cached

    preserved_modules = {}
    with patch.dict(
        sys.modules,
        {
            "csrcqsf.infra.vector_store.milvus": SimpleNamespace(milvus_client=MagicMock()),
            "csrcqsf.infra.db.mdp_db": SimpleNamespace(sgo_sessionLocal=MagicMock()),
            "csrcqsf.modules.railway_parts.integrations.milvus_state_manager": _fake_v1_milvus_module(),
            "cv2": _fake_cv2_module(),
        },
    ):
        import csrcqsf.modules.railway_parts.services.parts_service as parts_module
        preserved_modules = {
            "csrcqsf.modules.railway_parts.services.parts_service": parts_module,
            "csrcqsf.models.orm.item": sys.modules.get("csrcqsf.models.orm.item"),
            "csrcqsf.models.orm.sgo": sys.modules.get("csrcqsf.models.orm.sgo"),
            "csrcqsf.models.orm.search_history": sys.modules.get("csrcqsf.models.orm.search_history"),
        }

    for module_name, module in preserved_modules.items():
        if module is not None:
            sys.modules[module_name] = module

    _import_railway_parts_manager._cached = (
        parts_module.RailwayPartsManager,
        parts_module,
    )
    return _import_railway_parts_manager._cached


def _make_upload_bytes():
    image = Image.new("RGB", (4, 4), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_search_v2_by_text_persists_query_text_after_success():
    session = AsyncMock()

    def _add(obj):
        session.added = obj

    session.add = MagicMock(side_effect=_add)

    fake_hits = [
        {
            "entity": {
                "item_id": 1,
                "description": "转向架上的制动圆盘",
                "inquiry_id": "inq-1",
            },
            "distance": 0.98,
        },
        {
            "entity": {
                "item_id": 2,
                "description": "司机室操作制动的控制部件",
                "inquiry_id": "inq-2",
            },
            "distance": 0.91,
        },
    ]
    fake_items = {
        1: SimpleNamespace(id=1, item_code="40000728845", item_name="制动2"),
        2: SimpleNamespace(id=2, item_code="19010025620", item_name="制动控制器"),
    }

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    semantic_service = SimpleNamespace(search=AsyncMock(return_value=fake_hits))
    with patch.object(
        parts_module.parts_search_service.search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ), patch.object(parts_module, "get_id", return_value=2048696242753638400), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(
             parts_module.ContextualSearchRepository,
             "list_items_by_ids",
             AsyncMock(return_value=list(fake_items.values())),
         ), patch.object(
             parts_module.ContextualSearchRepository,
             "list_first_images_by_item_ids",
             AsyncMock(
                 return_value=[
                     SimpleNamespace(item_id=1, image_url="bfr-ai-files/b.jpg"),
                     SimpleNamespace(item_id=2, image_url="bfr-ai-files/c.jpg"),
                 ]
             ),
         ):
        result = asyncio.run(RailwayPartsManager.search_v2_by_text("制动盘", top_k=10))

    assert result.history_id == "2048696242753638400"
    assert len(result.data) == 2
    assert result.data[0].item_id == "1"
    assert result.data[0].item_code == "40000728845"
    assert result.data[0].image_url == "bfr-ai-files/b.jpg"
    assert result.data[0].rate == 0.98
    assert result.data[0].matched_images == []
    assert result.data[0].matched_description == "转向架上的制动圆盘"
    assert isinstance(session.added, SearchHistory)
    assert session.added.search_result_item_code == "40000728845"
    assert session.added.query_text == "制动盘"
    assert session.added.query_image is None
    assert session.added.search_parameter is None
    assert session.added.search_results.items[0].item_id == "1"
    assert session.added.search_results.items[0].item_name == "制动2"
    assert session.added.search_results.items[0].image_url == "bfr-ai-files/b.jpg"
    assert session.added.search_results.items[0].matched_images == []
    assert session.added.search_results.items[0].matched_inquiry_id == "inq-1"
    assert len(session.added.search_results.items) == 2
    session.commit.assert_awaited()


def test_importing_railway_parts_manager_does_not_eager_import_v2_milvus_manager():
    sys.modules.pop("csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager", None)
    _import_railway_parts_manager()

    assert "csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager" not in sys.modules


def test_search_v2_by_text_persists_search_equipment_and_pending_feedback():
    session = AsyncMock()

    def _add(obj):
        session.added = obj

    session.add = MagicMock(side_effect=_add)
    fake_hit = {
        "entity": {
            "item_id": 1935558010375340032,
            "description": "固定盖板的六角螺栓",
            "inquiry_id": "inq-bolt",
        },
        "distance": 0.98,
    }
    fake_item = SimpleNamespace(
        id=1935558010375340032,
        item_code="11010150131",
        item_name="螺栓M8X22",
    )

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    semantic_service = SimpleNamespace(search=AsyncMock(return_value=[fake_hit]))
    with patch.object(
        parts_module.parts_search_service.search_service,
        "get_inquiry_semantic_index_service",
        return_value=semantic_service,
    ), patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(
             parts_module.ContextualSearchRepository,
             "list_items_by_ids",
             AsyncMock(return_value=[fake_item]),
         ), patch.object(
             parts_module.ContextualSearchRepository,
             "list_first_images_by_item_ids",
             AsyncMock(
                 return_value=[
                     SimpleNamespace(
                         item_id=1935558010375340032,
                         image_url="bfr-ai-files/bolt.jpg",
                     )
                 ]
             ),
         ):
        asyncio.run(RailwayPartsManager.search_v2_by_text("螺栓", top_k=5, search_equipment="web"))

    assert isinstance(session.added, SearchHistory)
    assert session.added.search_equipment == "web"
    assert session.added.verify_status == "pending"
    assert session.added.search_results.items[0].matched_description == "固定盖板的六角螺栓"


def test_search_v2_by_image_uploads_query_image_and_persists_path():
    session = AsyncMock()

    def _add(obj):
        session.added = obj

    session.add = MagicMock(side_effect=_add)
    upload_file = SimpleNamespace(
        filename="query image.png",
        read=AsyncMock(return_value=_make_upload_bytes()),
    )
    fake_hits = [
        {
            "entity": {
                "item_id": 1,
                "item_name": "制动2",
                "item_code": "40000728845",
                "image_url": "bfr-ai-files/a.jpg",
            },
            "distance": 0.93,
        },
        {
            "entity": {
                "item_id": 1,
                "item_name": "制动2",
                "item_code": "40000728845",
                "image_url": "bfr-ai-files/b.jpg",
            },
            "distance": 0.97,
        },
        {
            "entity": {
                "item_id": 2,
                "item_name": "制动控制器",
                "item_code": "19010025620",
                "image_url": "bfr-ai-files/c.jpg",
            },
            "distance": 0.90,
        },
    ]

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    with patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "get_id", return_value=2048696242753638400), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(
             RailwayPartsManager,
             "_upload_v2_search_query_image",
             AsyncMock(return_value="bfr-search-history-files/query-images/20260427/1_query_image.png"),
         ):
        manager_cls.return_value.search_by_image = AsyncMock(return_value=fake_hits)
        result = asyncio.run(RailwayPartsManager.search_v2_by_image(upload_file, top_k=10))

    assert result.history_id == "2048696242753638400"
    assert len(result.data) == 2
    assert result.data[0].item_code == "40000728845"
    assert result.data[0].image_url == "bfr-ai-files/b.jpg"
    assert len(result.data[0].matched_images) == 2
    assert session.added.query_text is None
    assert session.added.query_image == "bfr-search-history-files/query-images/20260427/1_query_image.png"
    assert session.added.search_results.items[0].image_url == "bfr-ai-files/b.jpg"
    assert session.added.search_results.items[0].matched_images[1].image_url == "bfr-ai-files/a.jpg"
    session.commit.assert_awaited()


def test_search_v2_by_image_keeps_search_working_when_query_image_upload_fails():
    session = AsyncMock()

    def _add(obj):
        session.added = obj

    session.add = MagicMock(side_effect=_add)
    upload_file = SimpleNamespace(
        filename="broken.png",
        read=AsyncMock(return_value=_make_upload_bytes()),
    )
    fake_hit = {
        "entity": {
            "item_id": 1935558010375340032,
            "item_name": "螺栓M8X22",
            "item_code": "11010150131",
            "image_url": "bfr-ai-files/bolt.jpg",
        },
        "distance": 0.98,
    }

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    with patch.object(parts_module, "MilvusManagerV2") as manager_cls, \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(
             RailwayPartsManager,
             "_upload_v2_search_query_image",
             AsyncMock(side_effect=RuntimeError("boom")),
         ):
        manager_cls.return_value.search_by_image = AsyncMock(return_value=[fake_hit])
        result = asyncio.run(RailwayPartsManager.search_v2_by_image(upload_file, top_k=5))

    assert result.data[0].item_code == "11010150131"
    assert session.added.query_image is None
    session.commit.assert_awaited()


def test_list_v2_search_history_uses_explicit_query_fields_and_unknown_fallback():
    from csrcqsf.modules.railway_parts.schemas.search import SearchHistoryListReq
    from csrcqsf.models.orm.search_history import SearchResults

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    text_history = SimpleNamespace(
        id=1,
        time_created=datetime(2026, 4, 23, 12, 0, 0),
        query_text="螺栓",
        query_image=None,
        search_equipment="web",
        verify_remark="用户确认正确",
        verified_at=datetime(2026, 4, 23, 12, 5, 0),
        search_results=SearchResults(items=[]),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="螺栓M8X22",
        search_result_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
    )
    image_history = SimpleNamespace(
        id=2,
        time_created=datetime(2026, 4, 23, 12, 1, 0),
        query_text=None,
        query_image="bfr-search-history-files/query-images/20260427/2_query.png",
        search_equipment="terminal",
        verify_remark="用户存在疑惑",
        verified_at=datetime(2026, 4, 23, 12, 6, 0),
        search_results=SearchResults(items=[{"item_id": "1", "item_code": "x", "item_name": "螺栓M8X22", "similar": 0.9, "image_url": "bfr-ai-files/1960224080514424832.jpg"}]),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="螺栓M8X22",
        search_result_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
    )
    legacy_history = SimpleNamespace(
        id=3,
        time_created=datetime(2026, 4, 23, 12, 2, 0),
        query_text=None,
        query_image=None,
        search_equipment=None,
        verify_remark=None,
        verified_at=None,
        search_results=SearchResults(items=[]),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name=None,
        search_result_item_code="",
        correct_item_name=None,
        correct_item_code=None,
    )
    page_result = SimpleNamespace(total=3, data=[text_history, image_history, legacy_history])

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchHistory, "list_search_history", AsyncMock(return_value=page_result)), \
         patch.object(parts_module.SearchReviewTicket, "list_latest_by_history_ids", AsyncMock(return_value={})):
        res = asyncio.run(
            RailwayPartsManager.list_v2_search_history(SearchHistoryListReq(page=1, pageSize=10))
        )

    assert res.total == 3
    assert res.items[0].search_type == "text"
    assert res.items[0].query_text == "螺栓"
    assert res.items[0].search_equipment == "web"
    assert res.items[0].feedback_remark == "用户确认正确"
    assert res.items[0].feedback_at == "2026-04-23 12:05:00"
    assert res.items[1].search_type == "image"
    assert res.items[1].query_image.endswith("2_query.png")
    assert res.items[1].search_equipment == "terminal"
    assert res.items[1].feedback_remark == "用户存在疑惑"
    assert res.items[1].feedback_at == "2026-04-23 12:06:00"
    assert res.items[1].result.items[0].item_name == "螺栓M8X22"
    assert res.items[1].result.items[0].image_url == "bfr-ai-files/1960224080514424832.jpg"
    assert res.items[2].search_type == "unknown"
    assert res.items[2].query_text is None
    assert res.items[2].query_image is None


def test_build_search_history_item_prefers_query_images_when_present():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    row = SimpleNamespace(
        id=1,
        time_created=datetime(2026, 5, 9, 10, 0, 0),
        query_text=None,
        query_image=None,
        query_images_json=["q1.jpg", "q2.jpg"],
        search_equipment="web",
        verify_status="pending",
        verify_remark=None,
        verified_at=None,
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="A",
        search_result_item_code="4001",
        correct_item_id=None,
        correct_item_name=None,
        correct_item_code=None,
        correct_image_url=None,
        correct_rank=None,
        correct_source=None,
        ranking_feedback_type=None,
        search_results=parts_module.SearchResults(
            items=[
                {
                    "item_id": "1",
                    "item_code": "4001",
                    "item_name": "A",
                    "similar": 0.99,
                    "image_url": "a1.jpg",
                    "matched_images": [
                        {
                            "image_url": "a1.jpg",
                            "rate": 0.99,
                            "matched_query_indexes": [0, 1],
                        }
                    ],
                }
            ]
        ),
    )

    item = RailwayPartsManager._build_search_history_item(row)

    assert item.search_type == "image"
    assert item.query_images == ["q1.jpg", "q2.jpg"]
    assert item.result.items[0].matched_images[0].matched_query_indexes == [0, 1]


def test_build_search_history_item_maps_public_statuses_by_history_and_latest_ticket():
    RailwayPartsManager, _parts_module = _import_railway_parts_manager()
    base_row = SimpleNamespace(
        id=1,
        time_created=datetime(2026, 5, 9, 10, 0, 0),
        query_text="q",
        query_image=None,
        query_images_json=None,
        search_equipment="web",
        verify_status="wrong",
        verify_remark=None,
        verified_at=None,
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="A",
        search_result_item_code="4001",
        correct_item_id=None,
        correct_item_name=None,
        correct_item_code=None,
        correct_image_url=None,
        correct_rank=None,
        correct_source=None,
        ranking_feedback_type=None,
        search_results=None,
    )

    pending_item = RailwayPartsManager._build_search_history_item(base_row)
    open_ticket_item = RailwayPartsManager._build_search_history_item(
        base_row,
        SimpleNamespace(id=11, review_status="open", issue_type="precision_issue"),
    )
    reviewing_ticket_item = RailwayPartsManager._build_search_history_item(
        base_row,
        SimpleNamespace(id=12, review_status="reviewing", issue_type="precision_issue"),
    )
    resolved_ticket_item = RailwayPartsManager._build_search_history_item(
        base_row,
        SimpleNamespace(id=13, review_status="resolved", issue_type="precision_issue"),
    )
    closed_ticket_item = RailwayPartsManager._build_search_history_item(
        base_row,
        SimpleNamespace(id=14, review_status="closed", issue_type="precision_issue"),
    )
    misjudged_item = RailwayPartsManager._build_search_history_item(
        SimpleNamespace(**{**base_row.__dict__, "id": 2, "verify_status": "user_misjudged"})
    )
    correct_item = RailwayPartsManager._build_search_history_item(
        SimpleNamespace(**{**base_row.__dict__, "id": 3, "verify_status": "correct"})
    )

    assert pending_item.status == "pending"
    assert open_ticket_item.status == "pending"
    assert reviewing_ticket_item.status == "pending"
    assert resolved_ticket_item.status == "wrong"
    assert closed_ticket_item.status == "wrong"
    assert misjudged_item.status == "correct"
    assert correct_item.status == "correct"


def test_list_v2_search_history_backfills_missing_result_item_name_from_items_table():
    from csrcqsf.modules.railway_parts.schemas.search import SearchHistoryListReq
    from csrcqsf.models.orm.search_history import SearchResults

    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    legacy_history = SimpleNamespace(
        id=2,
        time_created=datetime(2026, 4, 23, 12, 1, 0),
        query_text=None,
        query_image="bfr-search-history-files/query-images/20260427/2_query.png",
        search_results=SearchResults(items=[{"item_id": "1935558010375340032", "item_code": "11010150131", "similar": 0.9, "image_url": "bfr-ai-files/1960224080514424832.jpg"}]),
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="螺栓M8X22",
        search_result_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
    )
    page_result = SimpleNamespace(total=1, data=[legacy_history])
    fake_item = SimpleNamespace(id=1935558010375340032, item_name="螺栓M8X22")

    async def _yield_items(*args, **kwargs):
        yield fake_item

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(parts_module.SearchHistory, "list_search_history", AsyncMock(return_value=page_result)), \
         patch.object(parts_module.Items, "get_item_by_id_list", _yield_items), \
         patch.object(parts_module.SearchReviewTicket, "list_latest_by_history_ids", AsyncMock(return_value={})):
        res = asyncio.run(
            RailwayPartsManager.list_v2_search_history(SearchHistoryListReq(page=1, pageSize=10))
        )

    assert res.items[0].result.items[0].item_name == "螺栓M8X22"


def test_build_search_history_item_leaves_correct_result_empty_without_feedback():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    row = SimpleNamespace(
        id=1,
        time_created=datetime(2026, 4, 30, 17, 0, 0),
        query_text="制动盘",
        query_image=None,
        search_equipment="web",
        verify_status="pending",
        verify_remark=None,
        verified_at=None,
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
        ranking_feedback_type=None,
        selected_item_id=None,
        selected_item_code=None,
        selected_item_name=None,
        selected_rank=None,
        selected_image_url=None,
        correct_item_id=None,
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="制动2",
        search_result_item_code="40000728845",
        correct_item_code=None,
        correct_item_name=None,
        correct_image_url=None,
        correct_rank=None,
        correct_source=None,
    )

    item = RailwayPartsManager._build_search_history_item(row)

    assert item.search_item_name == "制动2"
    assert item.search_item_code == "40000728845"
    assert item.correct_item_id is None
    assert item.correct_item_name is None
    assert item.correct_source == "none"
    assert "effective_item_id" not in item.__fields__


def test_build_search_history_item_uses_unified_correct_result_fields():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    row = SimpleNamespace(
        id=1,
        time_created=datetime(2026, 4, 30, 17, 0, 0),
        query_text="制动盘",
        query_image=None,
        search_equipment="web",
        verify_status="correct",
        verify_remark="第二个结果才对",
        verified_at=datetime(2026, 4, 30, 17, 5, 0),
        search_results=parts_module.SearchResults(items=[]),
        ranking_feedback_type="topk_correct",
        selected_item_id=1950361513125318656,
        selected_item_code="40000728845",
        selected_item_name="制动2",
        selected_rank=2,
        selected_image_url="bfr-ai-files/selected.jpg",
        correct_item_id=1950361513125318656,
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="制动2",
        search_result_item_code="40000728845",
        correct_item_name="制动2",
        correct_item_code="40000728845",
        correct_image_url="bfr-ai-files/selected.jpg",
        correct_rank=2,
        correct_source="user_selected",
    )

    item = RailwayPartsManager._build_search_history_item(row)

    assert item.ranking_feedback_type == "topk_correct"
    assert item.correct_item_id == "1950361513125318656"
    assert item.correct_rank == 2
    assert item.correct_image_url == "bfr-ai-files/selected.jpg"
    assert item.correct_source == "user_selected"


def test_build_search_history_item_keeps_bucket_object_asset_urls():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()
    row = SimpleNamespace(
        id=2,
        time_created=datetime(2026, 6, 16, 12, 0, 0),
        query_text=None,
        query_image="bfr-search-history-files/query-images/20260616/demo.png",
        query_images_json=["bfr-search-history-files/query-images/20260616/extra.png"],
        search_equipment="web",
        verify_status="pending",
        verify_remark=None,
        verified_at=None,
        search_results=parts_module.SearchResults(items=[]),
        ranking_feedback_type=None,
        selected_item_id=None,
        selected_item_code=None,
        selected_item_name=None,
        selected_rank=None,
        selected_image_url=None,
        correct_item_id=1950361513125318656,
        inquery_id=None,
        inquery_num=None,
        search_result_item_name="制动2",
        search_result_item_code="40000728845",
        correct_item_name="制动2",
        correct_item_code="40000728845",
        correct_image_url="bfr-ai-files/selected.jpg",
        correct_rank=2,
        correct_source="user_selected",
    )

    item = RailwayPartsManager._build_search_history_item(row)

    assert item.query_image == "bfr-search-history-files/query-images/20260616/demo.png"
    assert item.query_images == [
        "bfr-search-history-files/query-images/20260616/extra.png"
    ]
    assert item.correct_image_url == "bfr-ai-files/selected.jpg"
