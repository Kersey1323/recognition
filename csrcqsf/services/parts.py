from fastapi import APIRouter, BackgroundTasks
from csrcqsf.biz.railwayparts.api_models import *
from bfrcommon.snowflake import get_id
from bfrcommon.common import date_to_str
from csrcqsf.models.sgo import SgoItemImages
from csrcqsf.settings import ai_settings
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from csrcqsf.biz.railwayparts.milvus import MilvusManager
from anyio.to_thread import run_sync
parts_router = APIRouter(
    prefix="/railway/parts",
    tags=["railway"],
    # dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)


@parts_router.post('/item',  tags=["railway"], summary='创建配件实体', responses={
    200: {
        'model': str
    }
})
async def create_item(req: CreateItemReq):
    await RailwayPartsManager.create_item(item_name=req.item_name, item_code=req.item_code, obj_url=req.obj_url,
                                          height=req.height, length=req.length, width=req.width)


@parts_router.post('/item_delete',  tags=["railway"], summary='删除配件实体', responses={
    200: {
        'model': str
    }
})
async def delete_item(req: DeleteItemReq):
    item_id_list = [int(item_id) for item_id in (req.item_id_list)]
    await RailwayPartsManager.delete_item(item_id_list=item_id_list)


@parts_router.post('/item_put',  tags=["railway"], summary='修改配件实体描述', responses={
    200: {
        'model': str
    }
})
async def put_item(req: UpdateItemReq):
    await RailwayPartsManager.update_item(item_id=int(req.id), item_name=req.item_name, item_code=req.item_code,
                                          parent_item_id=int(req.parent_item_id), obj_url=req.obj_url, length=req.length,
                                          width=req.width, height=req.height)


@parts_router.post('/item/size_put',  tags=["railway"], summary='修改配件3D模型的尺寸描述', responses={
    200: {
        'model': str
    }
})
async def put_item_size_desc(req: UpdateItemSizeStr):
    await RailwayPartsManager.update_item_size(item_id=int(req.item_id), item_size_str=req.item_size_desc)


@parts_router.post('/list_items',  tags=["railway"], summary='列出配件列表', responses={
    200: {
        'model': LisItemRes
    }
})
async def list_items(req: ListItemReq):

    return await RailwayPartsManager.list_item(req)


@parts_router.post('/create_item_image',  tags=["railway"], summary='为配件上传图片', responses={
    200: {
        'model': str
    }
})
async def create_item_image(req: CreateItemImagesReq):
    await RailwayPartsManager.create_item_image(int(req.item_id), image_url_list=req.images_url)


@parts_router.post('/item_image_indexed',  tags=["railway"], summary='为配件建立索引,可以是原图，也可以是裁剪后的照片', responses={
    200: {
        'model': str
    }
})
async def create_item_image_index(req: CreateItemImagesIndexReq):
    await RailwayPartsManager.create_item_index(req)


@parts_router.post('/get_item_details',  tags=["railway"], summary='获取配件的详细信息', responses={
    200: {
        'model': GetItemDetailRes
    }
})
async def get_item_image_detail(req: GetItemDetailReq):
    return await RailwayPartsManager.get_item_detail(int(req.item_id))


@parts_router.post('/update_item_features',  tags=["railway"], summary='修改配件文字特征', responses={
    200: {
        'model': str
    }
})
async def update_item_features(req: UpdateFeatureReq):
    await RailwayPartsManager.update_item_features(req)


@parts_router.post('/delete_item_features',  tags=["railway"], summary='删除配件文字特征', responses={
    200: {
        'model': str
    }
})
async def delete_item_features(req: DeleteFeaturesReq):
    await RailwayPartsManager.delete_item_features(req)


@parts_router.post('/delete_item_image_index',  tags=["railway"], summary='删除配件图片索引', responses={
    200: {
        'model': str
    }
})
async def delete_item_image_index(req: DeleteImageIndexedReq):
    await RailwayPartsManager.delete_item_image_index(int(req.item_id), req.image_file_url)


@parts_router.post('/list_item_features',  tags=["railway"], summary='列出当前配件的features', responses={
    200: {
        'model': ListFeautresRes
    }
})
async def list_item_features(req: ListFeaturesReq):
    features = await MilvusManager.get_parts_feature_set(int(req.item_id))

    res = ListFeautresRes()
    for f in features:
        res.features.append(f)

    return res


@parts_router.post('/image_search',  tags=["railway"], summary='根据图片查询配件', responses={
    200: {
        'model': ImageSearchRes
    }
})
async def item_search(req: ImageSearchReq):
    return await RailwayPartsManager.image_search_to_item(req.images_url, req.radius)


@parts_router.post('/index_rebuild',  tags=["railway"], summary='重建所有配件的图片索引', responses={
    200: {
        'model': str
    }
})
async def rebuild_parts_pic_index():
    return await RailwayPartsManager.rebuild_pic_index()


class SearchReq(BaseModel):
    images: list[str] = []
    features: list[str] = []
    lower_rate: float = 0.8
    sgo_inquery_id: str | None
    parent_item_id: str | None = '0'





@parts_router.post('/search/v2',  tags=["railway"], summary='检索V2版本', responses={
    200: {
        'model': SearchRes
    }
})
async def search_v2(req: SearchReq):
    return await RailwayPartsManager.search(req.images, req.features, lower_rate=req.lower_rate,
                                            sgo_inquery_id=req.sgo_inquery_id, parent_item_id=int(req.parent_item_id))


@parts_router.post('/search/history/v2',  tags=["railway"], summary='检索历史列表', responses={
    200: {
        'model': ListSearchHistoryRes
    }
})
async def list_search_history_v2(req: ListSearchHistoryReq):
    return await RailwayPartsManager.list_search_history(req.page, req.per_page)


@parts_router.post('/search/history/delete/v2',  tags=["railway"], summary='删除检索历史', responses={
    200: {
        'model': ListSearchHistoryRes
    }
})
async def delete_search_history_v2(req: DeleteSearchHistoryReq):
    await RailwayPartsManager.delete_history([int(id) for id in req.history_id_list])


@parts_router.post('/data/statistics',  tags=["railway"], summary='索引统计', responses={
    200: {
        'model': IndexStatisticsRes
    }
})
async def indexstatistics(req: IndexStatisticsReq):
    return await RailwayPartsManager.statistics()


# ===== 自动分割建立索引接口 =====

from csrcqsf.biz.railwayparts.auto_processor import AutoPartProcessor


@parts_router.post('/auto_segment', tags=["railway"], summary='自动分割并建立索引 (SAM + DINOv2)', responses={
    200: {'model': AutoSegmentRes}
})
async def auto_segment(req: AutoSegmentReq):
    """根据配件ID自动分割并建立高精度索引
    
    1. 自动获取配件的 BASEINFO 类型图片
    2. SAM 自动分割出配件主体
    3. 分割后的图片上传到 MinIO
    4. 分割记录保存到数据库 (segmented_image_info 表)
    5. DINOv2 提取高精度特征并建立 Milvus 索引
    """
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


@parts_router.get('/segmented_images/{item_id}', tags=["railway"], summary='获取配件的分割记录', responses={
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


# ===== 3D 重建接口 =====

from csrcqsf.biz.reconstruction import ReconstructionPipeline


@parts_router.post('/reconstruct_3d', tags=["railway"], summary='3D重建 (多角度照片→OBJ)', responses={
    200: {'model': Reconstruct3DTaskRes}
})
async def reconstruct_3d(req: Reconstruct3DReq):
    """从多角度照片重建 3D 模型
    
    流程:
    1. COLMAP 相机位姿估计
    2. 3D Gaussian Splatting 训练
    3. SuGaR Mesh 提取
    4. 导出 OBJ 文件
    
    由于处理时间较长 (15-30分钟)，采用后台任务方式，
    返回 task_id 后可通过 /reconstruct_3d/progress 查询进度
    """
    if len(req.image_urls) < 10:
        return Reconstruct3DTaskRes(
            task_id='',
            item_id=req.item_id,
            status='failed',
            message='图片数量不足，至少需要 10 张多角度照片'
        )
    
    task = await ReconstructionPipeline.create_task(
        item_id=int(req.item_id),
        image_urls=req.image_urls
    )
    
    return Reconstruct3DTaskRes(
        task_id=task.task_id,
        item_id=req.item_id,
        status=task.status.value,
        progress=task.progress,
        message='3D 重建任务已创建，请使用 task_id 查询进度'
    )


@parts_router.get('/reconstruct_3d/progress/{task_id}', tags=["railway"], summary='查询3D重建进度', responses={
    200: {'model': TaskProgressRes}
})
async def get_reconstruct_progress(task_id: str):
    """查询 3D 重建任务进度"""
    task = ReconstructionPipeline.get_task(task_id)
    
    if task is None:
        return TaskProgressRes(
            task_id=task_id,
            status='not_found',
            message='任务不存在'
        )
    
    return TaskProgressRes(
        task_id=task.task_id,
        item_id=str(task.item_id),
        status=task.status.value,
        progress=task.progress,
        message=task.message,
        total_images=task.total_images,
        downloaded_images=task.downloaded_images,
        colmap_points=task.colmap_points,
        mesh_vertices=task.mesh_vertices,
        mesh_faces=task.mesh_faces,
        obj_url=task.obj_url,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error
    )


@parts_router.get('/reconstruct_3d/tasks', tags=["railway"], summary='列出3D重建任务')
async def list_reconstruct_tasks(item_id: str = None):
    """列出所有 3D 重建任务"""
    tasks = ReconstructionPipeline.list_tasks(
        item_id=int(item_id) if item_id else None
    )
    
    return [
        TaskProgressRes(
            task_id=t.task_id,
            item_id=str(t.item_id),
            status=t.status.value,
            progress=t.progress,
            message=t.message,
            obj_url=t.obj_url,
            created_at=t.created_at
        ) for t in tasks
    ]
