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
        "summary='V2检索历史校验提交', responses={",
        "- `verify_status`: 校验结果，支持 `correct`、`wrong`、`partial`",
        "summary='物料编码联想', responses={",
        "- `keyword`: 联想关键词，可输入物料编码或物料名称片段",
        "summary='V2检索历史批量删除', responses={",
        "- `history_id_list`: 待删除的检索历史ID列表",
    ]

    for fragment in expected_fragments:
        assert fragment in source
