from csrcqsf.biz.railwayparts.api_models import (
    SearchRes,
    SearchTextReq,
    SearchHistoryFeedbackReq,
    SearchHistoryFeedbackRes,
    SearchHistoryListItem,
    SearchHistoryListReq,
    SearchItem,
    SearchReviewTicketListReq,
    SearchReviewTicketListRes,
    SearchReviewTicketDetailReq,
    SearchReviewTicketDetailRes,
    SearchReviewTicketUpdateReq,
    SearchReviewTicketUpdateRes,
    SearchReviewTicketSummaryRes,
    SearchReviewTicketItem,
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


def test_search_history_list_request_accepts_search_equipment_filter():
    req = SearchHistoryListReq(page=1, pageSize=10, search_equipment="terminal")

    assert req.search_equipment == "terminal"


def test_search_history_list_item_serializes_explicit_query_fields():
    item = SearchHistoryListItem(
        history_id=BIG_ITEM_ID,
        search_type="text",
        time_created="2026-04-23 10:00:00",
        query_text="螺栓",
        query_image=None,
        search_item_name="螺栓M8X22",
        search_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
        result={
            "items": [
                {
                    "item_id": BIG_ITEM_ID,
                    "item_code": "11010150131",
                    "item_name": "螺栓M8X22",
                    "similar": 0.98,
                    "image_url": "bfr-ai-files/bolt.jpg",
                }
            ]
        },
        inquery_id=None,
        inquery_num=None,
    )
    data = dump_model(item)

    assert data["history_id"] == str(BIG_ITEM_ID)
    assert data["search_type"] == "text"
    assert data["query_text"] == "螺栓"
    assert data["query_image"] is None
    assert "parameters" not in data
    assert data["result"]["items"][0]["item_id"] == str(BIG_ITEM_ID)
    assert data["result"]["items"][0]["item_name"] == "螺栓M8X22"
    assert data["result"]["items"][0]["image_url"] == "bfr-ai-files/bolt.jpg"


def test_search_item_serializes_matched_images():
    item = SearchItem(
        item_id="1950361513125318656",
        item_code="40000728845",
        item_name="制动2",
        image_url="bfr-ai-files/1960224093814181888.jpg",
        rate=0.9584,
        matched_images=[
            {
                "image_url": "bfr-ai-files/1960224093814181888.jpg",
                "rate": 0.9584,
                "matched_query_indexes": [0, 1],
            },
            {"image_url": "bfr-ai-files/1960224087363723264.jpg", "rate": 0.9584},
        ],
    )

    data = dump_model(item)

    assert data["item_id"] == "1950361513125318656"
    assert len(data["matched_images"]) == 2
    assert data["matched_images"][0]["image_url"].endswith("1960224093814181888.jpg")
    assert data["matched_images"][0]["rate"] == 0.9584
    assert data["matched_images"][0]["matched_query_indexes"] == [0, 1]


def test_search_text_request_model_serializes_request_body_fields():
    req = SearchTextReq(query_text="制动盘", top_k=5)

    data = dump_model(req)

    assert data == {
        "query_text": "制动盘",
        "top_k": 5,
        "search_equipment": "web",
    }


def test_search_response_serializes_history_id():
    res = SearchRes(
        history_id="2048696242753638400",
        data=[
            SearchItem(
                item_id="1950361513125318656",
                item_code="40000728845",
                item_name="制动2",
                image_url="bfr-ai-files/1960224093814181888.jpg",
                rate=0.9584,
            )
        ],
        message=None,
    )

    data = dump_model(res)

    assert data["history_id"] == "2048696242753638400"
    assert data["data"][0]["item_id"] == "1950361513125318656"


def test_search_history_list_item_serializes_aggregated_result_items():
    item = SearchHistoryListItem(
        history_id=BIG_ITEM_ID,
        search_type="text",
        time_created="2026-04-29 10:00:00",
        query_text="制动盘",
        query_image=None,
        search_item_name="制动2",
        search_item_code="40000728845",
        correct_item_name=None,
        correct_item_code=None,
        result={
            "items": [
                {
                    "item_id": "1950361513125318656",
                    "item_code": "40000728845",
                    "item_name": "制动2",
                    "similar": 0.9584,
                    "image_url": "bfr-ai-files/1960224093814181888.jpg",
                    "matched_images": [
                        {
                            "image_url": "bfr-ai-files/1960224093814181888.jpg",
                            "rate": 0.9584,
                            "matched_query_indexes": [0, 1],
                        },
                        {"image_url": "bfr-ai-files/1960224087363723264.jpg", "rate": 0.9584},
                    ],
                }
            ]
        },
        inquery_id=None,
        inquery_num=None,
    )
    data = dump_model(item)

    assert data["result"]["items"][0]["item_id"] == "1950361513125318656"
    assert data["result"]["items"][0]["image_url"].endswith("1960224093814181888.jpg")
    assert len(data["result"]["items"][0]["matched_images"]) == 2
    assert data["result"]["items"][0]["matched_images"][0]["matched_query_indexes"] == [0, 1]


def test_search_history_list_item_serializes_query_images():
    item = SearchHistoryListItem(
        history_id=BIG_ITEM_ID,
        search_type="image",
        time_created="2026-05-09 10:00:00",
        query_text=None,
        query_image=None,
        query_images=[
            "bfr-search-history-files/query-images/20260509/1.jpg",
            "bfr-search-history-files/query-images/20260509/2.jpg",
        ],
        status="pending",
        result={
            "items": [
                {
                    "item_id": BIG_ITEM_ID,
                    "item_code": "4000001",
                    "item_name": "测试配件",
                    "similar": 0.98,
                    "image_url": "bfr-ai-files/1.jpg",
                    "matched_images": [
                        {
                            "image_url": "bfr-ai-files/1.jpg",
                            "rate": 0.98,
                            "matched_query_indexes": [0, 1],
                        }
                    ],
                }
            ]
        },
        inquery_id=None,
        inquery_num=None,
        search_item_name="测试配件",
        search_item_code="4000001",
        correct_item_name=None,
        correct_item_code=None,
    )

    data = dump_model(item)

    assert data["query_images"] == [
        "bfr-search-history-files/query-images/20260509/1.jpg",
        "bfr-search-history-files/query-images/20260509/2.jpg",
    ]
    assert data["result"]["items"][0]["matched_images"][0]["matched_query_indexes"] == [0, 1]


def test_search_history_list_item_serializes_review_ticket_summary_fields():
    item = SearchHistoryListItem(
        history_id=BIG_ITEM_ID,
        search_type="text",
        time_created="2026-04-23 10:00:00",
        query_text="螺栓",
        query_image=None,
        search_equipment="terminal",
        feedback_remark="识别错误",
        feedback_at="2026-04-23 10:05:00",
        has_open_review_ticket=True,
        latest_ticket_id="3001",
        latest_review_status="reviewing",
        latest_issue_type="precision_issue",
        search_item_name="螺栓M8X22",
        search_item_code="11010150131",
        correct_item_name=None,
        correct_item_code=None,
        result=None,
        inquery_id=None,
        inquery_num=None,
    )
    data = dump_model(item)

    assert data["search_equipment"] == "terminal"
    assert data["feedback_remark"] == "识别错误"
    assert data["feedback_at"] == "2026-04-23 10:05:00"
    assert data["has_open_review_ticket"] is True
    assert data["latest_ticket_id"] == "3001"
    assert data["latest_review_status"] == "reviewing"
    assert data["latest_issue_type"] == "precision_issue"


def test_feedback_and_review_ticket_request_models_serialize():
    feedback_req = SearchHistoryFeedbackReq(
        history_id="1001",
        feedback_result="wrong",
        remark="结果错误",
    )
    feedback_res = SearchHistoryFeedbackRes(
        history_id="1001",
        verify_status="wrong",
        feedback_remark="结果错误",
        feedback_at="2026-04-23 11:00:00",
        ticket_id="5001",
        ticket_created=True,
        message="提交成功",
    )
    ticket_req = SearchReviewTicketListReq(
        page=1,
        pageSize=10,
        review_status="open",
        issue_type="precision_issue",
        search_equipment="terminal",
        keyword="钢丝绳",
        date_from="2026-04-20",
        date_to="2026-04-28",
    )
    ticket_item = SearchReviewTicketItem(
        ticket_id="5001",
        history_id="1001",
        review_status="open",
        issue_type="precision_issue",
        time_created="2026-04-23 11:00:00",
        time_updated="2026-04-23 12:00:00",
        query_text="钢丝绳",
        query_image=None,
        search_equipment="terminal",
        search_item_name="钢丝绳",
        search_item_code="19010036737",
        feedback_remark="结果错误",
        correct_item_name=None,
        correct_item_code=None,
    )

    assert dump_model(feedback_req)["feedback_result"] == "wrong"
    assert dump_model(feedback_res)["ticket_id"] == "5001"
    assert ticket_req.review_status == "open"
    assert dump_model(ticket_item)["issue_type"] == "precision_issue"
    assert dump_model(ticket_item)["search_equipment"] == "terminal"


def test_review_ticket_models_include_search_type_and_normalize_null_feedback():
    ticket_item = SearchReviewTicketItem(
        ticket_id="5001",
        history_id="1001",
        review_status="open",
        issue_type="precision_issue",
        time_created="2026-04-23 11:00:00",
        time_updated="2026-04-23 12:00:00",
        search_type="image",
        feedback_remark="null",
    )
    detail_res = SearchReviewTicketDetailRes(
        ticket_id="5001",
        history_id="1001",
        review_status="reviewing",
        time_created="2026-04-23 11:00:00",
        time_updated="2026-04-23 12:00:00",
        search_type="text",
        feedback_remark="null",
    )

    item_data = dump_model(ticket_item)
    detail_data = dump_model(detail_res)

    assert item_data["search_type"] == "image"
    assert item_data["feedback_remark"] is None
    assert detail_data["search_type"] == "text"
    assert detail_data["feedback_remark"] is None


def test_search_history_list_item_normalizes_public_statuses():
    correct_item = SearchHistoryListItem(
        history_id="1001",
        search_type="text",
        time_created="2026-04-30 17:00:00",
        query_text="制动盘",
        status="correct",
        result=None,
        inquery_id=None,
        inquery_num=None,
        search_item_name="制动2",
        search_item_code="40000728845",
        correct_item_name=None,
        correct_item_code=None,
    )
    wrong_item = SearchHistoryListItem(
        history_id="1002",
        search_type="text",
        time_created="2026-04-30 17:00:00",
        query_text="制动盘",
        status="wrong",
        result=None,
        inquery_id=None,
        inquery_num=None,
        search_item_name="制动2",
        search_item_code="40000728845",
        correct_item_name=None,
        correct_item_code=None,
    )

    assert dump_model(correct_item)["status"] == "correct"
    assert dump_model(wrong_item)["status"] == "wrong"


def test_search_history_feedback_request_accepts_optional_selected_fields():
    req = SearchHistoryFeedbackReq(
        history_id="1001",
        feedback_result="correct",
        remark="第二个结果才是正确的",
        selected_item_id="1950361513125318656",
    )

    data = dump_model(req)

    assert data["selected_item_id"] == "1950361513125318656"
    assert "selected_item_code" not in data
    assert "selected_rank" not in data
    assert "selected_image_url" not in data


def test_search_history_list_item_serializes_only_correct_item_fields_publicly():
    item = SearchHistoryListItem(
        history_id="1001",
        search_type="text",
        time_created="2026-04-30 17:00:00",
        query_text="制动盘",
        query_image=None,
        status="correct",
        result=None,
        inquery_id=None,
        inquery_num=None,
        search_item_name="制动2",
        search_item_code="40000728845",
        correct_item_id="1950361513125318656",
        correct_item_code="40000728845",
        correct_item_name="制动2",
        correct_image_url="bfr-ai-files/1960224080514424832.jpg",
        correct_rank=2,
        correct_source="user_selected",
        ranking_feedback_type="topk_correct",
    )
    data = dump_model(item)

    assert data["correct_item_id"] == "1950361513125318656"
    assert data["correct_rank"] == 2
    assert data["correct_source"] == "user_selected"
    assert data["ranking_feedback_type"] == "topk_correct"
    assert "effective_item_id" not in data
    assert "selected_item_id" not in data


def test_search_history_feedback_response_no_longer_exposes_selected_or_effective_fields():
    res = SearchHistoryFeedbackRes(
        history_id="1001",
        verify_status="correct",
        ranking_feedback_type="topk_correct",
        feedback_remark="第二个结果才对",
        feedback_at="2026-04-30 18:00:00",
        correct_item_id="2",
        correct_item_code="B",
        correct_item_name="正确候选",
        correct_image_url="bfr-ai-files/top2.jpg",
        correct_rank=2,
        correct_source="user_selected",
        ticket_id=None,
        ticket_created=False,
        message="用户反馈提交成功",
    )

    data = dump_model(res)

    assert data["correct_item_id"] == "2"
    assert "selected_item_id" not in data
    assert "effective_item_id" not in data


def test_review_ticket_contract_models_serialize():
    detail_req = SearchReviewTicketDetailReq(ticket_id="5001")
    detail_res = SearchReviewTicketDetailRes(
        ticket_id="5001",
        history_id="1001",
        review_status="reviewing",
        issue_type="precision_issue",
        time_created="2026-04-23 11:00:00",
        time_updated="2026-04-23 12:00:00",
        review_remark="已接单核验",
        resolution_remark="已修复精度问题",
        review_started_at="2026-04-23 11:30:00",
        resolved_at="2026-04-23 12:00:00",
        closed_at=None,
        query_text="钢丝绳",
        query_image=None,
        search_equipment="terminal",
        result=None,
        search_item_name="钢丝绳",
        search_item_code="19010036737",
        feedback_remark="结果错误",
        correct_item_name=None,
        correct_item_code=None,
    )
    list_item = SearchReviewTicketItem(
        ticket_id="5001",
        history_id="1001",
        review_status="reviewing",
        issue_type="precision_issue",
        time_created="2026-04-23 11:00:00",
        time_updated="2026-04-23 12:00:00",
        query_text="钢丝绳",
        query_image=None,
        search_equipment="terminal",
        search_item_name="钢丝绳",
        search_item_code="19010036737",
        feedback_remark="结果错误",
        correct_item_name=None,
        correct_item_code=None,
    )
    list_res = SearchReviewTicketListRes(total=1, page=1, pageSize=10, items=[list_item])
    update_req = SearchReviewTicketUpdateReq(
        ticket_id="5001",
        review_status="resolved",
        issue_type="precision_issue",
        review_remark="已接单核验",
        resolution_remark="已修复",
        correct_item_code="19010036737",
    )
    update_res = SearchReviewTicketUpdateRes(
        ticket_id="5001",
        review_status="resolved",
        issue_type="precision_issue",
        review_remark="已接单核验",
        resolution_remark="已修复",
        correct_item_code="19010036737",
        correct_item_name="钢丝绳",
        message="更新成功",
    )
    summary_res = SearchReviewTicketSummaryRes(
        total=5,
        open_count=2,
        reviewing_count=1,
        resolved_count=1,
        closed_count=1,
        missing_index_count=1,
        precision_issue_count=3,
        system_bug_count=1,
        user_misjudged_count=1,
    )

    assert detail_req.ticket_id == "5001"
    assert dump_model(detail_res)["time_created"] == "2026-04-23 11:00:00"
    assert dump_model(detail_res)["time_updated"] == "2026-04-23 12:00:00"
    assert dump_model(list_res)["items"][0]["ticket_id"] == "5001"
    assert dump_model(update_req)["review_status"] == "resolved"
    assert "verify_status" not in dump_model(update_req)
    assert dump_model(update_req)["review_remark"] == "已接单核验"
    assert dump_model(update_req)["resolution_remark"] == "已修复"
    assert dump_model(update_req)["correct_item_code"] == "19010036737"
    assert dump_model(update_res)["message"] == "更新成功"
    assert dump_model(summary_res)["open_count"] == 2
    assert dump_model(summary_res)["precision_issue_count"] == 3
    assert dump_model(summary_res)["user_misjudged_count"] == 1


def test_v2_index_delete_response_serializes_item_id_as_string():
    res = V2IndexDeleteRes(
        item_id=BIG_ITEM_ID,
        siglip_deleted=2,
        dinov2_deleted=2,
        message="V2索引删除成功",
    )
    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
