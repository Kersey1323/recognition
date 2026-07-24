"""Routes for search review ticket workflows."""

from csrcqsf.modules.railway_parts.schemas.review_ticket import (
    SearchReviewTicketDeleteReq,
    SearchReviewTicketDeleteRes,
    SearchReviewTicketDetailReq,
    SearchReviewTicketDetailRes,
    SearchReviewTicketListReq,
    SearchReviewTicketListRes,
    SearchReviewTicketSummaryRes,
    SearchReviewTicketUpdateReq,
    SearchReviewTicketUpdateRes,
)
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager

from .router import parts_router


@parts_router.post('/v2/search/reviewTicket/list', tags=["算法-向量检索V2"], summary='V2技术部核验清单分页查询', responses={
    200: {
        'model': SearchReviewTicketListRes
    }
}, description="""
请求体字段说明：

- `page`: 页码，从 1 开始
- `pageSize`: 每页数量
- `review_status`: 核验单状态筛选，支持 `all`、`open`、`reviewing`、`resolved`、`closed`、`deleted`，其中 `all` 默认不返回 `deleted`
- `issue_type`: 问题类型，支持 `missing_index`、`precision_issue`、`system_bug`、`user_misjudged`
- `search_equipment`: 检索设备筛选，支持 `all`、`web`、`terminal`
- `keyword`: 关键词筛选
- `date_from`: 开始日期，格式 `YYYY-MM-DD`
- `date_to`: 结束日期，格式 `YYYY-MM-DD`
""")
async def list_v2_search_review_tickets(req: SearchReviewTicketListReq):
    return await RailwayPartsManager.list_v2_search_review_tickets(req)


@parts_router.post('/v2/search/reviewTicket/detail', tags=["算法-向量检索V2"], summary='V2技术部核验单详情', responses={
    200: {
        'model': SearchReviewTicketDetailRes
    }
}, description="""
请求体字段说明：

- `ticket_id`: 核验单ID
""")
async def get_v2_search_review_ticket_detail(req: SearchReviewTicketDetailReq):
    return await RailwayPartsManager.get_v2_search_review_ticket_detail(ticket_id=int(req.ticket_id))


@parts_router.post('/v2/search/reviewTicket/update', tags=["算法-向量检索V2"], summary='V2技术部核验单更新', responses={
    200: {
        'model': SearchReviewTicketUpdateRes
    }
}, description="""
请求体字段说明：

- `ticket_id`: 核验单ID
- `review_status`: 目标状态，支持 `reviewing`、`resolved`、`closed`
- `issue_type`: 问题类型，支持 `missing_index`、`precision_issue`、`system_bug`、`user_misjudged`
- `review_remark`: 核验备注
- `resolution_remark`: 解决备注
- `correct_item_code`: 可选，纠正后的物料编码
""")
async def update_v2_search_review_ticket(req: SearchReviewTicketUpdateReq):
    return await RailwayPartsManager.update_v2_search_review_ticket(
        ticket_id=int(req.ticket_id),
        review_status=req.review_status,
        issue_type=req.issue_type,
        review_remark=req.review_remark,
        resolution_remark=req.resolution_remark,
        correct_item_code=req.correct_item_code,
    )


@parts_router.post('/v2/search/reviewTicket/delete', tags=["算法-向量检索V2"], summary='V2技术部核验单移出清单', responses={
    200: {
        'model': SearchReviewTicketDeleteRes
    }
}, description="""
请求体字段说明：

- `ticket_id_list`: 待移出校验清单的核验单ID列表
- `delete_remark`: 可选，移出清单备注
""")
async def delete_v2_search_review_ticket(req: SearchReviewTicketDeleteReq):
    return await RailwayPartsManager.delete_v2_search_review_ticket(
        ticket_id_list=[int(ticket_id) for ticket_id in req.ticket_id_list],
        delete_remark=req.delete_remark,
    )


@parts_router.post('/v2/search/reviewTicket/summary', tags=["算法-向量检索V2"], summary='V2技术部核验单统计', responses={
    200: {
        'model': SearchReviewTicketSummaryRes
    }
})
async def summary_v2_search_review_ticket():
    return await RailwayPartsManager.summary_v2_search_review_ticket()
