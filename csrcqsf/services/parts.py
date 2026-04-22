"""
服务层 - 配件管理API路由
职责：定义API接口、参数验证、调用业务逻辑
注意：此层不包含具体业务实现，仅负责路由和参数处理
"""
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form
from csrcqsf.biz.railwayparts.api_models import *
from bfrcommon.snowflake import get_id
from bfrcommon.common import date_to_str
from csrcqsf.models.sgo import SgoItemImages
from csrcqsf.models.reconstruction import ReconstructionRecord
from csrcqsf.data.pg import SessionLocal
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
                                          height=req.height, length=req.length, width=req.width, weight=req.weight)


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
                                          width=req.width, height=req.height, weight=req.weight)


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
# 算法接口 - 特征索引（已废弃，使用 /v2/index/rebuild）
# ============================================

# 旧的 index_rebuild 接口已删除，请使用 /v2/index/rebuild


# ============================================
# 算法接口 - 智能检索（已废弃，使用 /v2/search/*）
# ============================================

# 旧的 search/v2 接口已删除，请使用：
# - /v2/search/text - 文本检索
# - /v2/search/image - 图像检索


# ============================================
# 业务接口 - 数据统计
# ============================================

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


# ===== 新的3D重建接口 (Celery + Redis) =====

from csrcqsf.biz.railwayparts.reconstruction_manager import ReconstructionManager
from csrcqsf.biz.railwayparts.reconstruction_api_models import (
    ReconstructionTrainReq,
    ReconstructionVideoReq,
    ReconstructionTaskRes,
    ReconstructionStatusRes,
    ReconstructionListRes,
    ReconstructionSourceVideoRes,
    ReconstructionSourceVideoListRes,
    ReconstructionSourceVideoMessageRes,
    ReconstructionAllTasksRes,
    ReconstructionIndexRebuildRes,
)


@parts_router.post('/v2/reconstruct/train', tags=["算法-3D重建V2"], summary='V2: 从已有场景数据训练')
async def reconstruct_v2_train(req: ReconstructionTrainReq):
    """
    从已有场景数据直接训练（快速）
    
    前提：场景数据已在 reconstruction_server/data/{scene}/ 中
    
    参数：
    - item_id: 配件ID
    - scene: 场景名称（data目录下的文件夹名）
    - iterations: 训练迭代次数（默认30000）
    - output_name: 输出名称（可选）
    
    返回：
    - task_id: 任务ID，用于查询进度
    """
    result = await ReconstructionManager.submit_train_task(
        item_id=int(req.item_id),
        scene=req.scene,
        iterations=req.iterations,
        output_name=req.output_name
    )
    
    return ReconstructionTaskRes(**result)


@parts_router.post('/v2/reconstruct/video', tags=["算法-3D重建V2"], summary='V2: 新增三维重构原始视频')
async def upload_reconstruct_v2_video(
    item_id: str = Form(...),
    height: float | None = Form(None),
    length: float | None = Form(None),
    width: float | None = Form(None),
    weight: float | None = Form(None),
    file: UploadFile = File(...)
):
    """
    上传三维重构原始视频到独立 MinIO bucket。
    
    返回的 `video_path` 可以直接作为 `/v2/reconstruct/tasks/video` 的 `video_path` 参数。
    """
    result = await ReconstructionManager.upload_source_video(
        item_id=int(item_id),
        height=height,
        length=length,
        width=width,
        weight=weight,
        file=file
    )
    return ReconstructionSourceVideoRes(**result)


@parts_router.get('/v2/reconstruct/video', tags=["算法-3D重建V2"], summary='V2: 分页列出三维重构原始视频')
async def list_reconstruct_v2_source_videos(
    limit: int = 100,
    offset: int = 0,
):
    result = await ReconstructionManager.list_source_videos(
        limit=limit,
        offset=offset,
    )
    return ReconstructionSourceVideoListRes(**result)


@parts_router.get('/v2/reconstruct/video/{item_id}', tags=["算法-3D重建V2"], summary='V2: 查询配件三维重构原始视频')
async def get_reconstruct_v2_source_video(item_id: str):
    result = await ReconstructionManager.get_source_video(int(item_id))
    return ReconstructionSourceVideoRes(**result)


@parts_router.put('/v2/reconstruct/video/{item_id}', tags=["算法-3D重建V2"], summary='V2: 更新或替换三维重构原始视频')
async def update_reconstruct_v2_source_video(
    item_id: str,
    height: float | None = Form(None),
    length: float | None = Form(None),
    width: float | None = Form(None),
    weight: float | None = Form(None),
    file: UploadFile | None = File(None),
):
    result = await ReconstructionManager.update_source_video(
        item_id=int(item_id),
        file=file,
        height=height,
        length=length,
        width=width,
        weight=weight,
    )
    return ReconstructionSourceVideoRes(**result)


@parts_router.delete('/v2/reconstruct/video/{item_id}', tags=["算法-3D重建V2"], summary='V2: 删除三维重构原始视频')
async def delete_reconstruct_v2_source_video(item_id: str):
    result = await ReconstructionManager.delete_source_video(int(item_id))
    return ReconstructionSourceVideoMessageRes(**result)


@parts_router.post('/v2/reconstruct/tasks/video', tags=["算法-3D重建V2"], summary='V2: 从视频完整重建')
async def reconstruct_v2_video(req: ReconstructionVideoReq):
    """
    完整视频重建流程
    
    流程：视频 → 提帧 → 去模糊去重 → COLMAP → SAM3分割 → 3DGS训练
    
    参数：
    - item_id: 配件ID
    - video_path: 视频文件路径（服务器本地绝对路径，或 MinIO 对象路径，如 bfr-3d-videos/raw-videos/...mp4）
    - name: 场景名称
    - iterations: 训练迭代次数
    - sam3_model: SAM3模型路径，为空则跳过分割
    - skip_*: 跳过已完成的步骤（断点续跑）
    
    返回：
    - task_id: 任务ID，用于查询进度
    """
    result = await ReconstructionManager.submit_video_task(
        item_id=int(req.item_id),
        video_path=req.video_path,
        name=req.name,
        iterations=req.iterations,
        fps=req.fps,
        image_size=req.image_size,
        blur_threshold=req.blur_threshold,
        dedup_threshold=req.dedup_threshold,
        min_frames=req.min_frames,
        sam3_model=req.sam3_model,
        text_prompt=req.text_prompt,
        mask_dilate=req.mask_dilate,
        camera=req.camera,
        no_gpu=req.no_gpu,
        skip_extract=req.skip_extract,
        skip_filter=req.skip_filter,
        skip_colmap=req.skip_colmap,
        skip_sam3=req.skip_sam3,
        output_name=req.output_name
    )
    
    return ReconstructionTaskRes(**result)


@parts_router.get('/v2/reconstruct/status/{task_id}', tags=["算法-3D重建V2"], summary='V2: 查询任务状态')
async def get_reconstruct_v2_status(task_id: str):
    """
    查询重建任务状态
    
    返回：
    - status: 任务状态 (pending/training/success/failed等)
    - progress: 进度百分比 (0-100)
    - current_stage: 当前阶段描述
    - result: 结果文件URL（完成后）
    """
    result = await ReconstructionManager.get_task_status(task_id)
    return ReconstructionStatusRes(**result)


@parts_router.get('/v2/reconstruct/item/{item_id}', tags=["算法-3D重建V2"], summary='V2: 列出配件的重建任务')
async def list_item_reconstruct_tasks(item_id: str):
    """
    列出指定配件的所有重建任务
    
    返回任务列表，按创建时间倒序排列
    """
    records = await ReconstructionManager.list_item_tasks(int(item_id))
    return ReconstructionListRes(records=records)


@parts_router.get('/v2/reconstruct/tasks', tags=["算法-3D重建V2"], summary='V2: 列出所有重建任务')
async def list_all_reconstruct_tasks(
    status: str = None,
    limit: int = 100,
    offset: int = 0
):
    """
    列出所有重建任务（支持分页和状态筛选）
    
    参数：
    - status: 任务状态筛选（可选）
        - pending: 等待中
        - extracting: 提帧中
        - filtering: 帧筛选中
        - colmap: COLMAP处理中
        - sam3: SAM3分割中
        - training: 训练中
        - converting: 转换中
        - success: 成功
        - failed: 失败
        - cancelled: 已取消
    - limit: 每页数量（默认100）
    - offset: 偏移量（默认0）
    
    返回：
    - total: 总任务数
    - limit: 每页数量
    - offset: 偏移量
    - records: 任务列表
    """
    result = await ReconstructionManager.list_all_tasks(
        status=status,
        limit=limit,
        offset=offset
    )
    return ReconstructionAllTasksRes(**result)


@parts_router.delete('/v2/reconstruct/cancel/{task_id}', tags=["算法-3D重建V2"], summary='V2: 取消任务')
async def cancel_reconstruct_task(task_id: str):
    """取消正在执行的重建任务"""
    return await ReconstructionManager.cancel_task(task_id)


@parts_router.get('/v2/reconstruct/scenes', tags=["算法-3D重建V2"], summary='V2: 列出可用场景')
async def list_reconstruction_scenes():
    """
    列出 reconstruction_server/data/ 目录下所有可用场景
    
    返回已准备好 COLMAP 数据的场景，可直接用于训练
    """
    scenes = ReconstructionManager.list_scenes()
    return {"scenes": scenes}



# ============================================
# 新向量数据库接口 (SigLIP + DINOv2)
# ============================================

@parts_router.post('/v2/collections/drop', tags=["算法-向量检索V2"], summary='清空V2向量数据库')
async def drop_v2_collections():
    """
    清空向量数据库（删除所有集合）
    
    警告：此操作会删除以下集合的所有数据：
    - PARTS_SIGLIP_SO400M_1152D_V1: SigLIP 图文特征
    - PARTS_DINOV2_LARGE_1024D_V1: DINOv2 视觉特征
    
    删除后需要重新调用 /v2/collections/init 创建集合
    """
    from csrcqsf.biz.railwayparts.vector_db.storage.milvus_manager import MilvusManagerV2
    
    manager = MilvusManagerV2()
    await run_sync(manager.drop_collections)
    
    return {
        'message': 'V2 collections dropped successfully',
        'warning': 'All vector data has been deleted. Please call /v2/collections/init to recreate collections.'
    }


@parts_router.post('/v2/collections/init', tags=["算法-向量检索V2"], summary='初始化V2向量数据库集合')
async def init_v2_collections():
    """
    初始化新的向量数据库集合 (SigLIP + DINOv2)
    
    创建两个集合：
    - PARTS_SIGLIP_SO400M_1152D_V1: SigLIP 图文特征 (1152维)
    - PARTS_DINOV2_LARGE_1024D_V1: DINOv2 视觉特征 (1024维)
    
    注意：
    - 如果集合已存在，将跳过创建
    - 此接口只创建集合结构，不建立索引
    - 建立索引请调用 /v2/index/rebuild 接口
    """
    await RailwayPartsManager.create_v2_collections(drop_existing=False)
    
    return {
        'message': 'V2 collections initialized successfully',
        'next_step': 'Call /v2/index/rebuild to build index'
    }


@parts_router.post('/v2/index/rebuild', tags=["算法-向量检索V2"], summary='重建V2索引')
async def rebuild_v2_index(
    item_id: str = None,
    limit: int = None,
    background_tasks: BackgroundTasks = None
):
    """
    重建V2向量索引 (SigLIP + DINOv2)
    
    参数：
    - item_id: 指定配件ID（可选，为空则重建所有）
    - limit: 限制处理数量（可选，用于测试，如 limit=10 只处理10条数据）
    - background_tasks: 后台任务（自动传入）
    
    注意：
    - 如果 limit > 100 或未指定 limit，将在后台执行
    - 小批量任务（limit <= 100）会同步执行并返回结果
    """
    # 判断是否需要后台执行
    should_background = (limit is None or limit > 100) and background_tasks is not None
    
    int_item_id = int(item_id) if item_id not in (None, "") else None

    if should_background:
        # 大批量任务放到后台执行
        background_tasks.add_task(
            RailwayPartsManager.rebuild_v2_index,
            item_id=int_item_id,
            limit=limit
        )
        return ReconstructionIndexRebuildRes(
            message='Index rebuild task started in background',
            item_id=item_id,
            limit=limit or 'all'
        )
    else:
        # 小批量任务直接执行
        result = await RailwayPartsManager.rebuild_v2_index(
            item_id=int_item_id,
            limit=limit
        )
        return {
            'message': 'Index rebuilt successfully',
            'result': result
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
