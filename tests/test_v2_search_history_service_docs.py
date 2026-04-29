from pathlib import Path


def test_review_console_routes_have_request_body_descriptions():
    source = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    expected_fragments = [
        "summary='V2检索历史分页查询', responses={",
        "请求体字段说明：",
        "- `page`: 页码，从 1 开始",
        "- `pageSize`: 每页数量",
        "- `search_type`: 检索类型筛选，支持 `all`、`text`、`image`",
        "summary='V2检索历史详情', responses={",
        "- `history_id`: 检索历史ID",
        "summary='V2检索历史校验提交', deprecated=True, responses={",
        "- `verify_status`: 校验结果，支持 `correct`、`wrong`、`partial`",
        "summary='物料编码联想', responses={",
        "- `keyword`: 联想关键词，可输入物料编码或物料名称片段",
        "summary='V2检索历史批量删除', responses={",
        "- `history_id_list`: 待删除的检索历史ID列表",
    ]

    for fragment in expected_fragments:
        assert fragment in source


def test_review_console_routes_describe_feedback_and_review_ticket_contract():
    source = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    expected_fragments = [
        "summary='V2检索历史用户反馈提交'",
        "- `feedback_result`: 用户反馈结果，支持 `correct`、`wrong`",
        "summary='V2技术部核验清单分页查询'",
        "- `review_status`: 核验单状态筛选，支持 `all`、`open`、`reviewing`、`resolved`、`closed`",
        "- `search_equipment`: 检索设备筛选，支持 `all`、`web`、`terminal`",
        "summary='V2技术部核验单详情'",
        "- `ticket_id`: 核验单ID",
        "summary='V2技术部核验单更新'",
        "- `issue_type`: 问题类型，支持 `missing_index`、`precision_issue`、`system_bug`",
        "- `review_remark`: 核验备注",
        "- `resolution_remark`: 解决备注",
        "- `correct_item_code`: 可选，纠正后的物料编码",
        "summary='V2技术部核验单统计'",
        "'model': SearchReviewTicketSummaryRes",
        "'model': SearchReviewTicketDetailRes",
        "'model': SearchReviewTicketListRes",
        "'model': SearchReviewTicketUpdateRes",
    ]

    for fragment in expected_fragments:
        assert fragment in source


def test_search_routes_describe_item_aggregation_contract():
    source = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    expected_fragments = [
        "summary='V2文本检索'",
        "- top_k: 参与聚合的图片命中数量",
        "- 返回结果按 item_id 聚合为候选配件列表",
        "- matched_images: 当前候选配件在本次检索中命中的图片列表",
        "summary='V2图像检索'",
    ]

    for fragment in expected_fragments:
        assert fragment in source
