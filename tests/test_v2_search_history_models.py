from csrcqsf.biz.railwayparts.api_models import (
    SearchHistoryListItem,
    SearchHistoryListReq,
    V2IndexDeleteRes,
)


BIG_ITEM_ID = 1935558010375340032


def dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", by_alias=True)
    return model.dict(by_alias=True)


def test_search_history_list_request_accepts_page_size_alias():
    req = SearchHistoryListReq(page=2, pageSize=20)

    assert req.page == 2
    assert req.per_page == 20


def test_search_history_list_item_serializes_history_id_as_string():
    item = SearchHistoryListItem(
        history_id=BIG_ITEM_ID,
        search_type="text",
        time_created="2026-04-23 10:00:00",
        search_item_name="螺栓M8X22",
        search_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
        parameters={
            "features": ["螺栓"],
            "images": [],
            "vechile": "",
            "parent_item_id": 0,
            "lower_rate": 0,
        },
        result={
            "items": [
                {
                    "item_id": BIG_ITEM_ID,
                    "item_code": "11010150131",
                    "similar": 0.98,
                }
            ]
        },
        inquery_id=None,
        inquery_num=None,
    )
    data = dump_model(item)

    assert data["history_id"] == str(BIG_ITEM_ID)
    assert data["search_type"] == "text"


def test_v2_index_delete_response_serializes_item_id_as_string():
    res = V2IndexDeleteRes(
        item_id=BIG_ITEM_ID,
        siglip_deleted=2,
        dinov2_deleted=2,
        message="V2索引删除成功",
    )
    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
