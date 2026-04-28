from csrcqsf.biz.railwayparts.api_models import (
    ItemSuggestReq,
    ItemSuggestRes,
    SearchHistoryDeleteReq,
    SearchHistoryDetailReq,
    SearchHistoryListItem,
    SearchHistoryListReq,
    SearchHistorySummaryRes,
    SearchHistoryVerifyReq,
)
from csrcqsf.models.search_history import SearchHistory


def dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", by_alias=True)
    return model.dict(by_alias=True)


def dump_schema(model_cls):
    if hasattr(model_cls, "model_json_schema"):
        return model_cls.model_json_schema(by_alias=True)
    return model_cls.schema(by_alias=True)


def test_search_history_table_has_review_status_columns():
    columns = list(SearchHistory.__table__.columns.keys())

    assert "verify_status" in columns
    assert "verify_remark" in columns
    assert "verified_at" in columns


def test_search_history_list_request_accepts_review_filters():
    req = SearchHistoryListReq(
        page=1,
        pageSize=10,
        search_type="image",
        keyword="19010036737",
        status="pending",
        date_from="2026-04-27",
        date_to="2026-04-28",
    )

    assert req.search_type == "image"
    assert req.keyword == "19010036737"
    assert req.status == "pending"
    assert req.date_from == "2026-04-27"
    assert req.date_to == "2026-04-28"


def test_search_history_list_item_serializes_status_and_result_image_urls():
    item = SearchHistoryListItem(
        history_id=1,
        search_type="image",
        time_created="2026-04-28 10:00:00",
        query_text=None,
        query_image="bfr-search-history-files/query-images/20260428/1_demo.png",
        status="pending",
        search_item_name="钢丝绳",
        search_item_code="19010036737",
        correct_item_name=None,
        correct_item_code=None,
        result={
            "items": [
                {
                    "item_id": "101",
                    "item_code": "19010036737",
                    "similar": 0.91,
                    "image_url": "bfr-ai-files/demo.jpg",
                }
            ]
        },
        inquery_id=None,
        inquery_num=None,
    )

    data = dump_model(item)

    assert data["status"] == "pending"
    assert data["result"]["items"][0]["image_url"] == "bfr-ai-files/demo.jpg"


def test_review_console_request_and_response_models_serialize():
    detail_req = SearchHistoryDetailReq(history_id="1")
    verify_req = SearchHistoryVerifyReq(
        history_id="1",
        verify_status="correct",
        correct_item_code="19010036737",
        remark="人工确认正确",
    )
    delete_req = SearchHistoryDeleteReq(history_id_list=["1", "2"])
    suggest_req = ItemSuggestReq(keyword="1901", limit=5)
    summary = SearchHistorySummaryRes(
        total=10,
        pending_count=4,
        correct_count=3,
        wrong_count=2,
        partial_count=1,
    )
    suggest = ItemSuggestRes(
        items=[{"item_id": "1", "item_code": "19010036737", "item_name": "钢丝绳"}]
    )

    assert detail_req.history_id == "1"
    assert verify_req.verify_status == "correct"
    assert delete_req.history_id_list == ["1", "2"]
    assert suggest_req.limit == 5
    assert dump_model(summary)["pending_count"] == 4
    assert dump_model(suggest)["items"][0]["item_code"] == "19010036737"


def test_review_console_request_models_expose_openapi_examples_and_descriptions():
    list_schema = dump_schema(SearchHistoryListReq)
    detail_schema = dump_schema(SearchHistoryDetailReq)
    verify_schema = dump_schema(SearchHistoryVerifyReq)
    suggest_schema = dump_schema(ItemSuggestReq)
    delete_schema = dump_schema(SearchHistoryDeleteReq)

    assert list_schema["properties"]["search_type"]["description"] == "检索类型筛选：all 全部，text 文本检索，image 图片检索"
    assert list_schema["properties"]["status"]["description"] == "校验状态筛选：all 全部，pending 待校验，correct 正确，wrong 错误，partial 部分正确"
    assert list_schema["example"]["search_type"] == "image"
    assert list_schema["example"]["status"] == "pending"

    assert detail_schema["properties"]["history_id"]["description"] == "检索历史ID"
    assert detail_schema["example"]["history_id"] == "2048696242753638400"

    assert verify_schema["properties"]["verify_status"]["description"] == "校验结果：correct 正确，wrong 错误，partial 部分正确"
    assert verify_schema["example"]["correct_item_code"] == "19010036737"

    assert suggest_schema["properties"]["keyword"]["description"] == "联想关键词，可输入物料编码或物料名称片段"
    assert suggest_schema["example"]["limit"] == 10

    assert delete_schema["properties"]["history_id_list"]["description"] == "待删除的检索历史ID列表"
    assert delete_schema["example"]["history_id_list"] == ["2048696242753638400", "2048696242753638401"]
