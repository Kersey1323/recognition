from fastapi import APIRouter
from pydantic import BaseModel, Field

from bfrcommon.api_models import PageReq, PageRes
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.modules.sgo.repositories import SgoItemImages
from csrcqsf.modules.sgo.services import SGOBiz
from csrcqsf.modules.sgo.schemas import ListInqueryItem

import json


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


@sgo_router.post('/sgo/parts/sync', tags=["业务-SGO集成"], summary='同步一次所有的配件基本信息', responses={
    200: {
        'model': str
    }
})
async def sgo_parts_sync(_: SyncItemsReq):
    await SGOBiz.sync_parts_items()


@sgo_router.post('/sgo/parts/images/sync', tags=["业务-SGO集成"], summary='同步选中的配件的照片', responses={
    200: {
        'model': str
    }
})
async def sgo_parts_image_sync(req: SyncItemsImages):
    await SGOBiz.sync_images(req.items_id_list)


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
        if data.nameplate_photos:
            file_describe = json.loads(data.nameplate_photos)
            for file_item in file_describe:
                url_array = str(file_item['url']).split("_")
                if len(url_array) < 2:
                    continue
                raw_url_list.append(url_array[1])
        if data.detailed_photos:
            file_describe = json.loads(data.detailed_photos)
            for file_item in file_describe:
                url_array = str(file_item['url']).split("_")
                if len(url_array) < 2:
                    continue
                raw_url_list.append(url_array[1])

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

        if data.nameplate_photos:
            file_describe = json.loads(data.nameplate_photos)
            for file_item in file_describe:
                url_array = str(file_item['url']).split("_")
                if len(url_array) < 2:
                    continue
                url = url_array[1]
                if url in sgo_image_dict:
                    item.nameplate_photos_urls.append(sgo_image_dict[url].image_url)

        if data.detailed_photos:
            file_describe = json.loads(data.detailed_photos)
            for file_item in file_describe:
                url_array = str(file_item['url']).split("_")
                if len(url_array) < 2:
                    continue
                url = url_array[1]
                if url in sgo_image_dict:
                    item.detailed_photos_urls.append(sgo_image_dict[url].image_url)

        res.items.append(item)

    return res
