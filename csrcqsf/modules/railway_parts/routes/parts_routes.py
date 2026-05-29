"""Routes for parts CRUD, image management, and segmentation entrypoints."""

from fastapi import File, Form, Request, UploadFile

from csrcqsf.modules.railway_parts.schemas.parts import (
    AutoSegmentReq,
    AutoSegmentRes,
    CreateItemImagesReq,
    CreateItemImagesRes,
    CreateItemReq,
    DeleteItemReq,
    GetItemDetailReq,
    GetItemDetailRes,
    IndexStatisticsReq,
    IndexStatisticsRes,
    ItemSuggestReq,
    ItemSuggestRes,
    LisItemRes,
    ListItemImageItem,
    ListItemImagesReq,
    ListItemImagesRes,
    ListItemReq,
    ListSegmentedImagesRes,
    SegmentedImageItem,
    UpdateItemReq,
    UpdateItemSizeStr,
)
from csrcqsf.biz.railwayparts.auto_processor import AutoPartProcessor
from csrcqsf.biz.sgo import SGOBiz
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.runtime import ensure_segment_model_enabled

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


@parts_router.post('/get_item_details',  tags=["业务-配件管理"], summary='获取配件的详细信息', responses={
    200: {
        'model': GetItemDetailRes
    }
})
async def get_item_image_detail(req: GetItemDetailReq):
    return await RailwayPartsManager.get_item_detail(int(req.item_id))


@parts_router.post('/data/statistics',  tags=["业务-数据统计"], summary='索引统计', responses={
    200: {
        'model': IndexStatisticsRes
    }
})
async def indexstatistics(req: IndexStatisticsReq):
    return await RailwayPartsManager.statistics()


@parts_router.post('/auto_segment', tags=["算法-图像分割"], deprecated=True,summary='自动分割并建立索引 (SAM + DINOv2)', responses={
    200: {'model': AutoSegmentRes}
})
async def auto_segment(req: AutoSegmentReq):
    """
    自动分割并建立高精度索引

    算法流程：
    1. 获取配件的 BASEINFO 类型图片
    2. 使用 SAM (Segment Anything Model) 自动分割出配件主体
    3. 分割后的图片上传到 MinIO
    4. 分割记录保存到数据库 (segmented_image_info 表)
    5. 使用 DINOv2 提取高精度特征（1024维向量）
    6. 建立 Milvus 向量索引

    参数：
    - item_id: 配件ID
    - rebuild: 是否重建已有索引

    业务逻辑：AutoPartProcessor.auto_segment_by_item_id() in biz/railwayparts/auto_processor.py
    核心算法：SAM分割 + DINOv2特征提取 + Milvus索引
    """
    ensure_segment_model_enabled()
    result = await AutoPartProcessor.auto_segment_by_item_id(
        item_id=int(req.item_id),
        rebuild=req.rebuild
    )

    return AutoSegmentRes(
        item_id=result.item_id,
        total_baseinfo_images=result.total_baseinfo_images,
        segmented_count=result.segmented_count,
        indexed_count=result.indexed_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        message=result.message
    )


@parts_router.get('/segmented_images/{item_id}', tags=["业务-图片管理"],deprecated=True, summary='获取配件的分割记录', responses={
    200: {'model': ListSegmentedImagesRes}
})
async def list_segmented_images(item_id: str):
    """获取配件的分割记录列表"""
    records = await AutoPartProcessor.list_segmented_images(int(item_id))

    return ListSegmentedImagesRes(
        item_id=item_id,
        records=[
            SegmentedImageItem(**rec) for rec in records
        ]
    )


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
