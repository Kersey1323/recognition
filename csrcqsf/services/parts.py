"""
服务层 - 配件管理API路由
职责：定义API接口、参数验证、调用业务逻辑
注意：此层不包含具体业务实现，仅负责路由和参数处理
"""
from fastapi import APIRouter, BackgroundTasks, UploadFile, File
from csrcqsf.biz.railwayparts.api_models import *
from bfrcommon.snowflake import get_id
from bfrcommon.common import date_to_str
from csrcqsf.models.sgo import SgoItemImages
from csrcqsf.settings import ai_settings
# 导入业务逻辑层
from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
from csrcqsf.biz.railwayparts.milvus import MilvusManager
from anyio.to_thread import run_sync

# 配件管理路由器
parts_router = APIRouter(
    prefix="/railway/parts",
    tags=["railway"],
    # dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)



# ============================================
# 配件基础管理接口
# ============================================

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
                                          height=req.height, length=req.length, width=req.width)


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
    await RailwayPartsManager.update_item(item_id=int(req.id), item_name=req.item_name, item_code=req.item_code,
                                          parent_item_id=int(req.parent_item_id), obj_url=req.obj_url, length=req.length,
                                          width=req.width, height=req.height)


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


@parts_router.post('/create_item_image',  tags=["业务-图片管理"], summary='为配件上传图片', responses={
    200: {
        'model': str
    }
})
async def create_item_image(req: CreateItemImagesReq):
    await RailwayPartsManager.create_item_image(int(req.item_id), image_url_list=req.images_url)


@parts_router.post('/item_image_indexed',  tags=["算法-特征索引"], summary='为配件建立索引,可以是原图，也可以是裁剪后的照片', responses={
    200: {
        'model': str
    }
})
async def create_item_image_index(req: CreateItemImagesIndexReq):
    await RailwayPartsManager.create_item_index(req)


@parts_router.post('/get_item_details',  tags=["业务-配件管理"], summary='获取配件的详细信息', responses={
    200: {
        'model': GetItemDetailRes
    }
})
async def get_item_image_detail(req: GetItemDetailReq):
    return await RailwayPartsManager.get_item_detail(int(req.item_id))


@parts_router.post('/update_item_features',  tags=["业务-特征管理"], summary='修改配件文字特征', responses={
    200: {
        'model': str
    }
})
async def update_item_features(req: UpdateFeatureReq):
    await RailwayPartsManager.update_item_features(req)


@parts_router.post('/delete_item_features',  tags=["业务-特征管理"], summary='删除配件文字特征', responses={
    200: {
        'model': str
    }
})
async def delete_item_features(req: DeleteFeaturesReq):
    await RailwayPartsManager.delete_item_features(req)


@parts_router.post('/delete_item_image_index',  tags=["业务-图片管理"], summary='删除配件图片索引', responses={
    200: {
        'model': str
    }
})
async def delete_item_image_index(req: DeleteImageIndexedReq):
    await RailwayPartsManager.delete_item_image_index(int(req.item_id), req.image_file_url)


@parts_router.post('/list_item_features',  tags=["业务-特征管理"], summary='列出当前配件的features', responses={
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


@parts_router.post('/image_search',  tags=["算法-智能检索"], summary='根据图片查询配件', responses={
    200: {
        'model': ImageSearchRes
    }
})
async def item_search(req: ImageSearchReq):
    return await RailwayPartsManager.image_search_to_item(req.images_url, req.radius)



# ============================================
# 算法接口 - 特征索引
# ============================================

@parts_router.post('/index_rebuild',  tags=["算法-特征索引"], summary='重建所有配件的图片索引', responses={
    200: {
        'model': str
    }
})
async def rebuild_parts_pic_index():
    """
    重建所有配件的图片索引
    
    算法流程：
    1. 标记所有图片为未索引状态
    2. 获取所有图片
    3. 使用DINOv2提取特征并重建Milvus向量索引
    4. 标记所有图片为已索引状态
    
    业务逻辑：RailwayPartsManager.rebuild_pic_index() in biz/railwayparts/parts.py:529
    核心算法：MilvusManager.rebuild_collection() - DINOv2特征提取 + Milvus索引
    """
    return await RailwayPartsManager.rebuild_pic_index()


class SearchReq(BaseModel):
    images: list[str] = []
    features: list[str] = []
    lower_rate: float = 0.8
    sgo_inquery_id: str | None
    parent_item_id: str | None = '0'





@parts_router.post('/search/v2',  tags=["算法-智能检索"], summary='检索V2版本', responses={
    200: {
        'model': SearchRes
    }
})
async def search_v2(req: SearchReq):
    return await RailwayPartsManager.search(req.images, req.features, lower_rate=req.lower_rate,
                                            sgo_inquery_id=req.sgo_inquery_id, parent_item_id=int(req.parent_item_id))


@parts_router.post('/search/history/v2',  tags=["业务-检索历史"], summary='检索历史列表', responses={
    200: {
        'model': ListSearchHistoryRes
    }
})
async def list_search_history_v2(req: ListSearchHistoryReq):
    return await RailwayPartsManager.list_search_history(req.page, req.per_page)


@parts_router.post('/search/history/delete/v2',  tags=["业务-检索历史"], summary='删除检索历史', responses={
    200: {
        'model': ListSearchHistoryRes
    }
})
async def delete_search_history_v2(req: DeleteSearchHistoryReq):
    await RailwayPartsManager.delete_history([int(id) for id in req.history_id_list])


@parts_router.post('/data/statistics',  tags=["业务-数据统计"], summary='索引统计', responses={
    200: {
        'model': IndexStatisticsRes
    }
})
async def indexstatistics(req: IndexStatisticsReq):
    return await RailwayPartsManager.statistics()


# ===== 自动分割建立索引接口 =====

from csrcqsf.biz.railwayparts.auto_processor import AutoPartProcessor



# ============================================
# 算法接口 - 图像分割
# ============================================

@parts_router.post('/auto_segment', tags=["算法-图像分割"], summary='自动分割并建立索引 (SAM + DINOv2)', responses={
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


@parts_router.get('/segmented_images/{item_id}', tags=["业务-图片管理"], summary='获取配件的分割记录', responses={
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


@parts_router.post('/reconstruct_3d', tags=["算法-3D重建"], summary='3D重建 (多角度照片→OBJ)', responses={
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


@parts_router.get('/reconstruct_3d/progress/{task_id}', tags=["业务-任务管理"], summary='查询3D重建进度', responses={
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


@parts_router.get('/reconstruct_3d/tasks', tags=["业务-任务管理"], summary='列出3D重建任务')
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



# ============================================
# 新向量数据库接口 (SigLIP + DINOv2)
# ============================================

@parts_router.post('/v2/collections/init', tags=["算法-向量检索V2"], summary='初始化V2向量数据库并建立索引')
async def init_v2_collections(
    limit: int = None,
    drop_existing: bool = False,
    background_tasks: BackgroundTasks = None
):
    """
    初始化新的向量数据库集合 (SigLIP + DINOv2) 并建立索引
    
    创建两个集合：
    - PARTS_SIGLIP_SO400M_1152D_V1: SigLIP 图文特征 (1152维)
    - PARTS_DINOV2_LARGE_1024D_V1: DINOv2 视觉特征 (1024维)
    
    参数：
    - limit: 限制处理数量（可选，用于测试，如 limit=10 只处理10条数据）
    - drop_existing: 是否删除已存在的集合（默认 False，保留现有数据）
    - background_tasks: 后台任务（自动传入）
    
    注意：
    - 如果集合已存在且 drop_existing=False，将跳过创建直接建索引
    - 如果 limit 较大或为空，将在后台执行建库任务
    - drop_existing=True 会清空所有现有数据，请谨慎使用！
    """
    # 创建集合（如果不存在）
    await RailwayPartsManager.create_v2_collections(drop_existing=drop_existing)
    
    # 如果指定了 limit，则同时建立索引
    if limit is not None:
        if limit > 100 and background_tasks:
            # 大批量任务放到后台执行
            background_tasks.add_task(
                RailwayPartsManager.rebuild_v2_index,
                item_id=None,
                limit=limit
            )
            return {
                'message': f'V2 collections initialized, building index for {limit} items in background',
                'drop_existing': drop_existing
            }
        else:
            # 小批量任务直接执行
            result = await RailwayPartsManager.rebuild_v2_index(
                item_id=None,
                limit=limit
            )
            return {
                'message': f'V2 collections initialized and index built for {limit} items',
                'drop_existing': drop_existing,
                'result': result
            }
    
    return {
        'message': 'V2 collections initialized successfully (no indexing performed)',
        'drop_existing': drop_existing
    }


@parts_router.post('/v2/search/text', tags=["算法-向量检索V2"], summary='V2文本检索')
async def search_v2_by_text(
    query_text: str,
    top_k: int = 10,
    # use_image_vector: bool = False
):
    """
    使用新算法进行文本检索
    
    参数：
    - query_text: 查询文本（如"制动盘"）
    - top_k: 返回结果数量
    - use_image_vector: 是否使用 image_vector 字段（可选）
        - False（默认）: 使用 text_vector 字段进行文本匹配
        - True: 使用 image_vector 字段进行图像内容语义匹配
    
    算法：
    - 使用 SigLIP 提取文本特征
    - 在 PARTS_SIGLIP_SO400M_1152D_V1 集合中检索
    - 返回最相似的配件
    """
    result = await RailwayPartsManager.search_v2_by_text(
        query_text=query_text,
        top_k=top_k
        # use_image_vector=use_image_vector
    )
    return result


@parts_router.post('/v2/search/image', tags=["算法-向量检索V2"], summary='V2图像检索')
async def search_v2_by_image(
    file: UploadFile = File(...),
    top_k: int = 10,
    search_mode: str = "hybrid"
):
    """
    使用新算法进行图像检索（上传图片文件）
    
    参数：
    - file: 上传的图片文件（支持 jpg, png, jpeg 等格式）
    - top_k: 返回结果数量
    - search_mode: 检索模式
        - "siglip": SigLIP 模式 - 使用 image_vector 字段，简单快速
        - "dinov2": DINOv2 两阶段检索 - global_vector 粗排 + patch_tokens 精排
        - "hybrid": 混合检索（推荐）- RRF 融合 + Patch Token 精排
    
    算法流程（hybrid模式）：
    1. 粗排：SigLIP + DINOv2 全局特征 RRF 融合
    2. 精排：DINOv2 Patch Token 细粒度匹配
    3. 加权融合：alpha * RRF分数 + (1-alpha) * Patch分数
    
    注意：
    - siglip 模式：默认使用 text_vector 进行文本匹配，image_vector 是可选字段
    - dinov2 模式：两阶段检索，适合需要精确匹配视觉细节的场景
    - hybrid 模式：推荐使用，融合两个模型的优势
    """
    result = await RailwayPartsManager.search_v2_by_image(
        file=file,
        top_k=top_k,
        search_mode=search_mode
    )
    return result


@parts_router.get('/v2/search/modes', tags=["算法-向量检索V2"], summary='获取V2检索模式说明')
async def get_v2_search_modes():
    """
    获取 V2 检索模式说明
    
    返回各种检索模式的详细说明和适用场景
    """
    return {
        'modes': [
            {
                'name': 'siglip',
                'description': 'SigLIP 图像检索',
                'features': [
                    '使用 image_vector 字段',
                    '图文共享空间，1152维特征',
                    '简单快速'
                ],
                'use_case': '快速图像检索，对精度要求不高的场景',
                'speed': '快',
                'accuracy': '中',
                'note': 'image_vector 是可选字段，默认为 text_vector 匹配'
            },
            {
                'name': 'dinov2',
                'description': 'DINOv2 两阶段检索',
                'features': [
                    'global_vector (1024D) 粗排',
                    'patch_tokens (1369×1024) 精排',
                    '细粒度局部特征匹配'
                ],
                'use_case': '需要精确匹配视觉细节的场景，识别微小规格差异',
                'speed': '慢',
                'accuracy': '高'
            },
            {
                'name': 'hybrid',
                'description': '混合检索（推荐）',
                'features': [
                    'RRF 融合 SigLIP + DINOv2',
                    'Patch Token 精排',
                    '多模型互补，鲁棒性强'
                ],
                'use_case': '生产环境推荐，工业配件精确检索',
                'speed': '中',
                'accuracy': '最高'
            }
        ],
        'recommendation': 'hybrid 模式在准确率和速度之间取得最佳平衡，推荐用于生产环境',
        'text_search_note': '文本检索默认使用 text_vector 字段，可选 use_image_vector=true 使用 image_vector 字段'
    }
