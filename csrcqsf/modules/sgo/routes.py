from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, root_validator

from bfrcommon.api_models import PageReq, PageRes
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.modules.sgo.repositories import SgoItemImages
from csrcqsf.modules.sgo.photo_parser import extract_photo_raw_urls
from csrcqsf.modules.sgo.services import SGOBiz
from csrcqsf.modules.sgo.item_mapping import normalize_sgo_return_item
from csrcqsf.modules.sgo.schemas import (
    ListInqueryItem,
    SgoA9CleanupExecuteReq,
    SgoA9CleanupPreviewRes,
    SgoSyncFailureListReq,
    SgoSyncFailureListRes,
    SgoSyncFailureRecord,
    SgoSyncTaskCancelReq,
    SgoSyncTaskDeleteReq,
    SgoSyncTaskDeleteRes,
    SgoSyncTaskListReq,
    SgoSyncTaskListRes,
    SgoSyncTaskStatisticsReq,
    SgoSyncTaskStatisticsRes,
    SgoSyncTaskStartRes,
    SgoSyncTaskStatusRes,
)
from csrcqsf.modules.sgo.sync_task_manager import sgo_sync_task_manager

sgo_router = APIRouter(
    prefix="/sgo",
    tags=["sgo"],
    responses={404: {"description": "Not found"}},
)


class ListInqueryReq(PageReq):
    query: str | None = Field(
        default=None,
        max_length=200,
        description='搜索关键词，模糊匹配询码单号、名称描述、车型、车号、所属部件、供应商及提报信息',
        example='监控室对面窗帘',
    )
    vehicle: str | None = Field(
        default=None,
        max_length=100,
        description='车型筛选，可单独使用，也可与列号/车厢号同时筛选；按包含关系模糊匹配',
        example='CRH380B',
    )
    train_no: str | None = Field(
        default=None,
        max_length=100,
        description='列号筛选，可单独使用，也可与车型/车厢号同时筛选；按包含关系模糊匹配',
        example='D6521',
    )
    car_num: str | None = Field(
        default=None,
        max_length=100,
        description='车厢号筛选，可单独使用，也可与车型/列号同时筛选；按包含关系模糊匹配',
        example='05',
    )
    has_indexed: int = Field(default=0, description='1. 做过索引了 2. 没做过索引 0 不要这个条件', example=0)
    current_status: str = Field(
        default='FINISH',
        description='询码的状态.FINISH 已结束 CREATE:技术部待回复 CONFIRMAUDIT:编码确认审核中 BACKAUDIT:驳回审核中 REGING:编码注册中',
        example='FINISH',
    )

    class Config:
        json_schema_extra = {
            "example": {
                "page": 1,
                "pageSize": 20,
                "query": "监控室对面窗帘",
                "vehicle": "CRH380B",
                "train_no": "D6521",
                "car_num": "05",
                "has_indexed": 0,
                "current_status": "FINISH",
            }
        }


class ListInqueryRes(PageRes):
    items: list[ListInqueryItem] = []


class SyncItemsReq(BaseModel):
    pass


class SyncItemsImages(BaseModel):
    sync_scope: Literal["selected", "all"] = Field(
        default="selected",
        description="selected 同步指定配件；all 同步主库全部配件",
    )
    items_id_list: list[str] = Field(
        default_factory=list,
        description="selected 模式下需要同步的配件 ID",
    )

    @root_validator
    def validate_scope(cls, values):
        scope = values.get("sync_scope")
        item_ids = values.get("items_id_list") or []
        if scope == "selected" and not item_ids:
            raise ValueError("selected 模式必须提供 items_id_list")
        if scope == "all" and item_ids:
            raise ValueError("all 模式不允许提供 items_id_list")
        return values


class SyncInquiryHistoryReq(BaseModel):
    limit: int | None = Field(default=None, description="仅同步前 N 条，空值表示全量")
    batch_size: int = Field(default=500, ge=1, description="每批写入主库的记录数")


@sgo_router.post('/sgo/parts/sync', tags=["业务-SGO集成"], summary='同步配件、供应商及父子层级信息', responses={
    200: {
        'model': str
    }
})
async def sgo_parts_sync(_: SyncItemsReq):
    try:
        task = await sgo_sync_task_manager.start("parts", SGOBiz.sync_parts_items)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SgoSyncTaskStartRes(
        message="配件、供应商及父子层级同步任务已在后台启动",
        task_id=task["task_id"],
        task_type=task["task_type"],
        status=task["status"],
    )


@sgo_router.get(
    '/sgo/parts/cleanup/a9/preview',
    tags=["业务-SGO集成"],
    summary='预览待清理的 A9 演示配件',
    response_model=SgoA9CleanupPreviewRes,
)
async def preview_sgo_a9_cleanup():
    return SgoA9CleanupPreviewRes(**(await SGOBiz.preview_a9_cleanup()))


@sgo_router.post(
    '/sgo/parts/cleanup/a9',
    tags=["业务-SGO集成"],
    summary='清理已同步的 A9 演示配件',
    response_model=SgoSyncTaskStartRes,
    description='仅清理未同时出现在 A1/A3/A5 的 A9 配件；必须先调用预览接口确认范围。',
)
async def execute_sgo_a9_cleanup(_: SgoA9CleanupExecuteReq):
    try:
        task = await sgo_sync_task_manager.start(
            "parts-cleanup",
            SGOBiz.cleanup_a9_demo_data,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SgoSyncTaskStartRes(
        message="A9 演示配件清理任务已在后台启动",
        task_id=task["task_id"],
        task_type=task["task_type"],
        status=task["status"],
    )


@sgo_router.post('/sgo/parts/images/sync', tags=["业务-SGO集成"], summary='同步选中的配件的照片', responses={
    200: {
        'model': str
    }
})
async def sgo_parts_image_sync(req: SyncItemsImages):
    try:
        task = await sgo_sync_task_manager.start(
            "images",
            SGOBiz.sync_images,
            item_id_list=req.items_id_list,
            sync_scope=req.sync_scope,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SgoSyncTaskStartRes(
        message="配件图片同步任务已在后台启动",
        task_id=task["task_id"],
        task_type=task["task_type"],
        status=task["status"],
    )


@sgo_router.post(
    '/sgo/inquiry-history/sync',
    tags=["业务-SGO集成"],
    summary='同步 SGO 询码历史到主业务库',
)
async def sgo_inquiry_history_sync(req: SyncInquiryHistoryReq):
    try:
        task = await sgo_sync_task_manager.start(
            "inquiry-history",
            SGOBiz.sync_inquiry_history,
            limit=req.limit,
            batch_size=req.batch_size,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SgoSyncTaskStartRes(
        message="SGO 询码历史同步任务已在后台启动",
        task_id=task["task_id"],
        task_type=task["task_type"],
        status=task["status"],
    )


@sgo_router.get(
    '/sgo/sync/status/{task_id}',
    tags=["业务-SGO集成"],
    summary='查询 SGO 同步任务进度',
)
async def sgo_sync_status(task_id: str):
    task = await sgo_sync_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"SGO 同步任务不存在: task_id={task_id}")
    return SgoSyncTaskStatusRes(**task)


@sgo_router.post(
    '/sgo/sync/tasks/list',
    tags=["业务-SGO集成"],
    summary='分页查询持久化 SGO 同步任务',
    response_model=SgoSyncTaskListRes,
)
async def list_sgo_sync_tasks(req: SgoSyncTaskListReq):
    records, total = await sgo_sync_task_manager.list(
        page=req.page,
        per_page=req.per_page,
        status=req.status,
        task_type=req.task_type,
    )
    return SgoSyncTaskListRes(
        total=total,
        page=req.page,
        pageSize=req.per_page,
        records=[SgoSyncTaskStatusRes(**record) for record in records],
    )


@sgo_router.post(
    '/sgo/sync/tasks/delete',
    tags=["业务-SGO集成"],
    summary='批量删除已结束的 SGO 同步任务',
    response_model=SgoSyncTaskDeleteRes,
    description='删除明确指定的历史任务及其失败明细；请求中包含活动任务时整批拒绝，不级联删除重试链或语义索引任务。',
)
async def delete_sgo_sync_tasks(req: SgoSyncTaskDeleteReq):
    try:
        result = await sgo_sync_task_manager.delete_tasks(req.task_id_list)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SgoSyncTaskDeleteRes(**result)


@sgo_router.post(
    '/sgo/sync/tasks/statistics',
    tags=["业务-SGO集成"],
    summary='按同步类型统计任务状态',
    response_model=SgoSyncTaskStatisticsRes,
)
async def get_sgo_sync_task_statistics(req: SgoSyncTaskStatisticsReq):
    return SgoSyncTaskStatisticsRes(
        **(await sgo_sync_task_manager.statistics(req.type))
    )


@sgo_router.get(
    '/sgo/sync/tasks/{task_id}',
    tags=["业务-SGO集成"],
    summary='查询持久化 SGO 同步任务详情',
    response_model=SgoSyncTaskStatusRes,
)
async def get_sgo_sync_task(task_id: str):
    task = await sgo_sync_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"SGO 同步任务不存在: task_id={task_id}")
    return SgoSyncTaskStatusRes(**task)


@sgo_router.post(
    '/sgo/sync/tasks/{task_id}/cancel',
    tags=["业务-SGO集成"],
    summary='取消 SGO 同步任务',
    response_model=SgoSyncTaskStatusRes,
)
async def cancel_sgo_sync_task(task_id: str, req: SgoSyncTaskCancelReq):
    try:
        task = await sgo_sync_task_manager.cancel(task_id, req.cancel_reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SGO 同步任务不存在: task_id={task_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SgoSyncTaskStatusRes(**task)


@sgo_router.post(
    '/sgo/sync/tasks/{task_id}/retry',
    tags=["业务-SGO集成"],
    summary='按原参数重试 SGO 同步任务',
    response_model=SgoSyncTaskStartRes,
)
async def retry_sgo_sync_task(task_id: str):
    try:
        task = await sgo_sync_task_manager.retry(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"SGO 同步任务不存在: task_id={task_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SgoSyncTaskStartRes(
        message="SGO 同步重试任务已在后台启动",
        task_id=task["task_id"],
        task_type=task["task_type"],
        status=task["status"],
    )


@sgo_router.post(
    '/sgo/sync/tasks/{task_id}/failures/list',
    tags=["业务-SGO集成"],
    summary='分页查询 SGO 同步失败明细',
    response_model=SgoSyncFailureListRes,
)
async def list_sgo_sync_task_failures(task_id: str, req: SgoSyncFailureListReq):
    if await sgo_sync_task_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail=f"SGO 同步任务不存在: task_id={task_id}")
    records, total = await sgo_sync_task_manager.list_failures(
        task_id,
        page=req.page,
        per_page=req.per_page,
        stage=req.stage,
        error_type=req.error_type,
        error_message=req.error_message,
        error_code=req.error_code,
    )
    return SgoSyncFailureListRes(
        total=total,
        page=req.page,
        pageSize=req.per_page,
        records=[SgoSyncFailureRecord(**record) for record in records],
    )


@sgo_router.post('/sgo/inquery/list', tags=["业务-SGO集成"], summary='获取询码记录列表', responses={
    200: {
        'model': ListInqueryRes
    }
})
async def sgo_inquery_list(req: ListInqueryReq):
    """
    获取询码记录列表。

    请求体字段说明：
    - `query`: 通用关键词，对询码单号/名称描述/人工确认的配件编码和名称/车型/列号/
      车厢号/部件/供应商等多个字段任一命中
    - `vehicle`（车型）、`train_no`（列号）、`car_num`（车厢号）: 三个独立检索字段，
      可只传其中一个，也可任意两个或三个同时传入（同时传入时按 AND 叠加筛选，
      互不依赖、无需级联），每个字段均按包含关系模糊匹配
    - `has_indexed`: 1=已索引 2=未索引 0=不限
    - `current_status`: 询码状态筛选
    """
    if req.has_indexed not in (0, 1, 2):
        raise Exception('has_indexed只能为0,1或者2')

    inquery_list = await SGOBiz.list_inquery(
        req.page,
        req.per_page,
        req.current_status,
        req.has_indexed,
        req.query,
        req.vehicle,
        req.train_no,
        req.car_num,
    )
    res = ListInqueryRes(total=inquery_list.total)

    raw_url_list: list[str] = []
    for data in inquery_list.data:
        raw_url_list.extend(extract_photo_raw_urls(data.nameplate_photos))
        raw_url_list.extend(extract_photo_raw_urls(data.detailed_photos))

    sgo_image_dict: dict[str, SgoItemImages] = {}
    if raw_url_list:
        async with SessionLocal() as session:
            sgo_images = await SgoItemImages.list_item_images_by_raw_url(session, raw_url_list)
            for image in sgo_images:
                sgo_image_dict[image.raw_url] = image

    for data in inquery_list.data:
        item = ListInqueryItem(id=data.id)
        item.car_num = data.car_num
        item.creater = data.creater
        item.creater_org_name = data.creater_org_name
        item.current_status = data.current_status
        item.return_item_code, item.return_item_name = normalize_sgo_return_item(
            getattr(data, "return_item_name_raw", None),
            getattr(data, "return_item_code_raw", None),
        )
        item.detailed_photos = data.detailed_photos
        item.inquiry_num = data.inquiry_num
        item.item_name = data.item_name
        item.remark = data.remark
        item.vehicle = data.vehicle
        item.nameplate_photos = data.nameplate_photos
        item.submission_date = data.submission_date
        item.supplier_code = data.supplier_code
        item.supplier_name = data.supplier_name
        item.train_no = data.train_no
        item.subordinate_component = data.subordinate_component

        for url in extract_photo_raw_urls(data.nameplate_photos):
            if url in sgo_image_dict:
                item.nameplate_photos_urls.append(sgo_image_dict[url].image_url)

        for url in extract_photo_raw_urls(data.detailed_photos):
            if url in sgo_image_dict:
                item.detailed_photos_urls.append(sgo_image_dict[url].image_url)

        res.items.append(item)

    return res
