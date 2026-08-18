from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from bfrcommon.api_models import PageReq, PageRes
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.modules.sgo.repositories import SgoItemImages
from csrcqsf.modules.sgo.photo_parser import extract_photo_raw_urls
from csrcqsf.modules.sgo.services import SGOBiz
from csrcqsf.modules.sgo.schemas import (
    ListInqueryItem,
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
    has_indexed: int = Field(default=1, description='1. 做过索引了 2. 没做过索引 0 不要这个条件', example=0)
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
                "has_indexed": 0,
                "current_status": "FINISH",
            }
        }


class ListInqueryRes(PageRes):
    items: list[ListInqueryItem] = []


class SyncItemsReq(BaseModel):
    pass


class SyncItemsImages(BaseModel):
    items_id_list: list[str] = []


class SyncInquiryHistoryReq(BaseModel):
    limit: int | None = Field(default=None, description="仅同步前 N 条，空值表示全量")
    batch_size: int = Field(default=500, ge=1, description="每批写入主库的记录数")


@sgo_router.post('/sgo/parts/sync', tags=["业务-SGO集成"], summary='同步一次所有的配件基本信息', responses={
    200: {
        'model': str
    }
})
async def sgo_parts_sync(_: SyncItemsReq):
    try:
        task = sgo_sync_task_manager.start("parts", SGOBiz.sync_parts_items)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SgoSyncTaskStartRes(
        message="配件基础信息同步任务已在后台启动",
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
        task = sgo_sync_task_manager.start(
            "images",
            SGOBiz.sync_images,
            item_id_list=req.items_id_list,
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
        task = sgo_sync_task_manager.start(
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
    task = sgo_sync_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"SGO 同步任务不存在: task_id={task_id}")
    return SgoSyncTaskStatusRes(**task)


@sgo_router.post('/sgo/inquery/list', tags=["业务-SGO集成"], summary='获取询码记录列表', responses={
    200: {
        'model': ListInqueryRes
    }
})
async def sgo_inquery_list(req: ListInqueryReq):
    if req.has_indexed not in (0, 1, 2):
        raise Exception('has_indexed只能为0,1或者2')

    inquery_list = await SGOBiz.list_inquery(req.page, req.per_page, req.current_status, req.has_indexed)
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
