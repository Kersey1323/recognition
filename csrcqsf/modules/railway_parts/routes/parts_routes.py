"""配件维护、图片管理和分割入口路由。"""

from fastapi import File, Form, HTTPException, Request, UploadFile

from csrcqsf.modules.railway_parts.schemas.parts import (
    CreateItemImagesReq,
    CreateItemImagesRes,
    CreateItemReq,
    DeleteItemImageReq,
    DeleteItemImageRes,
    DeleteItemReq,
    GetItemDetailReq,
    GetItemDetailRes,
    HierarchyItemDetailReq,
    HierarchyItemDetailRes,
    IndexStatisticsReq,
    IndexStatisticsRes,
    ItemSuggestReq,
    ItemSuggestRes,
    LisItemRes,
    ListItemImageItem,
    ListItemImagesReq,
    ListItemImagesRes,
    ListItemReq,
    UpdateItemReq,
    UpdateItemSizeStr,
)
from csrcqsf.modules.sgo.services import SGOBiz
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.modules.railway_parts.services.search_hierarchy_service import enrich_search_items, get_hierarchy_item_detail as load_hierarchy_item_detail

from .router import parts_router


@parts_router.post('/item',  tags=["业务-配件管理"], summary='创建配件实体', responses={
    200: {
        'model': str
    }
})
async def create_item(req: CreateItemReq):
    """
    创建配件实体

    服务层职责：接收HTTP请求，验证参数，调用业务逻辑
    业务逻辑：RailwayPartsManager.create_item() in biz/railwayparts/parts.py
    """
    await RailwayPartsManager.create_item(item_name=req.item_name, item_code=req.item_code, obj_url=req.obj_url,
                                          height=req.height, length=req.length, width=req.width, weight=req.weight,
                                          parent_item_id=int(req.parent_item_id) if req.parent_item_id is not None else None)


@parts_router.post('/item_delete',  tags=["业务-配件管理"], summary='删除配件实体', responses={
    200: {
        'model': str
    }
})
async def delete_item(req: DeleteItemReq):
    """
    删除配件实体

    业务逻辑：RailwayPartsManager.delete_item() in biz/railwayparts/parts.py
    """
    item_id_list = [int(item_id) for item_id in (req.item_id_list)]
    await RailwayPartsManager.delete_item(item_id_list=item_id_list)


@parts_router.post('/item_put',  tags=["业务-配件管理"], summary='修改配件实体描述', responses={
    200: {
        'model': str
    }
})
async def put_item(req: UpdateItemReq):
    update_fields = set(req.__fields_set__)
    update_fields.discard("id")
    if "parent_item_id" in update_fields and req.parent_item_id is None:
        update_fields.remove("parent_item_id")

    await RailwayPartsManager.update_item(
        item_id=int(req.id),
        update_fields=update_fields,
        item_name=req.item_name,
        item_code=req.item_code,
        parent_item_id=int(req.parent_item_id) if req.parent_item_id is not None else None,
        length=req.length,
        width=req.width,
        height=req.height,
        weight=req.weight,
    )


@parts_router.post('/item/size_put',  tags=["业务-配件管理"], summary='修改配件3D模型的尺寸描述', responses={
    200: {
        'model': str
    }
})
async def put_item_size_desc(req: UpdateItemSizeStr):
    await RailwayPartsManager.update_item_size(item_id=int(req.item_id), item_size_str=req.item_size_desc)


@parts_router.post('/list_items',  tags=["业务-配件管理"], summary='列出配件列表', responses={
    200: {
        'model': LisItemRes
    }
})
async def list_items(req: ListItemReq):
    return await RailwayPartsManager.list_item(req)


@parts_router.post('/list_item_images', tags=["业务-图片管理"], summary='列出配件已保存图片', responses={
    200: {
        'model': ListItemImagesRes
    }
})
async def list_item_images(req: ListItemImagesReq):
    images = await SGOBiz.list_parts_sgo_image(item_id=int(req.item_id))
    res = ListItemImagesRes()
    for img in images:
        image = ListItemImageItem()
        image.image_id = str(img.id)
        image.has_indexed = img.is_indexed
        image.image_url = img.image_url
        image.image_source_type = img.image_source
        res.items.append(image)

    return res


@parts_router.post('/create_item_image',  tags=["业务-图片管理"], summary='为配件上传图片', responses={
    200: {
        'model': CreateItemImagesRes
    }
})
async def create_item_image(
    request: Request,
    item_id: str | None = Form(None),
    files: list[UploadFile] | None = File(None),
):
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        if item_id is None:
            raise Exception("item_id不能为空")
        result = await RailwayPartsManager.create_item_image_files(int(item_id), files or [])
        return CreateItemImagesRes(**result)

    payload = await request.json()
    req = CreateItemImagesReq(**payload)
    result = await RailwayPartsManager.create_item_image(int(req.item_id), image_url_list=req.images_url)
    return CreateItemImagesRes(**result)


@parts_router.post('/delete_item_image', tags=["业务-图片管理"], summary='删除配件指定图片', responses={
    200: {
        'model': DeleteItemImageRes
    }
})
async def delete_item_image(req: DeleteItemImageReq):
    result = await RailwayPartsManager.delete_item_image(
        item_id=int(req.item_id),
        image_id=int(req.image_id),
        delete_reason=req.delete_reason,
    )
    return DeleteItemImageRes(**result)


@parts_router.post('/get_item_details',  tags=["业务-配件管理"], summary='获取配件的详细信息', responses={
    200: {
        'model': GetItemDetailRes
    }
})
async def get_item_image_detail(req: GetItemDetailReq):
    detail = await RailwayPartsManager.get_item_detail(int(req.item_id))
    # 配件详情按当前业务库层级展示直接父子件，不按单一车型隐藏其他关联。
    await enrich_search_items([detail])
    return detail


@parts_router.post('/hierarchy/item/detail', tags=["业务-配件管理"], summary='按编码查询层级配件详情', response_model=HierarchyItemDetailRes, description='从已同步的层级关系读取节点名称、车型和直接父子配件；不要求该编码存在于 item_info。')
async def get_hierarchy_item_detail(req: HierarchyItemDetailReq):
    detail = await load_hierarchy_item_detail(req.item_code, vehicle_batch=req.vehicle_batch)
    if detail is None:
        raise HTTPException(status_code=404, detail='未找到该配件编码的有效层级关系')
    return detail


@parts_router.post('/data/statistics',  tags=["业务-数据统计"], summary='索引统计', responses={
    200: {
        'model': IndexStatisticsRes
    }
})
async def indexstatistics(req: IndexStatisticsReq):
    return await RailwayPartsManager.statistics()


@parts_router.post('/item/suggest', tags=["业务-配件管理"], summary='物料编码联想', responses={
    200: {
        'model': ItemSuggestRes
    }
}, description="""
请求体字段说明：

- `keyword`: 联想关键词，可输入物料编码或物料名称片段
- `limit`: 最多返回的联想条数
""")
async def suggest_items(req: ItemSuggestReq):
    return await RailwayPartsManager.suggest_items(req.keyword, limit=req.limit)
