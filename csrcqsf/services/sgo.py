from fastapi import APIRouter, BackgroundTasks
from csrcqsf.api_models import FrontOCRReq
from csrcqsf.biz.railwayparts.api_models import *
from bfrcommon.snowflake import get_id
from bfrcommon.common import date_to_str
from csrcqsf.settings import ai_settings
from csrcqsf.biz.segment import SegmentBiz
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from csrcqsf.biz.sgo import SGOBiz
from csrcqsf.models.sgo import ImageSourceType, ListInqueryItem
from bfrcommon.api_models import PageReq, PageRes
from csrcqsf.models.sgo import SgoItemImages
from csrcqsf.data.pg import SessionLocal
import json
sgo_router = APIRouter(
    prefix="/sgo",
    tags=["sgo"],
    # dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)


class ListInqueryReq(PageReq):
    has_indexed: int = Field(default=1, description='1. 做过索引了 2. 没做过索引 0 不要这个条件')
    current_status: str = Field(
        default='FINISH', description='询码的状态.FINISH 已结束 CREATE:技术部待回复 CONFIRMAUDIT:编码确认审核中 BACKAUDIT:驳回审核中 REGING:编码注册中')





class ListInqueryRes(PageRes):
    items: list[ListInqueryItem] = []


class SyncItemsReq(BaseModel):
    pass


class SyncItemsImages(BaseModel):
    items_id_list: list[str] = []


class ListSgoItemImagesReq(BaseModel):
    item_id: str


class ListSgoItemImageItem(BaseModel):
    image_id: str = ''
    has_indexed: int = Field(default=0, description='是否已经加入配件的索引库，1为已索引 2为未索引')
    image_url: str = ''
    image_source_type: ImageSourceType | None = Field(
        description='来着sgo系统的图片来源,分别为询码记录和基本信息')


class ListSgoItemImageRes(BaseModel):
    items: list[ListSgoItemImageItem] = []


@sgo_router.post('/sgo/parts/sync',  tags=["sgo"], summary='同步一次所有的配件基本信息', responses={
    200: {
        'model': str
    }
})
async def sgo_parts_sync(_: SyncItemsReq):
    await SGOBiz.sync_parts_items()


@sgo_router.post('/sgo/parts/images/sync',  tags=["sgo"], summary='同步选中的配件的照片', responses={
    200: {
        'model': str
    }
})
async def sgo_parts_image_sync(req: SyncItemsImages):
    # return await SGOBiz.sync_parts_items()
    await SGOBiz.sync_images(req.items_id_list)


@sgo_router.post('/sgo/parts/images',  tags=["sgo"], summary='根据配件id获取sgo系统里的图片', responses={
    200: {
        'model': ListSgoItemImageRes
    }
})
async def sgo_parts_image_list(req: ListSgoItemImagesReq):
    images = await SGOBiz.list_parts_sgo_image(item_id=int(req.item_id))
    res = ListSgoItemImageRes()
    for img in images:
        image = ListSgoItemImageItem()
        image.image_id = str(img.id)
        image.has_indexed = img.is_indexed
        image.image_url = img.image_url
        image.image_source_type = img.image_source
        res.items.append(image)

    return res


@sgo_router.post('/sgo/inquery/list',  tags=["sgo"], summary='获取询码记录列表', responses={
    200: {
        'model': ListInqueryRes
    }
})
async def sgo_inquery_list(req: ListInqueryReq):
    if req.has_indexed != 1 and req.has_indexed != 2 and req.has_indexed != 0:
        raise Exception(f'has_indexed只能为0,1或者2')
    inquery_list = await SGOBiz.list_inquery(req.page, req.per_page, req.current_status, req.has_indexed)
    res = ListInqueryRes(
        total=inquery_list.total
    )
    raw_url_list: list[str] = []
    for data in inquery_list.data:
        if data.nameplate_photos is not None and data.nameplate_photos != '':
            file_describe = json.loads(data.nameplate_photos)
            for f in file_describe:
                url_array = str(f['url']).split("_")
                if len(url_array) < 2:
                    continue
                url = url_array[1]
                raw_url_list.append(url)
        if data.detailed_photos is not None and data.detailed_photos != '':
            file_describe = json.loads(data.detailed_photos)
            for f in file_describe:
                url_array = str(f['url']).split("_")
                if len(url_array) < 2:
                    continue
                url = url_array[1]
                raw_url_list.append(url)
    sgo_image_dict: dict[str, SgoItemImages] = {}
    if len(raw_url_list) > 0:
        async with SessionLocal() as session:
            sgoImages = await SgoItemImages.list_item_images_by_raw_url(session, raw_url_list)
            for image in sgoImages:
                sgo_image_dict[image.raw_url] = image

    for data in inquery_list.data:
        item = ListInqueryItem(
            id=data.id
        )
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
        if data.nameplate_photos is not None and data.nameplate_photos != '':
            file_describe = json.loads(data.nameplate_photos)
            for f in file_describe:
                url_array = str(f['url']).split("_")
                if len(url_array) < 2:
                    continue
                url = url_array[1]
                if url in sgo_image_dict:
                    item.nameplate_photos_urls.append(
                        sgo_image_dict[url].image_url)
        if data.detailed_photos is not None and data.detailed_photos != '':
            file_describe = json.loads(data.detailed_photos)
            for f in file_describe:
                url_array = str(f['url']).split("_")
                if len(url_array) < 2:
                    continue
                url = url_array[1]
                if url in sgo_image_dict:
                    item.detailed_photos_urls.append(
                        sgo_image_dict[url].image_url)
        res.items.append(item)

    return res
